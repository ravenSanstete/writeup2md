"""TASK_19 completeness gate tests.

Verifies:
- completeness.json is emitted next to document.md.
- All 6 invariants are checked.
- --strict CLI flag switches to strict mode.
- Suspicious-document detection forces rejected status.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from writeup2md.completeness import (
    check_completeness,
    is_suspicious_document,
    apply_completeness_to_status,
    _count_unclosed_fences,
)
from writeup2md.models import (
    Block,
    BlockType,
    Document,
    DocumentStatus,
    Manifest,
    SourceRecord,
    SourceType,
    VisualBlockState,
    VisualType,
)


def _make_doc(blocks: list[Block]) -> Document:
    return Document(
        manifest=Manifest(
            document_id="d",
            source="x",
            source_type=SourceType.HTML,
            canonical_source="x",
            captured_at="2026-06-20T00:00:00Z",
            content_sha256="a" * 64,
            config_sha256="b" * 64,
            status=DocumentStatus.ACCEPTED,
        ),
        source=SourceRecord(
            source_type=SourceType.HTML,
            source="x",
            canonical_source="x",
            captured_at="2026-06-20T00:00:00Z",
            content_sha256="a" * 64,
        ),
        blocks=blocks,
    )


def test_check_completeness_clean_document_passes_all_invariants(tmp_path: Path):
    blocks = [
        Block(block_id="b_000000", order=0, type=BlockType.HEADING, text="Title", heading_level=1),
        Block(block_id="b_000001", order=1, type=BlockType.PARAGRAPH, text="Body text."),
        Block(
            block_id="b_000002",
            order=2,
            type=BlockType.NATIVE_CODE,
            text="print('hi')",
            language="python",
        ),
    ]
    doc = _make_doc(blocks)
    md = "# Title\n\nBody text.\n\n```python\nprint('hi')\n```"
    result = check_completeness(
        document=doc,
        markdown_text=md,
        markdown_path=tmp_path / "document.md",
        mode="document",
    )
    assert result["summary"]["passed"] == 6
    assert result["summary"]["failed"] == 0
    assert result["failed_invariants"] == []
    assert result["invariants"]["visuals_missing"] == 0
    assert result["invariants"]["image_syntax_count"] == 0
    assert result["invariants"]["unclosed_fence_count"] == 0


def test_check_completeness_catches_image_syntax(tmp_path: Path):
    doc = _make_doc([])
    md = "Before\n![alt](http://x/y.png)\nafter"
    result = check_completeness(
        document=doc, markdown_text=md,
        markdown_path=tmp_path / "document.md", mode="document",
    )
    assert result["invariants"]["image_syntax_count"] == 1
    assert "image_syntax_count" in result["failed_invariants"]
    assert result["summary"]["failed"] >= 1


def test_check_completeness_catches_html_img(tmp_path: Path):
    doc = _make_doc([])
    md = "Before\n<img src='x'>\nafter"
    result = check_completeness(
        document=doc, markdown_text=md,
        markdown_path=tmp_path / "document.md", mode="document",
    )
    assert result["invariants"]["html_img_tag_count"] == 1
    assert "html_img_tag_count" in result["failed_invariants"]


def test_check_completeness_catches_base64_uri(tmp_path: Path):
    doc = _make_doc([])
    md = "text data:image/png;base64,iVBORw0KG more text"
    result = check_completeness(
        document=doc, markdown_text=md,
        markdown_path=tmp_path / "document.md", mode="document",
    )
    assert result["invariants"]["base64_image_uri_count"] == 1
    assert "base64_image_uri_count" in result["failed_invariants"]


def test_check_completeness_catches_unclosed_fence(tmp_path: Path):
    doc = _make_doc([])
    md = "# Title\n\n```python\nprint('hi')\n"  # no closing fence
    result = check_completeness(
        document=doc, markdown_text=md,
        markdown_path=tmp_path / "document.md", mode="document",
    )
    assert result["invariants"]["unclosed_fence_count"] == 1
    assert "unclosed_fence_count" in result["failed_invariants"]


def test_check_completeness_catches_html_comment_marker_in_document_mode(tmp_path: Path):
    doc = _make_doc([])
    md = "<!-- writeup2md: [REVIEW REQUIRED] visual=code block=b_000003 -->"
    result = check_completeness(
        document=doc, markdown_text=md,
        markdown_path=tmp_path / "document.md", mode="document",
    )
    assert result["invariants"]["html_comment_marker_count"] == 1
    assert "html_comment_marker_count" in result["failed_invariants"]


def test_check_completeness_allows_html_comment_marker_in_strict_mode(tmp_path: Path):
    """In strict mode, html_comment_marker_count is allowed (review UI)."""
    doc = _make_doc([])
    md = "<!-- writeup2md: [REVIEW REQUIRED] visual=code block=b_000003 -->"
    result = check_completeness(
        document=doc, markdown_text=md,
        markdown_path=tmp_path / "document.md", mode="strict",
    )
    assert result["invariants"]["html_comment_marker_count"] == 1
    # In strict mode this invariant is allowed, so it's not in failed_invariants.
    assert "html_comment_marker_count" not in result["failed_invariants"]
    assert result["summary"]["failed"] == 0


def test_count_unclosed_fences_zero_for_matched():
    md = "```python\nprint(1)\n```\n\ntext\n\n```bash\n$ ls\n```"
    assert _count_unclosed_fences(md) == 0


def test_count_unclosed_fences_one_for_unmatched():
    md = "```python\nprint(1)\n"  # no close
    assert _count_unclosed_fences(md) == 1


def test_count_unclosed_fences_handles_longer_fences():
    """Inner ``` is escaped with longer outer fence — no unclosed."""
    md = "````text\n```\ninner\n```\n````"
    assert _count_unclosed_fences(md) == 0


def test_suspicious_document_all_visuals_review_no_native_text():
    """Multiple visuals all routed to review with no native text."""
    from writeup2md.models import EnrichedVisual
    blocks = [
        Block(
            block_id="b_000000",
            order=0,
            type=BlockType.VISUAL,
            visual_type=VisualType.CODE,
            visual_state=VisualBlockState.REVIEW_REQUIRED,
            enrichment=EnrichedVisual(
                visual_type=VisualType.CODE,
                raw_text="",
                selected_text="",
                confidence=0.0,
                review_required=True,
            ),
        ),
        Block(
            block_id="b_000001",
            order=1,
            type=BlockType.VISUAL,
            visual_type=VisualType.CODE,
            visual_state=VisualBlockState.REVIEW_REQUIRED,
        ),
    ]
    doc = _make_doc(blocks)
    md = "some short markdown"
    suspicious, reason = is_suspicious_document(doc, md)
    assert suspicious
    assert "pipeline issue" in reason


def test_suspicious_document_single_visual_review_not_suspicious():
    """Single visual routed to review is legitimate, not suspicious."""
    from writeup2md.models import EnrichedVisual
    blocks = [
        Block(block_id="b_000000", order=0, type=BlockType.PARAGRAPH, text="Some text."),
        Block(
            block_id="b_000001",
            order=1,
            type=BlockType.VISUAL,
            visual_type=VisualType.CODE,
            visual_state=VisualBlockState.REVIEW_REQUIRED,
            enrichment=EnrichedVisual(
                visual_type=VisualType.CODE,
                raw_text="",
                selected_text="",
                confidence=0.0,
                review_required=True,
            ),
        ),
    ]
    doc = _make_doc(blocks)
    md = "Some text. More text. Even more text. Final text."
    suspicious, reason = is_suspicious_document(doc, md)
    assert not suspicious


def test_apply_completeness_to_status_rejects_on_failed_invariant():
    completeness = {
        "summary": {"total_invariants": 6, "passed": 5, "failed": 1},
        "failed_invariants": ["image_syntax_count"],
    }
    new_status, reasons = apply_completeness_to_status(
        status=DocumentStatus.ACCEPTED,
        completeness=completeness,
        is_suspicious=False,
    )
    assert new_status == DocumentStatus.REJECTED
    assert any("image_syntax_count" in r for r in reasons)


def test_apply_completeness_to_status_rejects_on_suspicious():
    completeness = {
        "summary": {"total_invariants": 6, "passed": 6, "failed": 0},
        "failed_invariants": [],
    }
    new_status, reasons = apply_completeness_to_status(
        status=DocumentStatus.ACCEPTED,
        completeness=completeness,
        is_suspicious=True,
    )
    assert new_status == DocumentStatus.REJECTED
    assert any("suspicious" in r for r in reasons)


def test_apply_completeness_to_status_keeps_status_when_clean():
    completeness = {
        "summary": {"total_invariants": 6, "passed": 6, "failed": 0},
        "failed_invariants": [],
    }
    new_status, reasons = apply_completeness_to_status(
        status=DocumentStatus.ACCEPTED,
        completeness=completeness,
        is_suspicious=False,
    )
    assert new_status == DocumentStatus.ACCEPTED
    assert reasons == []


def test_convert_emits_completeness_json(tmp_path: Path):
    """End-to-end: convert_html emits completeness.json + quality_report.json."""
    from writeup2md.adapters.html import convert_html
    from writeup2md.config import Profile, build_config

    html_path = Path(__file__).resolve().parents[1] / "fixtures" / "html" / "tutorial.html"
    cfg = build_config(Profile.MACBOOK)
    cfg.ocr.backend = "rapid"  # pin to avoid slow PaddleOCR-VL load

    result = convert_html(
        source=str(html_path), output_root=tmp_path, config=cfg, keep_evidence=True
    )
    d = result.document_dir
    assert (d / "completeness.json").is_file()
    assert (d / "quality_report.json").is_file()

    completeness = json.loads((d / "completeness.json").read_text(encoding="utf-8"))
    assert "invariants" in completeness
    assert "summary" in completeness
    assert "failed_invariants" in completeness
    # All 6 invariants must be present.
    expected_keys = {
        "visuals_missing", "image_syntax_count", "html_img_tag_count",
        "base64_image_uri_count", "unclosed_fence_count", "html_comment_marker_count",
    }
    assert set(completeness["invariants"].keys()) == expected_keys

    quality_report = json.loads((d / "quality_report.json").read_text(encoding="utf-8"))
    assert "status" in quality_report
    assert "completeness" in quality_report
