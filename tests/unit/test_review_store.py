"""Unit tests for the UI review store (human revisions)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from writeup2md.ui.review_store import (
    append_revision,
    load_review_state,
    load_revisions,
    save_reviewed_markdown,
    set_block_correction,
    set_block_verified,
    set_document_status,
)


def test_set_document_status_creates_review_dir(tmp_path: Path):
    doc_dir = tmp_path / "doc"
    doc_dir.mkdir()
    set_document_status(doc_dir, "accepted")
    assert (doc_dir / "review").is_dir()
    state = load_review_state(doc_dir)
    assert state["status"] == "accepted"


def test_set_document_status_records_revision(tmp_path: Path):
    doc_dir = tmp_path / "doc"
    doc_dir.mkdir()
    set_document_status(doc_dir, "review")
    set_document_status(doc_dir, "accepted")
    revs = load_revisions(doc_dir)
    assert len(revs) == 2
    assert revs[0]["new_value"] == "review"
    assert revs[1]["new_value"] == "accepted"


def test_set_block_correction_does_not_overwrite_raw(tmp_path: Path):
    """The correction is stored separately; raw OCR is never mutated."""
    doc_dir = tmp_path / "doc"
    doc_dir.mkdir()
    # Simulate a raw OCR artifact.
    raw_path = doc_dir / "document.json"
    raw_path.write_text(
        json.dumps({"blocks": [{"block_id": "b_0", "enrichment": {"raw_text": "ORIGINAL"}}]}),
        encoding="utf-8",
    )
    set_block_correction(doc_dir, "b_0", "HUMAN EDIT")
    # The raw document.json must be unchanged.
    raw_after = json.loads(raw_path.read_text(encoding="utf-8"))
    assert raw_after["blocks"][0]["enrichment"]["raw_text"] == "ORIGINAL"
    # The correction is in review_state.
    state = load_review_state(doc_dir)
    assert state["corrections"]["b_0"] == "HUMAN EDIT"
    # And in revisions.jsonl.
    revs = load_revisions(doc_dir)
    assert any(r["block_id"] == "b_0" and r["new_value"] == "HUMAN EDIT" for r in revs)


def test_set_block_verified(tmp_path: Path):
    doc_dir = tmp_path / "doc"
    doc_dir.mkdir()
    set_block_verified(doc_dir, "b_1", True)
    state = load_review_state(doc_dir)
    assert state["verified_blocks"]["b_1"] is True


def test_save_reviewed_markdown_separate_from_original(tmp_path: Path):
    doc_dir = tmp_path / "doc"
    doc_dir.mkdir()
    (doc_dir / "document.md").write_text("ORIGINAL", encoding="utf-8")
    save_reviewed_markdown(doc_dir, "EDITED")
    # Original unchanged.
    assert (doc_dir / "document.md").read_text(encoding="utf-8") == "ORIGINAL"
    # Reviewed version exists.
    assert (doc_dir / "review" / "document.reviewed.md").read_text(encoding="utf-8") == "EDITED"


def test_append_revision_grows_jsonl(tmp_path: Path):
    doc_dir = tmp_path / "doc"
    doc_dir.mkdir()
    append_revision(doc_dir, block_id="b_0", field="x", old_value=1, new_value=2)
    append_revision(doc_dir, block_id="b_0", field="y", old_value="a", new_value="b")
    revs = load_revisions(doc_dir)
    assert len(revs) == 2


def test_load_revisions_handles_missing_file(tmp_path: Path):
    doc_dir = tmp_path / "doc"
    doc_dir.mkdir()
    assert load_revisions(doc_dir) == []


def test_load_review_state_handles_missing_file(tmp_path: Path):
    doc_dir = tmp_path / "doc"
    doc_dir.mkdir()
    state = load_review_state(doc_dir)
    assert state["status"] is None
    assert state["verified_blocks"] == {}
