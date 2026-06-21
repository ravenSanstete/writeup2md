"""Unit tests for the IR models and deterministic IDs."""

from __future__ import annotations

import json

import pytest

from writeup2md.models import (
    SCHEMA_VERSION,
    Block,
    BlockType,
    Document,
    DocumentStatus,
    EnrichedVisual,
    EvidenceKind,
    EvidenceRef,
    Manifest,
    Provenance,
    SourceRecord,
    SourceType,
    VisualBlockState,
    VisualType,
    canonicalize_source,
    compute_document_id,
    content_sha256_text,
    next_block_id,
)


def test_schema_version_is_stable_string():
    assert SCHEMA_VERSION == "1.0"


def test_canonicalize_source_normalizes_urls():
    assert canonicalize_source("HTTPS://Example.COM/A/") == "https://example.com/A"
    assert canonicalize_source("http://example.com/a#frag") == "http://example.com/a"


def test_canonicalize_source_keeps_paths_as_is():
    assert canonicalize_source("./raw/x.pdf") == "./raw/x.pdf"


def test_compute_document_id_is_deterministic():
    args = dict(
        source="https://example.com/x",
        canonical_source="https://example.com/x",
        content_sha256="a" * 64,
        config_sha256="b" * 64,
    )
    a = compute_document_id(**args)
    b = compute_document_id(**args)
    assert a == b
    assert len(a) == 16
    # Different content hash yields different id.
    other = compute_document_id(**{**args, "content_sha256": "c" * 64})
    assert other != a


def test_compute_document_id_explicit_id_slugified():
    out = compute_document_id(
        source="x",
        canonical_source="x",
        content_sha256="a" * 64,
        config_sha256="b" * 64,
        explicit_id="My Tutorial! 2026",
    )
    assert out == "my-tutorial-2026"


def test_next_block_id_zero_padded():
    assert next_block_id(0) == "b_000000"
    assert next_block_id(123) == "b_000123"


def test_block_round_trip_json():
    b = Block(
        block_id="b_000001",
        order=1,
        type=BlockType.NATIVE_CODE,
        text="print('hi')",
        language="python",
    )
    s = b.model_dump_json()
    b2 = Block.model_validate_json(s)
    assert b2 == b


def test_manifest_round_trip():
    m = Manifest(
        document_id="abc123",
        source="https://example.com/x",
        source_type=SourceType.URL,
        canonical_source="https://example.com/x",
        captured_at="2026-06-19T00:00:00Z",
        content_sha256="a" * 64,
        config_sha256="b" * 64,
        status=DocumentStatus.REVIEW,
    )
    j = json.loads(m.model_dump_json())
    assert j["schema_version"] == "1.0"
    assert j["status"] == "review"


def test_enriched_visual_serialization():
    e = EnrichedVisual(
        visual_type=VisualType.TERMINAL,
        raw_text="$ ls\nfile.txt",
        selected_text="$ ls\nfile.txt",
        language="bash",
        confidence=0.93,
        transformations=["removed_editor_line_numbers"],
    )
    d = e.model_dump(mode="json")
    assert d["visual_type"] == "terminal"
    assert d["confidence"] == 0.93
    assert "removed_editor_line_numbers" in d["transformations"]


def test_evidence_ref_round_trip_pdf():
    ev = EvidenceRef(
        kind=EvidenceKind.PDF_REGION,
        page=7,
        bbox=[100.0, 220.0, 1400.0, 930.0],
        asset_path="evidence/regions/b_000123.png",
    )
    j = ev.model_dump(mode="json")
    assert j["kind"] == "pdf_region"
    assert j["page"] == 7


def test_provenance_round_trip():
    p = Provenance(
        block_id="b_000001",
        source_kind=SourceType.PDF,
        source_ref="raw/x.pdf",
        evidence=[
            EvidenceRef(
                kind=EvidenceKind.PDF_REGION,
                page=1,
                bbox=[0.0, 0.0, 10.0, 10.0],
                asset_path="evidence/regions/b_000001.png",
            )
        ],
        transformations=[],
        raw_text="print('hi')",
        final_text="```python\nprint('hi')\n```",
    )
    j = p.model_dump_json()
    p2 = Provenance.model_validate_json(j)
    assert p2.evidence[0].page == 1


def test_document_full_round_trip():
    src = SourceRecord(
        source_type=SourceType.PDF,
        source="x.pdf",
        canonical_source="x.pdf",
        captured_at="2026-06-19T00:00:00Z",
        content_sha256=content_sha256_text("hello"),
    )
    manifest = Manifest(
        document_id="doc1",
        source="x.pdf",
        source_type=SourceType.PDF,
        canonical_source="x.pdf",
        captured_at="2026-06-19T00:00:00Z",
        content_sha256=src.content_sha256,
        config_sha256="b" * 64,
        status=DocumentStatus.ACCEPTED,
    )
    blocks = [
        Block(block_id="b_000000", order=0, type=BlockType.HEADING, text="Title", heading_level=1),
        Block(
            block_id="b_000001",
            order=1,
            type=BlockType.NATIVE_CODE,
            text="print('hi')",
            language="python",
        ),
    ]
    doc = Document(manifest=manifest, source=src, blocks=blocks)
    j = doc.model_dump_json()
    doc2 = Document.model_validate_json(j)
    assert len(doc2.blocks) == 2
    assert doc2.blocks[0].type == BlockType.HEADING


def test_block_order_negative_rejected():
    with pytest.raises(Exception):
        Block(block_id="b", order=-1, type=BlockType.PARAGRAPH, text="x")
