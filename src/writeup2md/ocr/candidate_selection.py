"""Candidate selection across multiple OCR passes (TASK_11).

When multi-view OCR produces N candidate outputs, we pick the best one by
a STRUCTURAL score. The score rewards signals that correlate with correct
code OCR:

- balanced brackets ((), [], {});
- presence of common code keywords (def, import, return, if, for, ...);
- reasonable line-length distribution (no very long merged lines);
- presence of expected structural tokens for the visual type
  (HTTP: `HTTP/\\d`; diff: `@@`; terminal: `$` or `>` prompt);
- non-trivial space-to-character ratio (penalizes space-merging).

The score NEVER rewards invented content. It only measures how well the
text conforms to expected structural patterns. We never look up tokens in
a language model; we never repair syntax.
"""

from __future__ import annotations

import re
from typing import Any

from .backend import OcrResult


# Common keywords across Python, bash, JavaScript, Go, Rust, Java. We use a
# small, deliberately conservative set so we don't bias toward any single
# language.
_COMMON_KEYWORDS: frozenset[str] = frozenset(
    {
        # Python
        "import", "from", "def", "class", "return", "if", "else", "elif",
        "for", "while", "try", "except", "finally", "with", "as", "lambda",
        "yield", "raise", "pass", "break", "continue", "global", "nonlocal",
        "assert", "del", "in", "is", "not", "and", "or", "None", "True",
        "False", "print", "self",
        # bash / shell
        "echo", "export", "source", "alias", "function", "local", "readonly",
        "cd", "ls", "cat", "grep", "awk", "sed", "curl", "wget", "ssh", "sudo",
        "chmod", "chown", "mkdir", "rm", "cp", "mv", "touch", "exit",
        # JavaScript
        "function", "const", "let", "var", "async", "await", "new", "typeof",
        "instanceof", "this", "null", "undefined", "console",
        # Go
        "package", "func", "go", "chan", "select", "defer", "range", "map",
        # Rust
        "fn", "let", "mut", "pub", "struct", "enum", "impl", "trait", "use",
        # Java
        "public", "private", "protected", "static", "final", "void", "extends",
        "implements", "throws",
        # HTTP
        "GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "HTTP",
        "Host", "Content-Type", "Content-Length", "Authorization", "Cookie",
        "User-Agent", "Accept", "Set-Cookie", "Location", "Server", "Date",
        # JSON / YAML / INI / TOML
        "true", "false", "null",
    }
)


_BRACKET_PAIRS = {"(": ")", "[": "]", "{": "}"}


def _bracket_balance_score(text: str) -> float:
    """Return 1.0 if all brackets are balanced, else a fraction in [0, 1).

    Each unmatched opener or closer reduces the score. We count the
    running depth per bracket type; if it ever goes negative, that's a
    mismatch. At the end, any positive depth is also a mismatch.
    """
    if not text:
        return 0.0
    depths = {"(": 0, "[": 0, "{": 0}
    mismatches = 0
    total_brackets = 0
    for ch in text:
        if ch in "([{":
            depths[ch] += 1
            total_brackets += 1
        elif ch in ")]}":
            total_brackets += 1
            # Find which opener this closes.
            opener = next((o for o, c in _BRACKET_PAIRS.items() if c == ch), None)
            if opener is None:
                mismatches += 1
                continue
            if depths[opener] <= 0:
                mismatches += 1
            else:
                depths[opener] -= 1
    # Remaining open depths are also mismatches.
    mismatches += sum(depths.values())
    if total_brackets == 0:
        return 0.5  # neutral — no brackets to check
    return max(0.0, 1.0 - mismatches / total_brackets)


def _keyword_density_score(text: str) -> float:
    """Fraction of common keywords that appear as standalone words.

    Returns a value in [0, 1]. Higher is better — real code references
    many of these keywords.
    """
    if not text:
        return 0.0
    # Split on non-word boundaries so `importrequests` does NOT match
    # `import` (because it's not a standalone word).
    words = set(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", text))
    if not words:
        return 0.0
    hits = sum(1 for kw in _COMMON_KEYWORDS if kw in words)
    # Normalize: a real code block typically has 5+ keyword types; we
    # saturate at 5 so a 50-keyword file doesn't outscore a 5-keyword one.
    return min(1.0, hits / 5.0)


def _line_length_score(text: str) -> float:
    """Penalize lines that look space-merged.

    A line > 120 chars without whitespace suggests space-merging. We
    return 1.0 minus the fraction of "bad" lines.
    """
    if not text:
        return 0.0
    lines = text.splitlines()
    if not lines:
        return 0.0
    bad = 0
    for ln in lines:
        if len(ln) > 120 and " " not in ln:
            bad += 1
    return max(0.0, 1.0 - bad / len(lines))


def _space_ratio_score(text: str) -> float:
    """Higher score when there's a reasonable ratio of spaces to non-spaces.

    Space-merged text has very few spaces. Real code has roughly 1 space
    per 4-10 non-space characters. We score 1.0 when the ratio is in
    [0.05, 0.5], falling off outside that range.
    """
    if not text:
        return 0.0
    non_space = sum(1 for c in text if not c.isspace() and c != " ")
    spaces = sum(1 for c in text if c == " ")
    if non_space == 0:
        return 0.0
    ratio = spaces / non_space
    if 0.05 <= ratio <= 0.5:
        return 1.0
    if ratio < 0.05:
        # very few spaces — likely space-merged
        return ratio / 0.05
    # too many spaces — likely whitespace noise
    return max(0.0, 1.0 - (ratio - 0.5) / 0.5)


def _visual_type_structural_score(text: str, visual_type: str | None) -> float:
    """Bonus for expected structural tokens per visual type."""
    if not text or not visual_type:
        return 0.5
    if visual_type == "http":
        if re.search(r"HTTP/\d", text):
            return 1.0
        return 0.3
    if visual_type == "diff":
        if "@@" in text and ("+" in text or "-" in text):
            return 1.0
        return 0.3
    if visual_type == "terminal":
        if re.search(r"^\s*[\$>]\s", text, re.MULTILINE):
            return 1.0
        return 0.3
    if visual_type == "code":
        # Any line ending with `:` or `;` is a structural signal.
        if re.search(r":\s*$|;\s*$", text, re.MULTILINE):
            return 0.8
        return 0.5
    return 0.5


def structural_score(text: str, visual_type: str | None = None) -> float:
    """Return a structural-quality score in [0, 1].

    Weighted combination of:
    - bracket balance (25%)
    - keyword density (25%)
    - line length (15%)
    - space ratio (15%)
    - visual-type structural tokens (20%)
    """
    if not text:
        return 0.0
    return (
        0.25 * _bracket_balance_score(text)
        + 0.25 * _keyword_density_score(text)
        + 0.15 * _line_length_score(text)
        + 0.15 * _space_ratio_score(text)
        + 0.20 * _visual_type_structural_score(text, visual_type)
    )


def select_best(
    candidates: list[OcrResult], visual_type: str | None = None
) -> OcrResult | None:
    """Pick the candidate with the highest structural score.

    Ties broken by model_confidence (higher wins), then by text length
    (longer wins, up to a cap to avoid rewarding junk). Returns None if
    the candidate list is empty.
    """
    if not candidates:
        return None
    scored = []
    for c in candidates:
        text = c.joined_text
        score = structural_score(text, visual_type)
        scored.append((score, c.model_confidence, min(len(text), 1000), c))
    # Sort: score desc, confidence desc, length desc.
    scored.sort(key=lambda t: (-t[0], -t[1], -t[2]))
    return scored[0][3]
