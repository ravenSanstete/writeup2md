"""TASK_13 — Streamlit review workflow unit tests.

Covers:
- search index build + tokenization + ranking + phrase search;
- review_store.export_reviews / export_reviews_jsonl payload structure;
- inspect_cmd.export_reviews integration with manifest.json;
- CLI `inspect --export-reviews PATH` surface and behavior.

Does NOT launch Streamlit (we test the underlying modules directly).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from writeup2md.cli import app
from writeup2md.inspect_cmd import export_reviews
from writeup2md.ui.review_store import (
    export_reviews as store_export_reviews,
    export_reviews_jsonl,
    set_block_correction,
    set_block_verified,
    set_document_status,
)
from writeup2md.ui.search import (
    SearchDoc,
    _tokenize,
    build_search_index,
    search_documents,
)


runner = CliRunner()


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _make_doc(
    root: Path,
    doc_id: str,
    *,
    source: str = "x.pdf",
    source_type: str = "pdf",
    status: str = "accepted",
    title: str = "Test Doc",
    body_md: str = "body text",
    blocks: list[dict] | None = None,
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
    (d / "diagnostics.json").write_text(
        json.dumps({"document_id": doc_id, "status": status, "quality": {"overall_quality_score": 0.9}}),
        encoding="utf-8",
    )
    doc = {"blocks": blocks or [{"block_id": "b_000000"}]}
    (d / "document.json").write_text(json.dumps(doc), encoding="utf-8")
    (d / "document.md").write_text(f"# {title}\n\n{body_md}", encoding="utf-8")
    return d


# ---------------------------------------------------------------------------
# search.py — tokenization
# ---------------------------------------------------------------------------


def test_tokenize_alphanumeric():
    toks = _tokenize("Hello, World! 123")
    assert toks == ["hello", "world", "123"]


def test_tokenize_empty():
    assert _tokenize("") == []


def test_tokenize_cjk_keeps_chunk():
    """CJK text isn't split by the alphanumeric regex; we keep the whole chunk."""
    toks = _tokenize("hello 漏洞世界")
    assert "hello" in toks
    # The CJK chunk is kept whole.
    assert "漏洞世界" in toks


def test_tokenize_preserves_dashes():
    toks = _tokenize("content-type header")
    assert "content-type" in toks
    assert "header" in toks


# ---------------------------------------------------------------------------
# search.py — build_search_index
# ---------------------------------------------------------------------------


def test_build_search_index_finds_documents(tmp_path: Path):
    _make_doc(tmp_path, "doc1", title="First", body_md="import requests")
    _make_doc(tmp_path, "doc2", title="Second", body_md="another doc")
    idx = build_search_index(tmp_path)
    assert len(idx) == 2
    ids = {d.document_id for d in idx}
    assert ids == {"doc1", "doc2"}


def test_build_search_index_extracts_block_text(tmp_path: Path):
    _make_doc(
        tmp_path,
        "doc1",
        title="T",
        body_md="placeholder",
        blocks=[
            {"block_id": "b_000000", "type": "paragraph", "text": "hidden keyword"},
            {
                "block_id": "b_000001",
                "type": "visual",
                "enrichment": {"raw_text": "raw ocr", "selected_text": "selected"},
            },
        ],
    )
    idx = build_search_index(tmp_path)
    assert len(idx) == 1
    tokens = set(idx[0].tokens)
    assert "hidden" in tokens
    assert "keyword" in tokens
    assert "raw" in tokens
    assert "selected" in tokens


def test_build_search_index_skips_status_subdirs(tmp_path: Path):
    _make_doc(tmp_path, "doc1")
    (tmp_path / "accepted").mkdir()
    idx = build_search_index(tmp_path)
    assert len(idx) == 1


def test_build_search_index_empty_root(tmp_path: Path):
    assert build_search_index(tmp_path / "nope") == []


# ---------------------------------------------------------------------------
# search.py — search_documents
# ---------------------------------------------------------------------------


def test_search_returns_matching_documents(tmp_path: Path):
    _make_doc(tmp_path, "doc1", body_md="python requests library")
    _make_doc(tmp_path, "doc2", body_md="golang http client")
    idx = build_search_index(tmp_path)
    results = search_documents(idx, "python")
    assert len(results) == 1
    assert results[0].document_id == "doc1"


def test_search_ranks_by_term_frequency(tmp_path: Path):
    """Document with more occurrences of the query token ranks first."""
    _make_doc(tmp_path, "doc1", body_md="python python python")
    _make_doc(tmp_path, "doc2", body_md="python once")
    idx = build_search_index(tmp_path)
    results = search_documents(idx, "python")
    assert results[0].document_id == "doc1"
    assert results[1].document_id == "doc2"
    assert results[0].score > results[1].score


def test_search_empty_query_returns_empty(tmp_path: Path):
    _make_doc(tmp_path, "doc1", body_md="content")
    idx = build_search_index(tmp_path)
    assert search_documents(idx, "") == []
    assert search_documents(idx, "   ") == []


def test_search_no_matches_returns_empty(tmp_path: Path):
    _make_doc(tmp_path, "doc1", body_md="python")
    idx = build_search_index(tmp_path)
    assert search_documents(idx, "javascript") == []


