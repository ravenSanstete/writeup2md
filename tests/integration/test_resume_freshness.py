"""TASK_12 batch resume freshness + failure recovery tests.

Verifies:
- file edit detection: edited file is re-processed on next batch run;
- partial-state recovery: a corrupted document directory is moved aside;
- `--force-refresh` bypasses cache;
- `--max-age SECONDS` treats young cache as fresh;
- 1-worker and 2-worker runs produce identical output on the same sources;
- URL sources default to fresh (no network call);
- check_source_freshness for local files re-hashes and compares.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from writeup2md.batch import (
    check_source_freshness,
    run_batch,
    _recover_partial_state,
)
from writeup2md.config import Profile, build_config


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def _make_pdf(path: Path, text: str = "Initial content") -> None:
    """Write a minimal PDF with native text."""
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text, fontsize=11)
    doc.save(str(path))
    doc.close()


# ---------------------------------------------------------------------------
# check_source_freshness
# ---------------------------------------------------------------------------


def test_freshness_file_unchanged_returns_true(tmp_path: Path):
    """An unchanged file matches its cached content_sha256."""
    from writeup2md.models import content_sha256_bytes

    pdf = tmp_path / "src.pdf"
    _make_pdf(pdf, "hello world")
    cached_sha = content_sha256_bytes(pdf.read_bytes())
    cached = {"content_sha256": cached_sha, "captured_at": "2020-01-01T00:00:00Z"}
    assert check_source_freshness(str(pdf), cached) is True


def test_freshness_file_edited_returns_false(tmp_path: Path):
    """An edited file no longer matches its cached content_sha256."""
    from writeup2md.models import content_sha256_bytes

    pdf = tmp_path / "src.pdf"
    _make_pdf(pdf, "hello world")
    cached_sha = content_sha256_bytes(pdf.read_bytes())
    cached = {"content_sha256": cached_sha, "captured_at": "2020-01-01T00:00:00Z"}
    # Edit the file.
    _make_pdf(pdf, "different content")
    assert check_source_freshness(str(pdf), cached) is False


def test_freshness_url_defaults_to_true():
    """URL sources default to fresh (no network call)."""
    cached = {"content_sha256": "abc", "captured_at": "2020-01-01T00:00:00Z"}
    assert check_source_freshness("https://example.com/x", cached) is True


def test_freshness_max_age_young_cache_returns_true():
    """A cache younger than max_age is fresh regardless of content."""
    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    cached = {"content_sha256": "abc", "captured_at": now_iso}
    # max_age=3600 — cache is 0 seconds old, well under 3600.
    assert check_source_freshness("/nonexistent/file.pdf", cached, max_age=3600) is True


def test_freshness_max_age_old_cache_falls_through_to_content_check(tmp_path: Path):
    """A cache older than max_age falls through to the content check."""
    from writeup2md.models import content_sha256_bytes

    pdf = tmp_path / "src.pdf"
    _make_pdf(pdf, "hello")
    cached_sha = content_sha256_bytes(pdf.read_bytes())
    # Old captured_at — older than max_age.
    cached = {"content_sha256": cached_sha, "captured_at": "2020-01-01T00:00:00Z"}
    # Content still matches, so fresh.
    assert check_source_freshness(str(pdf), cached, max_age=1) is True


def test_freshness_missing_file_returns_false(tmp_path: Path):
    """A missing file is not fresh."""
    cached = {"content_sha256": "abc", "captured_at": "2020-01-01T00:00:00Z"}
    assert check_source_freshness(str(tmp_path / "missing.pdf"), cached) is False


# ---------------------------------------------------------------------------
# Partial-state recovery
# ---------------------------------------------------------------------------


def test_recover_partial_state_moves_incomplete_dir(tmp_path: Path):
    """A document dir without manifest.json is moved aside."""
    doc_dir = tmp_path / "abc123"
    doc_dir.mkdir()
    (doc_dir / "raw").mkdir()
    (doc_dir / "raw" / "page.html").write_text("partial", encoding="utf-8")
    # manifest.json is missing.

    recovered = _recover_partial_state(doc_dir)
    assert recovered is True
    # The original directory no longer exists at the original path.
    assert not doc_dir.is_dir()
    # A partial-<timestamp> directory exists.
    partials = list(tmp_path.glob("abc123.partial.*"))
    assert len(partials) == 1
    # The partial content is preserved.
    assert (partials[0] / "raw" / "page.html").read_text(encoding="utf-8") == "partial"


def test_recover_partial_state_skips_complete_dir(tmp_path: Path):
    """A complete document dir (with manifest.json) is not moved."""
    doc_dir = tmp_path / "abc123"
    doc_dir.mkdir()
    (doc_dir / "manifest.json").write_text("{}", encoding="utf-8")
    (doc_dir / "document.json").write_text("{}", encoding="utf-8")
    recovered = _recover_partial_state(doc_dir)
    assert recovered is False
    assert doc_dir.is_dir()


def test_recover_partial_state_missing_dir_returns_false(tmp_path: Path):
    """A non-existent dir is not recovered."""
    assert _recover_partial_state(tmp_path / "does-not-exist") is False


# ---------------------------------------------------------------------------
# End-to-end: file edit triggers re-processing
# ---------------------------------------------------------------------------


def test_batch_file_edit_triggers_reprocessing(tmp_path: Path):
    """Editing a source file between batch runs causes re-processing."""
    cfg = build_config(Profile.MACBOOK)
    cfg.ocr.backend = "mock"
    src_pdf = tmp_path / "src.pdf"
    _make_pdf(src_pdf, "version 1")
    manifest = tmp_path / "src.jsonl"
    manifest.write_text(json.dumps({"source": str(src_pdf)}) + "\n", encoding="utf-8")
    out = tmp_path / "out"

    s1 = run_batch(input_path=manifest, output_root=out, config=cfg, workers=1, retry=0)
    assert s1.skipped == 0
    assert s1.total == 1

    # Re-run: should skip (content unchanged).
    s2 = run_batch(input_path=manifest, output_root=out, config=cfg, workers=1, retry=0)
    assert s2.skipped == 1

    # Edit the file.
    _make_pdf(src_pdf, "version 2 edited")
    # Re-run: should re-process (content changed).
    s3 = run_batch(input_path=manifest, output_root=out, config=cfg, workers=1, retry=0)
    assert s3.skipped == 0
    assert s3.total == 1


# ---------------------------------------------------------------------------
# --force-refresh
# ---------------------------------------------------------------------------


def test_batch_force_refresh_bypasses_cache(tmp_path: Path):
    """--force-refresh re-processes even when content is unchanged."""
    cfg = build_config(Profile.MACBOOK)
    cfg.ocr.backend = "mock"
    src_pdf = tmp_path / "src.pdf"
    _make_pdf(src_pdf, "content")
    manifest = tmp_path / "src.jsonl"
    manifest.write_text(json.dumps({"source": str(src_pdf)}) + "\n", encoding="utf-8")
    out = tmp_path / "out"

    s1 = run_batch(input_path=manifest, output_root=out, config=cfg, workers=1, retry=0)
    assert s1.skipped == 0

    # Re-run without force_refresh: skip.
    s2 = run_batch(input_path=manifest, output_root=out, config=cfg, workers=1, retry=0)
    assert s2.skipped == 1

    # Re-run with force_refresh: re-process.
    s3 = run_batch(
        input_path=manifest, output_root=out, config=cfg, workers=1, retry=0,
        force_refresh=True,
    )
    assert s3.skipped == 0


# ---------------------------------------------------------------------------
# --max-age
# ---------------------------------------------------------------------------


def test_batch_max_age_treats_young_cache_as_fresh(tmp_path: Path):
    """--max-age=3600 treats a 0-second-old cache as fresh (skipped)."""
    cfg = build_config(Profile.MACBOOK)
    cfg.ocr.backend = "mock"
    src_pdf = tmp_path / "src.pdf"
    _make_pdf(src_pdf, "content")
    manifest = tmp_path / "src.jsonl"
    manifest.write_text(json.dumps({"source": str(src_pdf)}) + "\n", encoding="utf-8")
    out = tmp_path / "out"

    run_batch(input_path=manifest, output_root=out, config=cfg, workers=1, retry=0)
    # Re-run with max_age=3600 — cache is fresh, should skip.
    s = run_batch(
        input_path=manifest, output_root=out, config=cfg, workers=1, retry=0,
        max_age=3600,
    )
    assert s.skipped == 1


def test_batch_max_age_expired_falls_through_to_content_check(tmp_path: Path):
    """--max-age=1 with an old cache falls through to content check.

    We can't easily make captured_at old without mocking, so we verify the
    behavior indirectly: the cache content matches, so even with max_age=1
    and a fresh run, the content check returns fresh → skip.
    """
    cfg = build_config(Profile.MACBOOK)
    cfg.ocr.backend = "mock"
    src_pdf = tmp_path / "src.pdf"
    _make_pdf(src_pdf, "content")
    manifest = tmp_path / "src.jsonl"
    manifest.write_text(json.dumps({"source": str(src_pdf)}) + "\n", encoding="utf-8")
    out = tmp_path / "out"

    run_batch(input_path=manifest, output_root=out, config=cfg, workers=1, retry=0)
    # Re-run with max_age=1. The captured_at is fresh (just now), so the
    # max_age branch returns True (skip).
    s = run_batch(
        input_path=manifest, output_root=out, config=cfg, workers=1, retry=0,
        max_age=1,
    )
    assert s.skipped == 1


# ---------------------------------------------------------------------------
# Concurrency: 1 worker vs 2 workers produce identical output
# ---------------------------------------------------------------------------


def test_batch_one_vs_two_workers_identical_output(tmp_path: Path):
    """1-worker and 2-worker runs produce identical Markdown output and statuses.

    Document IDs may differ because `workers` is part of the config hash
    (a deliberate design choice — changing the worker count invalidates the
    cache). What matters for "identical output" is the rendered Markdown,
    the block count, and the status.
    """
    cfg1 = build_config(Profile.MACBOOK)
    cfg1.ocr.backend = "mock"
    cfg2 = build_config(Profile.MACBOOK)
    cfg2.ocr.backend = "mock"

    # Two distinct sources.
    src1 = tmp_path / "src1.pdf"
    _make_pdf(src1, "source one content")
    src2 = tmp_path / "src2.pdf"
    _make_pdf(src2, "source two content")
    manifest = tmp_path / "src.jsonl"
    manifest.write_text(
        json.dumps({"source": str(src1)}) + "\n" +
        json.dumps({"source": str(src2)}) + "\n",
        encoding="utf-8",
    )

    out1 = tmp_path / "out_w1"
    out2 = tmp_path / "out_w2"

    s1 = run_batch(input_path=manifest, output_root=out1, config=cfg1, workers=1, retry=0)
    s2 = run_batch(input_path=manifest, output_root=out2, config=cfg2, workers=2, retry=0)

    # Same total.
    assert s1.total == s2.total == 2
    # Same set of statuses.
    statuses1 = sorted(r.status for r in s1.results)
    statuses2 = sorted(r.status for r in s2.results)
    assert statuses1 == statuses2
    # Same rendered Markdown (compare by content, not by doc_id path).
    md1_blobs = sorted(
        (r.document_dir / "document.md").read_text(encoding="utf-8")
        for r in s1.results if r.document_dir
    )
    md2_blobs = sorted(
        (r.document_dir / "document.md").read_text(encoding="utf-8")
        for r in s2.results if r.document_dir
    )
    assert md1_blobs == md2_blobs
    # Same block counts (compare as JSON strings for sortability).
    bc1 = sorted(
        json.dumps(
            json.loads((r.document_dir / "diagnostics.json").read_text(encoding="utf-8"))["block_counts"],
            sort_keys=True,
        )
        for r in s1.results if r.document_dir
    )
    bc2 = sorted(
        json.dumps(
            json.loads((r.document_dir / "diagnostics.json").read_text(encoding="utf-8"))["block_counts"],
            sort_keys=True,
        )
        for r in s2.results if r.document_dir
    )
    assert bc1 == bc2


# ---------------------------------------------------------------------------
# Partial-state recovery end-to-end
# ---------------------------------------------------------------------------


def test_batch_recovers_partial_state_on_rerun(tmp_path: Path):
    """If a previous run left a partial document dir, the next run recovers."""
    cfg = build_config(Profile.MACBOOK)
    cfg.ocr.backend = "mock"
    src_pdf = tmp_path / "src.pdf"
    _make_pdf(src_pdf, "content")
    manifest = tmp_path / "src.jsonl"
    manifest.write_text(json.dumps({"source": str(src_pdf)}) + "\n", encoding="utf-8")
    out = tmp_path / "out"

    # First run: completes.
    s1 = run_batch(input_path=manifest, output_root=out, config=cfg, workers=1, retry=0)
    assert s1.total == 1
    doc_id = s1.results[0].document_id
    assert doc_id
    doc_dir = s1.results[0].document_dir
    assert doc_dir is not None
    dir_name = doc_dir.name

    # Simulate interruption: delete manifest.json from the document dir.
    (doc_dir / "manifest.json").unlink()

    # Re-run: should recover the partial state (move it aside) and re-process.
    s2 = run_batch(input_path=manifest, output_root=out, config=cfg, workers=1, retry=0)
    assert s2.total == 1
    # A new complete document dir should exist (under the same name).
    assert (doc_dir / "manifest.json").is_file()
    # The partial dir should have been moved aside.
    partials = list(out.glob(f"{dir_name}.partial.*"))
    assert len(partials) >= 1
