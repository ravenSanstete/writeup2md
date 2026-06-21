"""Unit tests for the UI document index builder."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from writeup2md.ui.index import build_index, index_signature


def _make_doc(
    root: Path,
    doc_id: str,
    *,
    source: str = "x.pdf",
    source_type: str = "pdf",
    status: str = "accepted",
    quality: float = 0.9,
    blocks: int = 5,
    unresolved: int = 0,
    md_images: int = 0,
    title: str = "Test Doc",
) -> Path:
    d = root / doc_id
    d.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "1.0",
        "document_id": doc_id,
        "source": source,
        "source_type": source_type,
        "canonical_source": source,
        "captured_at": "2026-06-19T00:00:00Z",
        "content_sha256": "a" * 64,
        "config_sha256": "b" * 64,
        "status": status,
    }
    (d / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    diag = {
        "document_id": doc_id,
        "status": status,
        "unresolved_important_visuals": [f"b_{i:06d}" for i in range(unresolved)],
        "markdown_image_count": md_images,
        "quality": {"overall_quality_score": quality},
    }
    (d / "diagnostics.json").write_text(json.dumps(diag), encoding="utf-8")
    doc = {"blocks": [{"block_id": f"b_{i:06d}"} for i in range(blocks)]}
    (d / "document.json").write_text(json.dumps(doc), encoding="utf-8")
    (d / "document.md").write_text(f"# {title}\n\nbody text", encoding="utf-8")
    return d


def test_build_index_finds_documents(tmp_path: Path):
    root = tmp_path / "outputs"
    _make_doc(root, "doc1", status="accepted")
    _make_doc(root, "doc2", status="review", unresolved=2)
    entries = build_index(root)
    assert len(entries) == 2
    ids = {e.document_id for e in entries}
    assert ids == {"doc1", "doc2"}


def test_build_index_skips_status_subdirs(tmp_path: Path):
    root = tmp_path / "outputs"
    _make_doc(root, "doc1")
    (root / "accepted").mkdir()
    (root / "review").mkdir()
    entries = build_index(root)
    assert len(entries) == 1
    assert entries[0].document_id == "doc1"


def test_build_index_extracts_title_from_markdown(tmp_path: Path):
    root = tmp_path / "outputs"
    _make_doc(root, "doc1", title="My Tutorial Title")
    entries = build_index(root)
    assert entries[0].title == "My Tutorial Title"


def test_build_index_handles_empty_root(tmp_path: Path):
    entries = build_index(tmp_path / "empty")
    assert entries == []


def test_build_index_handles_missing_diagnostics(tmp_path: Path):
    root = tmp_path / "outputs"
    d = root / "doc1"
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps({"document_id": "doc1", "status": "accepted", "source": "x", "source_type": "pdf", "canonical_source": "x", "captured_at": "t", "content_sha256": "a", "config_sha256": "b"}), encoding="utf-8")
    (d / "document.md").write_text("# Hello\n", encoding="utf-8")
    entries = build_index(root)
    assert len(entries) == 1
    assert entries[0].quality_score == 0.0
    assert entries[0].unresolved_visuals == 0


def test_index_signature_changes_when_doc_added(tmp_path: Path):
    root = tmp_path / "outputs"
    sig1 = index_signature(root)
    _make_doc(root, "doc1")
    sig2 = index_signature(root)
    assert sig1 != sig2