def test_search_phrase_query_matches_substring(tmp_path: Path):
    """Quoted queries match literal substrings (case-insensitive)."""
    _make_doc(tmp_path, "doc1", body_md="import requests from bs4")
    _make_doc(tmp_path, "doc2", body_md="import something else")
    idx = build_search_index(tmp_path)
    # Quoted phrase search.
    results = search_documents(idx, '"import requests"')
    assert len(results) == 1
    assert results[0].document_id == "doc1"


def test_search_phrase_query_no_match(tmp_path: Path):
    _make_doc(tmp_path, "doc1", body_md="import something")
    idx = build_search_index(tmp_path)
    results = search_documents(idx, '"import requests"')
    assert results == []


def test_search_limit_caps_results(tmp_path: Path):
    for i in range(5):
        _make_doc(tmp_path, f"doc{i}", body_md="shared keyword")
    idx = build_search_index(tmp_path)
    results = search_documents(idx, "shared", limit=2)
    assert len(results) == 2


def test_search_tiebreaker_is_document_id(tmp_path: Path):
    """When scores tie, results sort alphabetically by document_id."""
    _make_doc(tmp_path, "zeta", body_md="python")
    _make_doc(tmp_path, "alpha", body_md="python")
    idx = build_search_index(tmp_path)
    results = search_documents(idx, "python")
    assert [r.document_id for r in results] == ["alpha", "zeta"]


# ---------------------------------------------------------------------------
# review_store.export_reviews
# ---------------------------------------------------------------------------


def test_export_reviews_returns_state_and_revisions(tmp_path: Path):
    d = _make_doc(tmp_path, "doc1", title="T", body_md="content")
    set_document_status(d, "accepted")
    set_block_correction(d, "b_000000", "edited text")
    set_block_verified(d, "b_000000", True)
    records = store_export_reviews(d)
    # 1 review_state record + 3 revision records (status, selected_text, verified)
    assert len(records) == 4
    kinds = [r["kind"] for r in records]
    assert kinds[0] == "review_state"
    assert "revision" in kinds
    # review_state record carries document_id.
    assert records[0]["document_id"] == "doc1"
    assert records[0]["status"] == "accepted"
    assert records[0]["corrections"] == {"b_000000": "edited text"}
    # Revisions are annotated with document_id.
    for r in records[1:]:
        assert r["document_id"] == "doc1"


def test_export_reviews_handles_no_revisions(tmp_path: Path):
    d = _make_doc(tmp_path, "doc1")
    records = store_export_reviews(d)
    assert len(records) == 1
    assert records[0]["kind"] == "review_state"
    assert records[0]["status"] is None


def test_export_reviews_jsonl_writes_file(tmp_path: Path):
    d = _make_doc(tmp_path, "doc1")
    set_document_status(d, "review")
    out = tmp_path / "exports" / "reviews.jsonl"
    n = export_reviews_jsonl(d, out)
    assert n >= 1
    assert out.is_file()
    # Each line is valid JSON.
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == n
    for line in lines:
        json.loads(line)


def test_export_reviews_jsonl_creates_parent_dir(tmp_path: Path):
    d = _make_doc(tmp_path, "doc1")
    out = tmp_path / "deeply" / "nested" / "path" / "reviews.jsonl"
    export_reviews_jsonl(d, out)
    assert out.is_file()


# ---------------------------------------------------------------------------
# inspect_cmd.export_reviews
# ---------------------------------------------------------------------------


def test_inspect_export_reviews_writes_jsonl(tmp_path: Path):
    d = _make_doc(tmp_path, "doc1")
    set_block_correction(d, "b_000000", "fixed")
    out = tmp_path / "out.jsonl"
    n = export_reviews(d, out)
    assert n >= 1
    assert out.is_file()
    # Spot-check that the correction appears in the exported file.
    text = out.read_text(encoding="utf-8")
    assert "fixed" in text


def test_inspect_export_reviews_missing_manifest_raises(tmp_path: Path):
    d = tmp_path / "no-doc"
    d.mkdir()
    with pytest.raises(FileNotFoundError):
        export_reviews(d, tmp_path / "out.jsonl")


# ---------------------------------------------------------------------------
# CLI: `inspect --export-reviews PATH`
# ---------------------------------------------------------------------------


def test_cli_inspect_export_reviews_option_in_help():
    result = runner.invoke(app, ["inspect", "--help"])
    assert result.exit_code == 0
    assert "--export-reviews" in result.output


def test_cli_inspect_export_reviews_runs(tmp_path: Path):
    d = _make_doc(tmp_path, "doc1")
    set_block_correction(d, "b_000000", "CLI fix")
    out = tmp_path / "reviews.jsonl"
    result = runner.invoke(app, ["inspect", str(d), "--export-reviews", str(out)])
    assert result.exit_code == 0
    assert out.is_file()
    assert "CLI fix" in out.read_text(encoding="utf-8")


def test_cli_inspect_export_reviews_missing_manifest_input_error(tmp_path: Path):
    d = tmp_path / "no-doc"
    d.mkdir()
    out = tmp_path / "reviews.jsonl"
    result = runner.invoke(app, ["inspect", str(d), "--export-reviews", str(out)])
    # inspect_document raises FileNotFoundError → exit code 4.
    assert result.exit_code == 4
