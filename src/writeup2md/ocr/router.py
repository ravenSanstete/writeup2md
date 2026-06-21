"""Visual classification and routing.

The router classifies each visual block BEFORE OCR using contextual signals:
- the block's `extra` dict (alt text, title, src, scanned_page, embedded_image);
- the preceding and following text blocks (look for "screenshot", "terminal",
  "HTTP", "diff", "config", "log", "traceback", etc.);
- the presence of an editor-line-number pattern in any pre-extracted text.

After OCR, the post-processor re-evaluates the classification using the OCR
text itself (more reliable than context alone).
"""

from __future__ import annotations

import re
from typing import Iterable

from ..models import Block, BlockType, VisualType


_HTTP_RE = re.compile(
    r"^\s*(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS|TRACE|CONNECT)\s+\S+\s+HTTP/\d",
    re.MULTILINE,
)
_DIFF_RE = re.compile(r"^\s*(\+\+\+|---|@@|\+[^+]|\-[^-])", re.MULTILINE)
_SHELL_PROMPT_RE = re.compile(r"^\s*[\$>]\s", re.MULTILINE)
_TRACEBACK_RE = re.compile(r"\b(Traceback|Exception|Error:|File \"[^\"]+\", line \d+)", re.MULTILINE)
_LOG_LEVEL_RE = re.compile(
    r"^\s*\d{4}-\d{2}-\d{2}[\sT]\d{2}:\d{2}:\d{2}|"
    r"^\s*(DEBUG|INFO|WARN(?:ING)?|ERROR|FATAL|CRITICAL)\b",
    re.MULTILINE,
)
_YAML_RE = re.compile(r"^\s*[\w\.\-]+\s*:\s", re.MULTILINE)
_JSON_RE = re.compile(r"^\s*[\{\[]", re.MULTILINE)
_INI_RE = re.compile(r"^\s*\[[^\]]+\]\s*$", re.MULTILINE)
_EDITOR_LINE_NUM_RE = re.compile(r"^\s*\d{1,6}[\s|]", re.MULTILINE)


def classify_from_context(
    block: Block,
    *,
    preceding_text: str = "",
    following_text: str = "",
) -> VisualType:
    """Classify a visual block using contextual signals only."""
    extra = block.extra or {}
    alt = (extra.get("alt") or "").lower()
    title = (extra.get("title") or "").lower()

    # Decorative hints.
    if any(k in alt for k in ("logo", "icon", "avatar", "decorative", "sponsor")):
        return VisualType.DECORATIVE

    # Diagram / UI screenshot hints.
    if any(k in alt for k in ("diagram", "architecture", "flowchart", "graph")):
        return VisualType.DIAGRAM
    if any(k in alt for k in ("screenshot of", "screenshot:", "ui ", "interface")):
        return VisualType.UI_SCREENSHOT

    # Surrounding text hints.
    ctx = (preceding_text + "\n" + following_text).lower()
    if "http" in ctx and ("request" in ctx or "response" in ctx or "burp" in ctx):
        return VisualType.HTTP
    if "diff" in ctx or "patch" in ctx or "git diff" in ctx:
        return VisualType.DIFF
    if "terminal" in ctx or "shell" in ctx or "console" in ctx or "command line" in ctx:
        return VisualType.TERMINAL
    if "traceback" in ctx or "stack trace" in ctx or "exception" in ctx:
        return VisualType.STACK_TRACE
    if "log" in ctx and ("server" in ctx or "application" in ctx or "error" in ctx):
        return VisualType.LOG
    if "config" in ctx or "configuration" in ctx or "yaml" in ctx or "ini" in ctx:
        return VisualType.CONFIGURATION
    if "table" in ctx:
        return VisualType.TABLE

    # Default for unknown visual content.
    return VisualType.CODE


def classify_from_text(text: str, *, fallback: VisualType = VisualType.CODE) -> VisualType:
    """Re-classify a visual block using its OCR text."""
    if not text.strip():
        return fallback
    if _HTTP_RE.search(text):
        return VisualType.HTTP
    if _DIFF_RE.search(text):
        return VisualType.DIFF
    if _TRACEBACK_RE.search(text):
        return VisualType.STACK_TRACE
    if _LOG_LEVEL_RE.search(text):
        return VisualType.LOG
    if _SHELL_PROMPT_RE.search(text):
        return VisualType.TERMINAL
    if _INI_RE.search(text):
        return VisualType.CONFIGURATION
    if _JSON_RE.search(text) and text.strip().endswith(("]", "}")):
        return VisualType.CONFIGURATION
    if _YAML_RE.search(text) and ":" in text and "=" not in text:
        return VisualType.CONFIGURATION
    # If nothing specific, fall back to the contextual classification.
    return fallback


def detect_language(text: str, vtype: VisualType) -> str | None:
    """Best-effort language detection from OCR text."""
    if vtype == VisualType.HTTP:
        return "http"
    if vtype == VisualType.DIFF:
        return "diff"
    if vtype == VisualType.TERMINAL:
        return "bash"
    if vtype in (VisualType.LOG, VisualType.STACK_TRACE):
        return "log"
    if vtype == VisualType.CONFIGURATION:
        if _JSON_RE.search(text) and text.strip().endswith(("]", "}")):
            return "json"
        if _INI_RE.search(text):
            return "ini"
        if _YAML_RE.search(text):
            return "yaml"
        return None
    # Code.
    if re.search(r"^\s*def\s+\w+\s*\(", text, re.MULTILINE) or "import " in text.split("\n")[0]:
        return "python"
    if re.search(r"^\s*#include\s+[<\"]", text, re.MULTILINE) or re.search(
        r"\bint\s+main\s*\(", text
    ):
        return "cpp"
    if re.search(r"^\s*(const|let|var|function)\s+", text, re.MULTILINE):
        return "javascript"
    if re.search(r"^\s*(func|package)\s+", text, re.MULTILINE):
        return "go"
    if re.search(r"^\s*(use\s+std|fn\s+|impl\s+|mod\s+)", text, re.MULTILINE):
        return "rust"
    return None
