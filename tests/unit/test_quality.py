"""Tests for quality gates and status calculation."""

from __future__ import annotations

from writeup2md.config import Profile, build_config
from writeup2md.models import (
    Block,
    BlockType,
    Document,
    DocumentStatus,
    EnrichedVisual,
    EvidenceKind,
    EvidenceRef,
    Manifest,
    SourceRecord,
    SourceType,
    VisualBlockState,
    VisualType,
)
from writeup2md.quality import (
    build_diagnostics,
    calculate_status,
    compute_quality_report,
    is_unresolved_important,
)


def _doc(blocks: list[Block], status: DocumentStatus = DocumentStatus.ACCEPTED) -> Document:
    return Document(
        manifest=Manifest(
            document_id="d",
            source="x",
            source_type=SourceType.HTML,
            canonical_source="x",
            captured_at="2026-06-19T00:00:00Z",
            content_sha256="a" * 64,
            config_sha256="b" * 64,
            status=status,
        ),
        source=SourceRecord(
            source_type=SourceType.HTML,
            source="x",
            canonical_source="x",
            captured_at="2026-06-19T00:00:00Z",
            content_sha256="a" * 64,
        ),
        blocks=blocks,
    )


def test_accepted_when_only_native_blocks():
    blocks = [
        Block(block_id="b_0", order=0, type=BlockType.HEADING, text="T", heading_level=1),
        Block(block_id="b_1", order=1, type=BlockType.PARAGRAPH, text="hello"),
    ]
    doc = _doc(blocks)
    cfg = build_config(Profile.MACBOOK)
    assert calculate_status(doc, cfg) == DocumentStatus.ACCEPTED


def test_review_when_unresolved_important_visual():
    blocks = [
        Block(block_id="b_0", order=0, type=BlockType.HEADING, text="T", heading_level=1),
        Block(
            block_id="b_1",
            order=1,
            type=BlockType.VISUAL,
            visual_type=VisualType.CODE,
            visual_state=VisualBlockState.REVIEW_REQUIRED,
        ),
    ]
    doc = _doc(blocks)
    cfg = build_config(Profile.MACBOOK)
    assert calculate_status(doc, cfg) == DocumentStatus.REVIEW


def test_accepted_when_important_visual_resolved():
    blocks = [
        Block(
            block_id="b_0",
            order=0,
            type=BlockType.VISUAL,
            visual_type=VisualType.CODE,
            visual_state=VisualBlockState.RESOLVED_OCR,
            enrichment=EnrichedVisual(
                visual_type=VisualType.CODE,
                raw_text="print('hi')",
                selected_text="print('hi')",
                confidence=0.9,
            ),
            evidence=[
                EvidenceRef(
                    kind=EvidenceKind.PDF_REGION,
                    page=1,
                    bbox=[0.0, 0.0, 1.0, 1.0],
                    asset_path="evidence/regions/b_0.png",
                )
            ],
        )
    ]
    doc = _doc(blocks)
    cfg = build_config(Profile.MACBOOK)
    assert calculate_status(doc, cfg) == DocumentStatus.ACCEPTED


def test_failed_when_markdown_empty():
    doc = _doc([])
    cfg = build_config(Profile.MACBOOK)
    assert calculate_status(doc, cfg) == DocumentStatus.FAILED


def test_rejected_when_markdown_contains_image_syntax():
    # We craft a block whose text contains markdown image syntax (adversarial).
    blocks = [
        Block(
            block_id="b_0",
            order=0,
            type=BlockType.PARAGRAPH,
            text="![alt](http://x/y.png)",
        )
    ]
    doc = _doc(blocks)
    cfg = build_config(Profile.MACBOOK)
    assert calculate_status(doc, cfg) == DocumentStatus.REJECTED


def test_decorative_ignored_visual_is_not_unresolved():
    b = Block(
        block_id="b_0",
        order=0,
        type=BlockType.VISUAL,
        visual_type=VisualType.DECORATIVE,
        visual_state=VisualBlockState.IGNORED_DECORATIVE,
    )
    assert is_unresolved_important(b) is False


def test_compute_quality_report_counts():
    blocks = [
        Block(block_id="b_0", order=0, type=BlockType.HEADING, text="T", heading_level=1),
        Block(block_id="b_1", order=1, type=BlockType.PARAGRAPH, text="p"),
        Block(
            block_id="b_2",
            order=2,
            type=BlockType.VISUAL,
            visual_type=VisualType.CODE,
            visual_state=VisualBlockState.RESOLVED_OCR,
            enrichment=EnrichedVisual(
                visual_type=VisualType.CODE,
                raw_text="x",
                selected_text="x",
                confidence=0.9,
            ),
        ),
        Block(
            block_id="b_3",
            order=3,
            type=BlockType.VISUAL,
            visual_type=VisualType.CODE,
            visual_state=VisualBlockState.REVIEW_REQUIRED,
        ),
    ]
    doc = _doc(blocks)
    r = compute_quality_report(doc)
    assert r.ocr_enriched_block_count == 1
    assert r.unresolved_visual_count == 1
    assert r.markdown_image_count == 0


def test_build_diagnostics_round_trip():
    blocks = [
        Block(block_id="b_0", order=0, type=BlockType.HEADING, text="T", heading_level=1),
    ]
    doc = _doc(blocks)
    diag = build_diagnostics(doc, status_reasons=["ok"], warnings=["w1"])
    assert diag.document_id == "d"
    assert "w1" in diag.processing_warnings
    assert "heading" in diag.block_counts
