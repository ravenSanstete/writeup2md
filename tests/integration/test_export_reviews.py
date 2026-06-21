"""TASK_13 — integration test for the review export pipeline.

End-to-end:
1. Convert a small HTML fixture via the URL adapter (html_override path);
2. Apply human revisions via the review_store API;
3. Export reviews via inspect_cmd.export_reviews;
4. Verify the JSONL payload contains the expected record kinds and values.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from writeup2md.config import Profile, build_config
from writeup2md.inspect_cmd import export_reviews
from writeup2md.pipeline import convert_source
from writeup2md.ui.review_store import (
    set_block_correction,
    set_block_verified,
    set_document_status,
)


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def _html_with_visual_block() -> str:
    return """<!DOCTYPE html>
<html><head><title>Export Reviews Test</title></head>
<body>
<article>
<h1>Export Reviews Test</h1>
<p>Intro paragraph.</p>
<pre><code class="language-python">import os
print("hello")</code></pre>
<p>Outro paragraph.</p>
</article>
</body></html>"""


def test_export_reviews_end_to_end(tmp_path: Path):
    """Convert a doc, apply revisions, export to JSONL, verify contents."""
    cfg = build_config(Profile.MACBOOK)
    cfg.ocr.backend = "mock"

    html = _html_with_visual_block()
    html_path = tmp_path / "input.html"
    html_path.write_text(html, encoding="utf-8")

    out_root = tmp_path / "outputs"
    result = convert_source(
        source=str(html_path),
        output_root=out_root,
        config=cfg,
        force=True,
        keep_evidence=True,
    )
    assert result.document_dir.is_dir()
    doc_dir = result.document_dir

    # Read document.json to find a block id to correct.
    doc = json.loads((doc_dir / "document.json").read_text(encoding="utf-8"))
    blocks = doc.get("blocks", [])
    assert blocks, "expected at least one block"
    target_block_id = blocks[0]["block_id"]

    # Apply human revisions.
    set_document_status(doc_dir, "review")
    set_block_correction(doc_dir, target_block_id, "human-corrected text")
    set_block_verified(doc_dir, target_block_id, True)

    # Export via inspect_cmd.
    out_path = tmp_path / "exports" / "reviews.jsonl"
    n = export_reviews(doc_dir, out_path)
    assert n >= 1
    assert out_path.is_file()

    # Parse the JSONL.
    records = [
        json.loads(line)
        for line in out_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    # Expect: 1 review_state + at least 3 revisions (status, selected_text, verified).
    assert len(records) >= 4
    kinds = [r["kind"] for r in records]
    assert kinds[0] == "review_state"
    assert "revision" in kinds

    # The review_state record carries the document_id from the manifest.
    state_record = records[0]
    manifest = json.loads((doc_dir / "manifest.json").read_text(encoding="utf-8"))
    assert state_record["document_id"] == manifest["document_id"]
    assert state_record["status"] == "review"
    assert target_block_id in state_record["corrections"]
    assert state_record["corrections"][target_block_id] == "human-corrected text"

    # All revision records carry the document_id annotation.
    for r in records[1:]:
        assert r["document_id"] == manifest["document_id"]

    # The corrected text appears in at least one revision record.
    corrected_in_revisions = any(
        r.get("new_value") == "human-corrected text" for r in records[1:]
    )
    assert corrected_in_revisions


def test_export_reviews_with_no_revisions(tmp_path: Path):
    """A freshly-converted doc with no human edits still exports a review_state record."""
    cfg = build_config(Profile.MACBOOK)
    cfg.ocr.backend = "mock"
    html = "<html><body><article><h1>Empty</h1><p>text</p></article></body></html>"
    html_path = tmp_path / "input.html"
    html_path.write_text(html, encoding="utf-8")

    out_root = tmp_path / "outputs"
    result = convert_source(
        source=str(html_path),
        output_root=out_root,
        config=cfg,
        force=True,
        keep_evidence=True,
    )
    doc_dir = result.document_dir

    out_path = tmp_path / "reviews.jsonl"
    n = export_reviews(doc_dir, out_path)
    # 1 review_state record, 0 revisions.
    assert n == 1
    records = [json.loads(line) for line in out_path.read_text(encoding="utf-8").splitlines()]
    assert records[0]["kind"] == "review_state"
    assert records[0]["status"] is None
    assert records[0]["corrections"] == {}
