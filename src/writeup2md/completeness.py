"""TASK_19 completeness gates.

Emits ``completeness.json`` next to ``document.md`` for every
conversion. The artifact records the full invariant set:

- ``visuals_missing``: count of visual blocks without a final state.
- ``image_syntax_count``: ``![...](`` matches in the markdown.
- ``html_img_tag_count``: ``<img`` matches (case-insensitive).
- ``base64_image_uri_count``: ``data:image/...;base64`` matches.
- ``unclosed_fence_count``: unmatched triple-backtick fences.
- ``html_comment_marker_count``: ``<!-- writeup2md: -->`` matches.

A conversion that fails any invariant is routed to ``rejected``
regardless of OCR outcomes (see ``apply_completeness_to_status``).

Suspicious-document detection (19.D) forces ``rejected`` when the
output looks structurally broken even if individual invariants pass.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import Block, BlockType, Document, DocumentStatus, VisualBlockState


COMPLETENESS_JSON = "completeness.json"
QUALITY_REPORT_JSON = "quality_report.json"

# Patterns matched against the rendered document.md. We use the same
# patterns as render.py for consistency, but we re-define them here to
# keep this module independent of the renderer.
_IMAGE_MARKDOWN_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_IMAGE_HTML_RE = re.compile(r"<\s*img\b[^>]*>", re.IGNORECASE)
_BASE64_DATA_IMAGE_RE = re.compile(r"data:image/[^;]+;base64", re.IGNORECASE)
_HTML_COMMENT_MARKER_RE = re.compile(r"<!--\s*writeup2md:")

# A "fence line" is a line that starts with 3+ backticks optionally
# followed by a language tag (opening) or nothing (closing). Inner
# content lines (e.g. "```python code here") are NOT fences because
# they have non-backtick characters mixed with the backticks at line
# start. We use the same state machine as the render test.
_FENCE_LINE_RE = re.compile(r"^(`{3,})(\s*\S.*)?$")


def check_completeness(
    *,
    document: Document,
    markdown_text: str,
    markdown_path: Path,
    mode: str = "document",
) -> dict[str, Any]:
    """Compute the completeness invariants for a rendered document.

    Returns a dict matching the ``completeness.json`` schema (19.A).
    """
    blocks = document.blocks
    visuals = [b for b in blocks if b.type == BlockType.VISUAL]
    visuals_missing = sum(
        1 for b in visuals
        if b.visual_state is None
        or (b.coverage_state is None and b.visual_state != VisualBlockState.IGNORED_DECORATIVE)
    )

    image_syntax_count = len(_IMAGE_MARKDOWN_RE.findall(markdown_text))
    html_img_tag_count = len(_IMAGE_HTML_RE.findall(markdown_text))
    base64_image_uri_count = len(_BASE64_DATA_IMAGE_RE.findall(markdown_text))
    html_comment_marker_count = len(_HTML_COMMENT_MARKER_RE.findall(markdown_text))
    unclosed_fence_count = _count_unclosed_fences(markdown_text)

    invariants = {
        "visuals_missing": visuals_missing,
        "image_syntax_count": image_syntax_count,
        "html_img_tag_count": html_img_tag_count,
        "base64_image_uri_count": base64_image_uri_count,
        "unclosed_fence_count": unclosed_fence_count,
        "html_comment_marker_count": html_comment_marker_count,
    }

    # In document mode, all 6 invariants must be 0. In strict mode,
    # html_comment_marker_count is allowed (the review UI uses them).
    failed: list[str] = []
    for name, value in invariants.items():
        if name == "html_comment_marker_count" and mode == "strict":
            continue
        if value != 0:
            failed.append(name)

    total = len(invariants)
    passed = total - len(failed)

    md_bytes = markdown_text.encode("utf-8")
    md_sha = hashlib.sha256(md_bytes).hexdigest()

    return {
        "document_id": document.manifest.document_id,
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": mode,
        "invariants": invariants,
        "summary": {
            "total_invariants": total,
            "passed": passed,
            "failed": len(failed),
        },
        "failed_invariants": failed,
        "markdown_path": markdown_path.name,
        "markdown_sha256": md_sha,
        "markdown_byte_count": len(md_bytes),
    }


def _count_unclosed_fences(markdown_text: str) -> int:
    """Walk the markdown line-by-line. Return the number of unmatched
    opening fences at end-of-document (0 if all fences are matched)."""
    in_code = False
    fence_len = 0
    for line in markdown_text.split("\n"):
        m = _FENCE_LINE_RE.match(line)
        if not m:
            continue
        this_len = len(m.group(1))
        has_content = m.group(2) is not None
        if not in_code:
            in_code = True
            fence_len = this_len
        else:
            if not has_content and this_len >= fence_len:
                in_code = False
                fence_len = 0
    return 1 if in_code else 0


def is_suspicious_document(document: Document, markdown_text: str) -> tuple[bool, str]:
    """TASK_19.D suspicious-document detection.

    Returns ``(is_suspicious, reason)``. A suspicious document is
    routed to ``rejected`` even if individual invariants pass.

    Conservative: only fires when the output is clearly broken (no
    native text at all AND every non-decorative visual routed to
    review, suggesting a pipeline issue rather than legitimate
    difficult content).
    """
    blocks = document.blocks
    visuals = [b for b in blocks if b.type == BlockType.VISUAL]
    native_text_blocks = [
        b for b in blocks
        if b.type == BlockType.PARAGRAPH and (b.text or "").strip()
    ]

    # Suspicious case 1: zero native text AND multiple non-decorative
    # visuals all routed to review. Single-visual review is legitimate
    # (the visual is just hard to OCR); N>1 visuals all failing
    # without any native text suggests the pipeline itself is broken.
    if not native_text_blocks and visuals:
        transcribed = sum(
            1 for b in visuals
            if b.visual_state in (
                VisualBlockState.RESOLVED_OCR,
                VisualBlockState.RESOLVED_NATIVE,
                VisualBlockState.RESOLVED_STRUCTURED,
            )
        )
        failed = sum(1 for b in visuals if b.visual_state == VisualBlockState.FAILED)
        ignored = sum(1 for b in visuals if b.visual_state == VisualBlockState.IGNORED_DECORATIVE)
        non_decorative = len(visuals) - ignored
        if transcribed == 0 and failed == 0 and non_decorative >= 2:
            return True, (
                f"no native text and all {non_decorative} non-decorative visuals "
                "routed to review; likely pipeline issue"
            )

    # Suspicious case 2: PDF input with suspiciously short output.
    # Multiple pages but < 100 chars of markdown.
    if len(markdown_text.strip()) < 100:
        page_count = 0
        try:
            page_count = int(document.manifest.extra.get("page_range", {}).get("stop", 0)) if document.manifest.extra else 0
        except Exception:  # noqa: BLE001
            pass
        if page_count >= 2:
            return True, f"markdown < 100 chars on {page_count}-page input"

    return False, ""


def apply_completeness_to_status(
    *,
    status: DocumentStatus,
    completeness: dict[str, Any],
    is_suspicious: bool,
) -> tuple[DocumentStatus, list[str]]:
    """Apply completeness invariants to the document status.

    Returns ``(new_status, reasons)``. ``reasons`` lists the
    completeness failures that forced the status change.
    """
    reasons: list[str] = []
    if completeness["summary"]["failed"] > 0:
        reasons.append(
            f"completeness invariants failed: {', '.join(completeness['failed_invariants'])}"
        )
        return DocumentStatus.REJECTED, reasons
    if is_suspicious:
        reasons.append("document flagged as suspicious")
        return DocumentStatus.REJECTED, reasons
    return status, reasons


def write_completeness_artifacts(
    *,
    document_dir: Path,
    document: Document,
    markdown_text: str,
    mode: str = "document",
    diagnostics: Any = None,
    backend_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write ``completeness.json`` and ``quality_report.json`` to the
    document directory. Returns the completeness dict.
    """
    md_path = document_dir / "document.md"
    completeness = check_completeness(
        document=document,
        markdown_text=markdown_text,
        markdown_path=md_path,
        mode=mode,
    )
    (document_dir / COMPLETENESS_JSON).write_text(
        json.dumps(completeness, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # quality_report.json — human-readable summary.
    report = _build_quality_report(
        document=document,
        completeness=completeness,
        diagnostics=diagnostics,
        backend_info=backend_info,
    )
    (document_dir / QUALITY_REPORT_JSON).write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return completeness


def _build_quality_report(
    *,
    document: Document,
    completeness: dict[str, Any],
    diagnostics: Any = None,
    backend_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the human-readable ``quality_report.json``."""
    out: dict[str, Any] = {
        "document_id": document.manifest.document_id,
        "status": document.manifest.status.value,
        "mode": completeness.get("mode", "document"),
        "completeness": {
            "passed": completeness["summary"]["passed"],
            "failed": completeness["summary"]["failed"],
            "failed_invariants": completeness["failed_invariants"],
        },
    }
    if diagnostics is not None:
        # Visual coverage ledger.
        vc = getattr(diagnostics, "visual_coverage", None)
        if vc is not None:
            vc_dict = vc if isinstance(vc, dict) else (
                vc.model_dump(mode="json") if hasattr(vc, "model_dump") else vars(vc)
            )
            out["visual_coverage"] = vc_dict
        # Top 5 warnings.
        warnings = getattr(diagnostics, "processing_warnings", None) or []
        out["top_warnings"] = list(warnings[:5])
    if backend_info:
        out["backend"] = {
            k: backend_info.get(k)
            for k in ("backend", "backend_version", "model_repo", "model_revision")
            if backend_info.get(k) is not None
        }
    return out
