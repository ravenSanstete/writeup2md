"""Integration tests for batch processing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from writeup2md.batch import (
    BatchSourceItem,
    parse_batch_input,
    run_batch,
    simulate_interruption_after,
)
from writeup2md.config import Profile, build_config


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def test_parse_jsonl_manifest():
    items = parse_batch_input(FIXTURE_DIR / "batch" / "sources.jsonl")
    assert len(items) == 2
    assert items[0].source.endswith("writeup.pdf")
    assert items[1].source.endswith("tutorial.html")
    assert "pdf" in items[0].tags
    assert "html" in items[1].tags


def test_parse_url_list(tmp_path: Path):
    p = tmp_path / "urls.txt"
    p.write_text(
        "# comment\nhttps://example.com/a\nhttps://example.com/b\n\n",
        encoding="utf-8",
    )
    items = parse_batch_input(p)
    assert len(items) == 2
    assert items[0].source == "https://example.com/a"


def test_parse_directory(tmp_path: Path):
    d = tmp_path / "raw"
    d.mkdir()
    (d / "a.pdf").write_bytes(b"%PDF-1.4 fake")
    (d / "b.html").write_text("<html></html>", encoding="utf-8")
    (d / "c.txt").write_text("ignored", encoding="utf-8")
    items = parse_batch_input(d)
    sources = sorted(it.source for it in items)
    assert any(s.endswith("a.pdf") for s in sources)
    assert any(s.endswith("b.html") for s in sources)
    assert not any(s.endswith("c.txt") for s in sources)


def test_parse_directory_recursive(tmp_path: Path):
    d = tmp_path / "raw"
    sub = d / "sub"
    sub.mkdir(parents=True)
    (d / "a.pdf").write_bytes(b"%PDF-1.4 fake")
    (sub / "b.pdf").write_bytes(b"%PDF-1.4 fake")
    flat = parse_batch_input(d, recursive=False)
    deep = parse_batch_input(d, recursive=True)
    assert len(flat) == 1
    assert len(deep) == 2


def test_parse_directory_include_exclude(tmp_path: Path):
    d = tmp_path / "raw"
    d.mkdir()
    (d / "include.pdf").write_bytes(b"%PDF-1.4")
    (d / "exclude.pdf").write_bytes(b"%PDF-1.4")
    items = parse_batch_input(d, include="include*.pdf", exclude="exclude*.pdf")
    assert len(items) == 1
    assert items[0].source.endswith("include.pdf")


def test_batch_runs_two_sources_and_writes_summary(tmp_path: Path):
    cfg = build_config(Profile.MACBOOK)
    cfg.ocr.backend = "mock"  # avoid hitting real PaddleOCR-VL
    out = tmp_path / "out"
    summary = run_batch(
        input_path=FIXTURE_DIR / "batch" / "sources.jsonl",
        output_root=out,
        config=cfg,
        workers=1,
        retry=0,
    )
    assert summary.total == 2
    # PDF is accepted (no unresolved visuals); HTML is review (one image).
    statuses = sorted(r.status for r in summary.results)
    assert "accepted" in statuses
    assert "review" in statuses

    # Summary file written.
    assert (out / "batch_summary.json").is_file()
    summary_json = json.loads((out / "batch_summary.json").read_text(encoding="utf-8"))
    assert summary_json["total"] == 2

    # Batch manifest written.
    assert (out / "batch_manifest.jsonl").is_file()
    lines = (out / "batch_manifest.jsonl").read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2


def test_batch_resume_skips_completed_sources(tmp_path: Path):
    cfg = build_config(Profile.MACBOOK)
    cfg.ocr.backend = "mock"
    out = tmp_path / "out"
    summary1 = run_batch(
        input_path=FIXTURE_DIR / "batch" / "sources.jsonl",
        output_root=out,
        config=cfg,
        workers=1,
        retry=0,
    )
    assert summary1.skipped == 0

    # Re-run with resume: both should be skipped.
    summary2 = run_batch(
        input_path=FIXTURE_DIR / "batch" / "sources.jsonl",
        output_root=out,
        config=cfg,
        workers=1,
        retry=0,
    )
    assert summary2.skipped == 2
    assert summary2.accepted + summary2.review == 0


def test_batch_resume_after_simulated_interruption(tmp_path: Path):
    cfg = build_config(Profile.MACBOOK)
    cfg.ocr.backend = "mock"
    out = tmp_path / "out"
    # First run completes both.
    run_batch(
        input_path=FIXTURE_DIR / "batch" / "sources.jsonl",
        output_root=out,
        config=cfg,
        workers=1,
        retry=0,
    )
    # Simulate interruption: wipe state to 0 entries.
    simulate_interruption_after(out, 0)

    # Re-run: should process both again (no duplicates, no error).
    summary = run_batch(
        input_path=FIXTURE_DIR / "batch" / "sources.jsonl",
        output_root=out,
        config=cfg,
        workers=1,
        retry=0,
    )
    assert summary.total == 2
    # Both should be processed (skipped == 0 because state was truncated).
    assert summary.skipped == 0


def test_batch_partial_resume_processes_remaining(tmp_path: Path):
    cfg = build_config(Profile.MACBOOK)
    cfg.ocr.backend = "mock"
    out = tmp_path / "out"
    # First run: process both.
    run_batch(
        input_path=FIXTURE_DIR / "batch" / "sources.jsonl",
        output_root=out,
        config=cfg,
        workers=1,
        retry=0,
    )
    # Simulate interruption after the first source.
    simulate_interruption_after(out, 1)

    # Re-run: first should be skipped, second should be reprocessed.
    summary = run_batch(
        input_path=FIXTURE_DIR / "batch" / "sources.jsonl",
        output_root=out,
        config=cfg,
        workers=1,
        retry=0,
    )
    assert summary.total == 2
    assert summary.skipped == 1


def test_batch_failure_recorded(tmp_path: Path):
    cfg = build_config(Profile.MACBOOK)
    cfg.ocr.backend = "mock"
    out = tmp_path / "out"
    manifest = tmp_path / "bad.jsonl"
    manifest.write_text(
        '{"source": "/nonexistent/file.pdf"}\n', encoding="utf-8"
    )
    summary = run_batch(
        input_path=manifest,
        output_root=out,
        config=cfg,
        workers=1,
        retry=0,
    )
    assert summary.total == 1
    assert summary.failed == 1
    assert (out / "batch_failures.jsonl").is_file()
    failures = (out / "batch_failures.jsonl").read_text(encoding="utf-8").strip().split("\n")
    assert len(failures) == 1
    rec = json.loads(failures[0])
    assert "error" in rec


def test_batch_rejects_workers_above_two(tmp_path: Path):
    from writeup2md.config import build_config

    cfg = build_config(Profile.MACBOOK)
    cfg.pipeline.workers = 3
    with pytest.raises(ValueError):
        from writeup2md.config import enforce_macbook_limits

        enforce_macbook_limits(cfg)


def test_batch_creates_status_subdirectories(tmp_path: Path):
    cfg = build_config(Profile.MACBOOK)
    cfg.ocr.backend = "mock"
    out = tmp_path / "out"
    run_batch(
        input_path=FIXTURE_DIR / "batch" / "sources.jsonl",
        output_root=out,
        config=cfg,
        workers=1,
        retry=0,
    )
    for sub in ("accepted", "review", "rejected", "failed"):
        assert (out / sub).is_dir()
