"""Golden Set OCR evaluation.

Runs a real OCR backend over a Golden Set directory and computes accuracy
metrics globally and by visual type. Never uses the mock backend — if `auto`
resolves to mock or no real backend is available, evaluation fails.

Public entry points:
- `evaluate_golden_set(golden_dir, backend_name, output_dir)` — runs eval,
  writes per-sample and aggregate reports, returns the summary dict.
- `compute_metrics(gold, actual, sample)` — pure function computing all
  metrics for one sample. Reusable by tests.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .ocr.backend import get_backend, reset_backend, available_backends


# ---------------------------------------------------------------------------
# Character-level utilities
# ---------------------------------------------------------------------------

_LEVENSTEIN_CACHE: dict[tuple[str, str], int] = {}


def _levenshtein(a: str, b: str) -> int:
    """Compute Levenshtein distance with a tiny cache for repeated pairs."""
    key = (a, b)
    cached = _LEVENSTEIN_CACHE.get(key)
    if cached is not None:
        return cached
    if not a:
        result = len(b)
    elif not b:
        result = len(a)
    else:
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a, 1):
            cur = [i]
            for j, cb in enumerate(b, 1):
                cost = 0 if ca == cb else 1
                cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost))
            prev = cur
        result = prev[-1]
    if len(_LEVENSTEIN_CACHE) < 4096:
        _LEVENSTEIN_CACHE[key] = result
    return result


def _cer(gold: str, actual: str) -> float:
    """Character error rate: Levenshtein / max(len(gold), 1)."""
    if not gold:
        return 0.0 if not actual else 1.0
    return _levenshtein(gold, actual) / len(gold)


def _char_accuracy(gold: str, actual: str) -> float:
    return max(0.0, 1.0 - _cer(gold, actual))


# ---------------------------------------------------------------------------
# Token / line / structural metrics
# ---------------------------------------------------------------------------

def _line_metrics(gold: str, actual: str) -> dict[str, Any]:
    g_lines = gold.splitlines()
    a_lines = actual.splitlines()
    g_set = set(g_lines)
    a_set = set(a_lines)
    exact_line_match = g_lines == a_lines
    missing = sum(1 for ln in g_lines if ln not in a_set)
    extra = sum(1 for ln in a_lines if ln not in g_set)
    return {
        "exact_line_match": exact_line_match,
        "gold_line_count": len(g_lines),
        "actual_line_count": len(a_lines),
        "missing_line_count": missing,
        "extra_line_count": extra,
        "missing_line_rate": missing / max(1, len(g_lines)),
        "extra_line_rate": extra / max(1, len(a_lines)),
    }


def _indentation_metrics(gold: str, actual: str) -> dict[str, Any]:
    g_lines = gold.splitlines()
    a_lines = actual.splitlines()
    n = min(len(g_lines), len(a_lines))
    if n == 0:
        return {"indentation_exact_match": True, "leading_whitespace_accuracy": 1.0}
    indent_match = 0
    leading_ws_total = 0
    leading_ws_correct = 0
    for i in range(n):
        g_ws = len(g_lines[i]) - len(g_lines[i].lstrip(" \t"))
        a_ws = len(a_lines[i]) - len(a_lines[i].lstrip(" \t"))
        if g_ws == a_ws:
            indent_match += 1
        leading_ws_total += 1
        if g_ws == a_ws:
            leading_ws_correct += 1
    return {
        "indentation_exact_match": indent_match == n,
        "indentation_match_rate": indent_match / n,
        "leading_whitespace_accuracy": leading_ws_correct / max(1, leading_ws_total),
    }


_PUNCT_CATEGORIES = {
    "quotes": ("'", '"', "`"),
    "brackets": ("(", ")", "[", "]", "{", "}", "<", ">"),
    "slash_backslash": ("/", "\\"),
    "underscore_hyphen": ("_", "-"),
    "colon_semicolon": (":", ";"),
    "equals": ("=",),
    "pipe": ("|",),
    "at": ("@",),
    "hash": ("#",),
    "dollar": ("$",),
}


def _punctuation_accuracy(gold: str, actual: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for name, chars in _PUNCT_CATEGORIES.items():
        g_count = sum(gold.count(c) for c in chars)
        a_count = sum(actual.count(c) for c in chars)
        if g_count == 0:
            out[name] = 1.0 if a_count == 0 else 0.0
        else:
            # accuracy = 1 - (|g_count - a_count| / max(g_count, a_count))
            denom = max(g_count, a_count, 1)
            out[name] = max(0.0, 1.0 - abs(g_count - a_count) / denom)
    return out


def _digit_accuracy(gold: str, actual: str) -> float:
    g = sum(c.isdigit() for c in gold)
    a = sum(c.isdigit() for c in actual)
    if g == 0:
        return 1.0 if a == 0 else 0.0
    return max(0.0, 1.0 - abs(g - a) / max(g, a, 1))


_URL_RE = re.compile(r"https?://[^\s'\"<>)]+")
_HASH_RE = re.compile(r"\b[a-f0-9]{32,64}\b", re.IGNORECASE)


def _exact_match_for_pattern(gold: str, actual: str, pattern: re.Pattern[str]) -> dict[str, Any]:
    g = set(pattern.findall(gold))
    a = set(pattern.findall(actual))
    if not g:
        return {"present_in_gold": False, "exact_match": True, "matched": 0, "total": 0}
    matched = len(g & a)
    return {
        "present_in_gold": True,
        "exact_match": g == a,
        "matched": matched,
        "total": len(g),
        "recall": matched / len(g),
    }


def _critical_token_recall(gold: str, actual: str, tokens: list[str]) -> dict[str, Any]:
    if not tokens:
        return {"recall": 1.0, "matched": 0, "total": 0, "missing": []}
    actual_lower = actual.lower()
    matched = []
    missing = []
    for tok in tokens:
        if tok.lower() in actual_lower:
            matched.append(tok)
        else:
            missing.append(tok)
    return {
        "recall": len(matched) / len(tokens),
        "matched": len(matched),
        "total": len(tokens),
        "missing": missing,
    }


# ---------------------------------------------------------------------------
# Visual-type / language classification accuracy (uses router)
# ---------------------------------------------------------------------------

def _classify_visual_type(text: str) -> str:
    """Use the router to predict a visual type from text. Returns a string."""
    from .ocr.router import classify_from_text
    from .models import VisualType
    predicted = classify_from_text(text, fallback=VisualType.UNKNOWN)
    return predicted.value


def _detect_language(text: str, vtype: str) -> str | None:
    from .ocr.router import detect_language
    from .models import VisualType
    try:
        vt = VisualType(vtype) if vtype else VisualType.UNKNOWN
    except ValueError:
        vt = VisualType.UNKNOWN
    return detect_language(text, vt)


# ---------------------------------------------------------------------------
# Editor line-number removal accuracy
# ---------------------------------------------------------------------------

_LINENO_RE = re.compile(r"^\s*\d+[\s\.)\]]+")


def _strip_line_numbers(text: str) -> str:
    from .ocr.postprocess import _strip_editor_line_numbers
    result = _strip_editor_line_numbers(text)
    # _strip_editor_line_numbers returns (text, transformations) tuple.
    if isinstance(result, tuple):
        return result[0]
    return result


def _line_number_removal_accuracy(sample: dict, actual: str) -> dict[str, Any]:
    """If the sample has line numbers, did postprocessing strip them?"""
    if not sample.get("line_numbers_present"):
        return {"applicable": False}
    # Re-run the stripper on the actual output and see if any line still starts
    # with digits+whitespace.
    stripped = _strip_line_numbers(actual)
    raw_leading_lineno = sum(1 for ln in actual.splitlines() if _LINENO_RE.match(ln))
    stripped_leading_lineno = sum(1 for ln in stripped.splitlines() if _LINENO_RE.match(ln))
    return {
        "applicable": True,
        "raw_lines_with_lineno": raw_leading_lineno,
        "remaining_lines_with_lineno": stripped_leading_lineno,
        "removal_accuracy": (
            1.0 if raw_leading_lineno == 0
            else max(0.0, 1.0 - stripped_leading_lineno / raw_leading_lineno)
        ),
    }


# ---------------------------------------------------------------------------
# Command/output segmentation F1
# ---------------------------------------------------------------------------

def _segment_command_output(text: str) -> list[dict[str, str]]:
    """Return list of {role: command|output, text: line}."""
    from .ocr.postprocess import split_terminal_commands
    segments = split_terminal_commands(text)
    out = []
    for seg in segments:
        role = seg.get("role", "output")
        for line in seg.get("text", "").splitlines():
            out.append({"role": role, "text": line})
    return out


def _segmentation_f1(gold: str, actual: str, sample_vtype: str) -> dict[str, Any]:
    if sample_vtype != "terminal":
        return {"applicable": False}
    g_seg = _segment_command_output(gold)
    a_seg = _segment_command_output(actual)
    if not g_seg:
        return {"applicable": True, "precision": 1.0, "recall": 1.0, "f1": 1.0}
    # Match by (role, text) equality on a per-line basis.
    g_set = {(s["role"], s["text"]) for s in g_seg}
    a_set = {(s["role"], s["text"]) for s in a_seg}
    tp = len(g_set & a_set)
    fp = len(a_set - g_set)
    fn = len(g_set - a_set)
    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)
    f1 = 0.0 if (precision + recall) == 0 else 2 * precision * recall / (precision + recall)
    return {
        "applicable": True,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "tp": tp,
        "fp": fp,
        "fn": fn,
    }


# ---------------------------------------------------------------------------
# Hallucination rate
# ---------------------------------------------------------------------------

_PLAUSIBLE_CONFUSABLES = {
    # Common OCR confusions we do NOT count as hallucinations.
    "0": "O",
    "O": "0",
    "1": "lI",
    "l": "1I",
    "I": "l1",
    "5": "S",
    "S": "5",
    "2": "Z",
    "Z": "2",
    "B": "8",
    "8": "B",
    "rn": "m",
    "m": "rn",
    "cl": "d",
    "vv": "w",
    ",": ".",
    ".": ",",
    "；": ";",
    ";": "；",
    "，": ",",
    ",": "，",
    "（": "(",
    "(": "（",
    "）": ")",
    ")": "）",
    "　": " ",
    " ": "　",
    "''": "\"",
    "\"": "''",
    "‘": "'",
    "’": "'",
    "“": "\"",
    "”": "\"",
}


def _is_plausible_substitution(g_char: str, a_char: str) -> bool:
    if g_char == a_char:
        return True
    confusables = _PLAUSIBLE_CONFUSABLES.get(g_char, "")
    if a_char in confusables:
        return True
    # Also accept if both are whitespace or both are punctuation of similar class.
    if g_char.isspace() and a_char.isspace():
        return True
    return False


def _hallucination_rate(gold: str, actual: str) -> dict[str, Any]:
    """Chars in `actual` that are neither in gold nor plausible substitutions.

    We align `actual` against `gold` greedily (not optimal alignment, but a
    cheap heuristic). For each char in `actual`, we check if it appears
    somewhere in `gold` OR is a plausible substitution for some char in gold.
    """
    if not actual:
        return {"rate": 0.0, "hallucinated_chars": 0, "total_chars": 0}
    gold_set = set(gold)
    hallucinated = 0
    for ch in actual:
        if ch in gold_set:
            continue
        # Check if it is a plausible substitute for any gold char.
        plausible = False
        for g_ch in gold_set:
            if _is_plausible_substitution(g_ch, ch):
                plausible = True
                break
        if not plausible:
            hallucinated += 1
    return {
        "rate": hallucinated / len(actual),
        "hallucinated_chars": hallucinated,
        "total_chars": len(actual),
    }


# ---------------------------------------------------------------------------
# Main metric computation
# ---------------------------------------------------------------------------

@dataclass
class SampleMetrics:
    sample_id: str
    visual_type: str
    language: str
    cer: float
    char_accuracy: float
    exact_match: bool
    line: dict[str, Any] = field(default_factory=dict)
    indentation: dict[str, Any] = field(default_factory=dict)
    punctuation: dict[str, float] = field(default_factory=dict)
    digit_accuracy: float = 0.0
    url: dict[str, Any] = field(default_factory=dict)
    hash: dict[str, Any] = field(default_factory=dict)
    critical_tokens: dict[str, Any] = field(default_factory=dict)
    visual_type_classification_correct: bool = False
    language_detection_correct: bool = False
    segmentation: dict[str, Any] = field(default_factory=dict)
    line_number_removal: dict[str, Any] = field(default_factory=dict)
    hallucination: dict[str, Any] = field(default_factory=dict)
    ocr_backend: str = ""
    ocr_confidence: float = 0.0
    raw_ocr_text: str = ""
    gold_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "visual_type": self.visual_type,
            "language": self.language,
            "cer": self.cer,
            "char_accuracy": self.char_accuracy,
            "exact_match": self.exact_match,
            "line": self.line,
            "indentation": self.indentation,
            "punctuation": self.punctuation,
            "digit_accuracy": self.digit_accuracy,
            "url": self.url,
            "hash": self.hash,
            "critical_tokens": self.critical_tokens,
            "visual_type_classification_correct": self.visual_type_classification_correct,
            "language_detection_correct": self.language_detection_correct,
            "segmentation": self.segmentation,
            "line_number_removal": self.line_number_removal,
            "hallucination": self.hallucination,
            "ocr_backend": self.ocr_backend,
            "ocr_confidence": self.ocr_confidence,
            "raw_ocr_text": self.raw_ocr_text,
            "gold_text": self.gold_text,
        }


def compute_metrics(gold: str, actual: str, sample: dict) -> SampleMetrics:
    """Compute all metrics for one sample. Pure function."""
    sid = sample.get("sample_id", "")
    vtype = sample.get("visual_type", "other")
    lang = sample.get("language", "")
    cer = _cer(gold, actual)
    char_acc = _char_accuracy(gold, actual)
    exact = gold.strip() == actual.strip()
    line_m = _line_metrics(gold, actual)
    indent_m = _indentation_metrics(gold, actual)
    punct = _punctuation_accuracy(gold, actual)
    digit = _digit_accuracy(gold, actual)
    url_m = _exact_match_for_pattern(gold, actual, _URL_RE)
    hash_m = _exact_match_for_pattern(gold, actual, _HASH_RE)
    crit = _critical_token_recall(gold, actual, sample.get("critical_tokens", []))
    # Classification accuracy
    predicted_vtype = _classify_visual_type(actual)
    vtype_correct = predicted_vtype == vtype
    predicted_lang = _detect_language(actual, vtype)
    lang_correct = (predicted_lang == lang) or (lang in ("http", "diff", "log", "yaml", "json", "ini", "toml") and predicted_lang is None)
    seg = _segmentation_f1(gold, actual, vtype)
    lineno = _line_number_removal_accuracy(sample, actual)
    halluc = _hallucination_rate(gold, actual)
    return SampleMetrics(
        sample_id=sid,
        visual_type=vtype,
        language=lang,
        cer=cer,
        char_accuracy=char_acc,
        exact_match=exact,
        line=line_m,
        indentation=indent_m,
        punctuation=punct,
        digit_accuracy=digit,
        url=url_m,
        hash=hash_m,
        critical_tokens=crit,
        visual_type_classification_correct=vtype_correct,
        language_detection_correct=lang_correct,
        segmentation=seg,
        line_number_removal=lineno,
        hallucination=halluc,
    )


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def aggregate(metrics: list[SampleMetrics]) -> dict[str, Any]:
    n = len(metrics)
    if n == 0:
        return {"sample_count": 0}
    cers = [m.cer for m in metrics]
    char_accs = [m.char_accuracy for m in metrics]
    exacts = [1.0 if m.exact_match else 0.0 for m in metrics]
    exact_lines = [1.0 if m.line.get("exact_line_match") else 0.0 for m in metrics]
    missing_rates = [m.line.get("missing_line_rate", 0.0) for m in metrics]
    extra_rates = [m.line.get("extra_line_rate", 0.0) for m in metrics]
    indent_matches = [1.0 if m.indentation.get("indentation_exact_match") else 0.0 for m in metrics]
    leading_ws = [m.indentation.get("leading_whitespace_accuracy", 0.0) for m in metrics]
    digit_accs = [m.digit_accuracy for m in metrics]
    crit_recalls = [m.critical_tokens.get("recall", 1.0) for m in metrics]
    vtype_correct = [1.0 if m.visual_type_classification_correct else 0.0 for m in metrics]
    lang_correct = [1.0 if m.language_detection_correct else 0.0 for m in metrics]
    hall_rates = [m.hallucination.get("rate", 0.0) for m in metrics]

    # Aggregate punctuation.
    punct_keys = _PUNCT_CATEGORIES.keys()
    punct_avg: dict[str, float] = {}
    for k in punct_keys:
        punct_avg[k] = _mean([m.punctuation.get(k, 0.0) for m in metrics])

    # Segmentation only for terminal samples.
    seg_samples = [m for m in metrics if m.segmentation.get("applicable")]
    seg_f1 = _mean([m.segmentation.get("f1", 0.0) for m in seg_samples]) if seg_samples else None

    # Line-number removal for applicable samples.
    lineno_samples = [m for m in metrics if m.line_number_removal.get("applicable")]
    lineno_acc = _mean([m.line_number_removal.get("removal_accuracy", 0.0) for m in lineno_samples]) if lineno_samples else None

    # URL / hash exact match (only samples that have them).
    url_samples = [m for m in metrics if m.url.get("present_in_gold")]
    url_match = _mean([1.0 if m.url.get("exact_match") else 0.0 for m in url_samples]) if url_samples else None
    hash_samples = [m for m in metrics if m.hash.get("present_in_gold")]
    hash_match = _mean([1.0 if m.hash.get("exact_match") else 0.0 for m in hash_samples]) if hash_samples else None

    return {
        "sample_count": n,
        "cer_mean": _mean(cers),
        "cer_min": min(cers),
        "cer_max": max(cers),
        "char_accuracy_mean": _mean(char_accs),
        "exact_match_rate": _mean(exacts),
        "exact_line_match_rate": _mean(exact_lines),
        "missing_line_rate_mean": _mean(missing_rates),
        "extra_line_rate_mean": _mean(extra_rates),
        "indentation_exact_match_rate": _mean(indent_matches),
        "leading_whitespace_accuracy_mean": _mean(leading_ws),
        "punctuation_accuracy_mean": punct_avg,
        "digit_accuracy_mean": _mean(digit_accs),
        "critical_token_recall_mean": _mean(crit_recalls),
        "visual_type_classification_accuracy": _mean(vtype_correct),
        "language_detection_accuracy": _mean(lang_correct),
        "segmentation_f1_mean": seg_f1,
        "line_number_removal_accuracy_mean": lineno_acc,
        "url_exact_match_rate": url_match,
        "hash_exact_match_rate": hash_match,
        "hallucination_rate_mean": _mean(hall_rates),
    }


def aggregate_by_visual_type(metrics: list[SampleMetrics]) -> dict[str, dict[str, Any]]:
    by: dict[str, list[SampleMetrics]] = {}
    for m in metrics:
        by.setdefault(m.visual_type, []).append(m)
    return {vtype: aggregate(ms) for vtype, ms in by.items()}


# ---------------------------------------------------------------------------
# Confidence calibration
# ---------------------------------------------------------------------------

def calibrate_confidence(metrics: list[SampleMetrics], thresholds: tuple[float, float]) -> dict[str, Any]:
    """Compute false-accept / false-review rates under given thresholds.

    thresholds = (low, high). A sample with ocr_confidence >= high is
    "accepted"; < low is "review_required"; between is "review_required".
    So accepted = confidence >= high.
    """
    low, high = thresholds
    accepted = [m for m in metrics if m.ocr_confidence >= high]
    review = [m for m in metrics if low <= m.ocr_confidence < high]
    rejected = [m for m in metrics if m.ocr_confidence < low]

    def _acc_pass(m: SampleMetrics, threshold_cer: float = 0.05) -> bool:
        # "Correct enough to auto-accept" = CER below threshold AND all critical tokens present.
        if m.cer > threshold_cer:
            return False
        if m.critical_tokens.get("total", 0) > 0 and m.critical_tokens.get("recall", 1.0) < 1.0:
            return False
        return True

    # False accept = accepted by confidence but fails accuracy gate.
    false_accepts = [m for m in accepted if not _acc_pass(m)]
    # False review = routed to review but actually passes accuracy gate.
    false_reviews = [m for m in review if _acc_pass(m)]

    accepted_precision = (
        1.0 - len(false_accepts) / len(accepted) if accepted else 1.0
    )
    review_precision = (
        1.0 - len(false_reviews) / len(review) if review else 1.0
    )

    return {
        "thresholds": {"low": low, "high": high},
        "accepted_count": len(accepted),
        "review_count": len(review),
        "rejected_count": len(rejected),
        "accepted_precision": accepted_precision,
        "review_precision": review_precision,
        "false_accept_count": len(false_accepts),
        "false_review_count": len(false_reviews),
        "false_accept_rate": len(false_accepts) / max(1, len(accepted)),
        "false_review_rate": len(false_reviews) / max(1, len(review)),
        "accepted_mean_cer": _mean([m.cer for m in accepted]) if accepted else None,
        "review_mean_cer": _mean([m.cer for m in review]) if review else None,
        "rejected_mean_cer": _mean([m.cer for m in rejected]) if rejected else None,
    }


# ---------------------------------------------------------------------------
# Top-level evaluation
# ---------------------------------------------------------------------------

def evaluate_golden_set(
    golden_dir: Path | str,
    *,
    backend_name: str = "auto",
    output_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Run OCR over the Golden Set, compute metrics, write reports.

    Returns the aggregate summary dict. Raises if no real backend available
    or if the selected backend is mock.
    """
    golden = Path(golden_dir)
    manifest_path = golden / "manifest.jsonl"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"manifest not found: {manifest_path}")

    avail = available_backends()
    if not avail:
        raise RuntimeError(
            "no real OCR backend available; install rapidocr-onnxruntime, "
            "paddleocr, or mlx-vlm. mock is not accepted for evaluation."
        )

    reset_backend()
    backend = get_backend(backend_name)
    if getattr(backend, "name", "") == "mock":
        raise RuntimeError(
            "evaluate_golden_set refused to use mock backend. "
            "Install a real OCR backend."
        )

    samples: list[dict] = []
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        samples.append(json.loads(line))

    all_metrics: list[SampleMetrics] = []
    per_sample_records: list[dict] = []

    for sample in samples:
        sid = sample["sample_id"]
        img_path = golden / sample["image_path"]
        if not img_path.is_file():
            per_sample_records.append({
                "sample_id": sid,
                "error": f"image missing: {img_path}",
            })
            continue
        image_bytes = img_path.read_bytes()
        try:
            result = backend.recognize(image_bytes)
        except Exception as e:  # noqa: BLE001
            per_sample_records.append({
                "sample_id": sid,
                "error": f"ocr failed: {e}",
            })
            continue
        actual = result.joined_text
        gold = sample["gold_verbatim"]
        m = compute_metrics(gold, actual, sample)
        m.ocr_backend = result.backend
        m.ocr_confidence = result.model_confidence
        m.raw_ocr_text = actual
        m.gold_text = gold
        all_metrics.append(m)
        per_sample_records.append(m.to_dict())

    summary = aggregate(all_metrics)
    by_vtype = aggregate_by_visual_type(all_metrics)

    # Calibration under the CURRENT (TASK_09) production thresholds.
    # The enricher uses (low=0.6, high=0.99) — high raised from 0.85 to 0.99
    # because rapidocr confidence is uncalibrated and 0.85 admitted blocks
    # with ~17% CER (accepted_precision 0.07). Under (0.6, 0.99) almost no
    # blocks auto-accept, which is the conservative correct behavior until
    # a better-calibrated confidence source exists.
    calibration = calibrate_confidence(all_metrics, thresholds=(0.6, 0.99))
    # Also compute the legacy (0.6, 0.85) for comparison so the report shows
    # why the change was made.
    calibration_legacy = calibrate_confidence(all_metrics, thresholds=(0.6, 0.85))

    out: dict[str, Any] = {
        "backend": backend.name,
        "backend_version": backend.version,
        "is_mock": False,
        "sample_count": len(all_metrics),
        "summary": summary,
        "by_visual_type": by_vtype,
        "calibration": calibration,
        "calibration_legacy_thresholds": calibration_legacy,
    }

    if output_dir is not None:
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "results.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in per_sample_records) + "\n",
            encoding="utf-8",
        )
        (out_dir / "summary.json").write_text(
            json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (out_dir / "by_visual_type.json").write_text(
            json.dumps(by_vtype, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        # Also write the canonical reports/ copies.
        reports_dir = Path("reports")
        reports_dir.mkdir(parents=True, exist_ok=True)
        (reports_dir / "GOLDEN_SET_METRICS.json").write_text(
            json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (reports_dir / "GOLDEN_SET_METRICS.md").write_text(
            _render_markdown(out, by_vtype, calibration, calibration_legacy),
            encoding="utf-8",
        )

    return out


def _render_markdown(out: dict, by_vtype: dict, calibration: dict, calibration_legacy: dict | None = None) -> str:
    s = out["summary"]
    lines = [
        "# Golden Set OCR Metrics",
        "",
        f"- Backend: `{out['backend']}` v{out['backend_version']}",
        f"- Is mock: `{out['is_mock']}`",
        f"- Sample count: `{s['sample_count']}`",
        "",
        "## Aggregate metrics",
        "",
        f"- CER mean: `{s['cer_mean']:.4f}` (min `{s['cer_min']:.4f}`, max `{s['cer_max']:.4f}`)",
        f"- Character accuracy mean: `{s['char_accuracy_mean']:.4f}`",
        f"- Exact full-sample match rate: `{s['exact_match_rate']:.4f}`",
        f"- Exact line match rate: `{s['exact_line_match_rate']:.4f}`",
        f"- Missing-line rate mean: `{s['missing_line_rate_mean']:.4f}`",
        f"- Extra-line rate mean: `{s['extra_line_rate_mean']:.4f}`",
        f"- Indentation exact-match rate: `{s['indentation_exact_match_rate']:.4f}`",
        f"- Leading-whitespace accuracy mean: `{s['leading_whitespace_accuracy_mean']:.4f}`",
        f"- Digit accuracy mean: `{s['digit_accuracy_mean']:.4f}`",
        f"- Critical-token recall mean: `{s['critical_token_recall_mean']:.4f}`",
        f"- Visual-type classification accuracy: `{s['visual_type_classification_accuracy']:.4f}`",
        f"- Language-detection accuracy: `{s['language_detection_accuracy']:.4f}`",
        f"- Segmentation F1 (terminal): " + (
            "n/a" if s.get("segmentation_f1_mean") is None else f"`{s['segmentation_f1_mean']:.4f}`"
        ),
        f"- Line-number removal accuracy: " + (
            "n/a" if s.get("line_number_removal_accuracy_mean") is None else f"`{s['line_number_removal_accuracy_mean']:.4f}`"
        ),
        f"- URL exact-match rate: " + (
            "n/a" if s.get("url_exact_match_rate") is None else f"`{s['url_exact_match_rate']:.4f}`"
        ),
        f"- Hash exact-match rate: " + (
            "n/a" if s.get("hash_exact_match_rate") is None else f"`{s['hash_exact_match_rate']:.4f}`"
        ),
        f"- Hallucination rate mean: `{s['hallucination_rate_mean']:.4f}`",
        "",
        "## Punctuation accuracy (mean)",
        "",
    ]
    for k, v in s.get("punctuation_accuracy_mean", {}).items():
        lines.append(f"- `{k}`: `{v:.4f}`")
    lines += [
        "",
        "## Metrics by visual type",
        "",
        "| visual_type | n | CER mean | char_acc | exact_match | crit_recall | vtype_acc |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for vtype, m in sorted(by_vtype.items()):
        lines.append(
            f"| {vtype} | {m['sample_count']} | "
            f"{m['cer_mean']:.4f} | {m['char_accuracy_mean']:.4f} | "
            f"{m['exact_match_rate']:.4f} | {m['critical_token_recall_mean']:.4f} | "
            f"{m['visual_type_classification_accuracy']:.4f} |"
        )
    lines += [
        "",
        "## Confidence calibration (current production thresholds low=0.6, high=0.99)",
        "",
        f"- accepted_count: `{calibration['accepted_count']}`",
        f"- review_count: `{calibration['review_count']}`",
        f"- rejected_count: `{calibration['rejected_count']}`",
        f"- accepted_precision: `{calibration['accepted_precision']:.4f}`",
        f"- review_precision: `{calibration['review_precision']:.4f}`",
        f"- false_accept_count: `{calibration['false_accept_count']}`",
        f"- false_review_count: `{calibration['false_review_count']}`",
        f"- accepted_mean_cer: " + (
            "n/a" if calibration.get("accepted_mean_cer") is None else f"`{calibration['accepted_mean_cer']:.4f}`"
        ),
        f"- review_mean_cer: " + (
            "n/a" if calibration.get("review_mean_cer") is None else f"`{calibration['review_mean_cer']:.4f}`"
        ),
        "",
    ]
    if calibration_legacy is not None:
        lines += [
            "## Legacy thresholds (low=0.6, high=0.85) — kept for comparison",
            "",
            f"- accepted_count: `{calibration_legacy['accepted_count']}`",
            f"- accepted_precision: `{calibration_legacy['accepted_precision']:.4f}`",
            f"- false_accept_count: `{calibration_legacy['false_accept_count']}`",
            "",
            "The legacy 0.85 threshold admitted blocks with mean CER ~0.17 (accepted_precision "
            "0.07), which is why the production threshold was raised to 0.99.",
            "",
        ]
    lines += [
        "## Recommendation",
        "",
    ]
    if calibration["accepted_count"] == 0:
        lines.append(
            "Under the calibrated (0.6, 0.99) thresholds, no blocks auto-accept on this "
            "Golden Set. This is the intended conservative behavior: rapidocr's confidence "
            "is uncalibrated (mean 0.94 on samples with mean CER 0.17), so the priority "
            "of high accepted-precision is met by routing everything to human review until "
            "a better-calibrated confidence source (or a higher-quality backend) is available."
        )
    elif calibration["accepted_precision"] < 0.98:
        lines.append(
            "Accepted precision is below the 0.98 target. **Recommendation**: raise the "
            "`high` confidence threshold further or add a structural-quality gate."
        )
    else:
        lines.append("Accepted precision meets the 0.98 target. Current thresholds are acceptable.")
    return "\n".join(lines) + "\n"
