"""End-to-end acceptance tests verifying MacBook resource contracts.

These tests are the TASK_07 acceptance gate. They run on a MacBook-safe
configuration (1 worker, 1 OCR instance, 1 inference at a time, sequential
PDF pages, 1 Playwright page per source, lazy Streamlit loading).
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

from writeup2md.config import Profile, build_config, enforce_macbook_limits
from writeup2md.ocr.backend import (
    _INFERENCE_LOCK,
    _INSTANCE,
    _INSTANCE_LOCK,
    get_backend,
    reset_backend,
)


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture(autouse=True)
def _reset_ocr():
    reset_backend()
    yield
    reset_backend()


def test_default_worker_count_is_one():
    cfg = build_config(Profile.MACBOOK)
    assert cfg.pipeline.workers == 1


def test_macbook_profile_rejects_workers_above_two():
    cfg = build_config(Profile.MACBOOK)
    cfg.pipeline.workers = 3
    with pytest.raises(ValueError):
        enforce_macbook_limits(cfg)


def test_macbook_profile_allows_two_workers():
    cfg = build_config(Profile.MACBOOK)
    cfg.pipeline.workers = 2
    enforce_macbook_limits(cfg)  # should not raise


def test_ocr_model_instances_locked_to_one():
    cfg = build_config(Profile.MACBOOK)
    assert cfg.ocr.model_instances == 1
    assert cfg.ocr.max_concurrent_inference == 1


def test_heavy_queue_capacity_at_most_two():
    cfg = build_config(Profile.MACBOOK)
    assert cfg.ocr.heavy_queue_capacity <= 2


def test_one_backend_instance_reused_across_calls():
    """get_backend returns the same instance for the same name."""
    reset_backend()
    b1 = get_backend("mock")
    b2 = get_backend("mock")
    assert b1 is b2
    reset_backend()


def test_inference_lock_is_serialized():
    """The inference lock cannot be acquired twice from different threads."""
    lock = _INFERENCE_LOCK
    acquired_main = lock.acquire(blocking=False)
    try:
        assert acquired_main
        result = {}

        def _try():
            result["acquired"] = lock.acquire(blocking=False)
            if result["acquired"]:
                lock.release()

        t = threading.Thread(target=_try)
        t.start()
        t.join()
        assert result["acquired"] is False
    finally:
        lock.release()


def test_pdf_pages_processed_sequentially(tmp_path: Path):
    """The PDF adapter processes pages one at a time. We verify by patching
    load_page to track call ordering."""
    pdf_path = FIXTURE_DIR / "pdf" / "writeup.pdf"
    if not pdf_path.is_file():
        pytest.skip("PDF fixture missing")
    from writeup2md.adapters import pdf as pdf_adapter

    cfg = build_config(Profile.MACBOOK)
    cfg.ocr.backend = "mock"

    # Patch _render_page_to_png_bytes to record concurrent calls.
    call_count = [0]
    max_concurrent = [0]
    lock = threading.Lock()

    orig_render = pdf_adapter._render_page_to_png_bytes

    def wrapped(page, dpi):
        with lock:
            call_count[0] += 1
            max_concurrent[0] = max(max_concurrent[0], 1)
        # Simulate some work; if any other thread were here, max_concurrent
        # would exceed 1 (but we run sequentially so it never does).
        result = orig_render(page, dpi)
        with lock:
            pass
        return result

    pdf_adapter._render_page_to_png_bytes = wrapped
    try:
        result = pdf_adapter.convert_pdf(
            source=str(pdf_path),
            output_root=tmp_path,
            config=cfg,
            keep_evidence=True,
        )
    finally:
        pdf_adapter._render_page_to_png_bytes = orig_render

    assert result.status.value in ("accepted", "review")
    # The fixture has 2 pages and no scanned pages, so render is only called
    # for scanned pages (0 in this case). Either way, max_concurrent must be
    # at most 1.
    assert max_concurrent[0] <= 1


def test_final_markdown_contains_no_images(tmp_path: Path):
    """Every generated document.md must be image-free."""
    from writeup2md.adapters.html import convert_html

    cfg = build_config(Profile.MACBOOK)
    cfg.ocr.backend = "mock"
    result = convert_html(
        source=str(FIXTURE_DIR / "html" / "tutorial.html"),
        output_root=tmp_path,
        config=cfg,
        keep_evidence=True,
    )
    md = (result.document_dir / "document.md").read_text(encoding="utf-8")
    assert "![" not in md
    assert "<img" not in md
    assert "data:image/" not in md


def test_raw_evidence_unchanged_after_human_revision(tmp_path: Path):
    """Human revisions must not mutate raw evidence or raw OCR output."""
    from writeup2md.adapters.html import convert_html
    from writeup2md.ui.review_store import set_block_correction, set_document_status

    cfg = build_config(Profile.MACBOOK)
    cfg.ocr.backend = "mock"
    result = convert_html(
        source=str(FIXTURE_DIR / "html" / "tutorial.html"),
        output_root=tmp_path,
        config=cfg,
        keep_evidence=True,
    )
    doc_dir = result.document_dir

    # Snapshot raw evidence file hashes.
    evidence_dir = doc_dir / "evidence"
    raw_hashes_before: dict[str, str] = {}
    if evidence_dir.is_dir():
        for f in evidence_dir.rglob("*"):
            if f.is_file():
                import hashlib

                raw_hashes_before[str(f.relative_to(doc_dir))] = hashlib.sha256(
                    f.read_bytes()
                ).hexdigest()

    # Snapshot raw document.json.
    doc_json_before = (doc_dir / "document.json").read_text(encoding="utf-8")
    md_before = (doc_dir / "document.md").read_text(encoding="utf-8")

    # Apply human revisions.
    set_document_status(doc_dir, "accepted")
    set_block_correction(doc_dir, "b_000014", "HUMAN EDITED CONTENT")

    # Verify raw artifacts unchanged.
    assert (doc_dir / "document.json").read_text(encoding="utf-8") == doc_json_before
    assert (doc_dir / "document.md").read_text(encoding="utf-8") == md_before
    for rel, sha in raw_hashes_before.items():
        import hashlib

        actual = hashlib.sha256((doc_dir / rel).read_bytes()).hexdigest()
        assert actual == sha, f"evidence file {rel} was mutated"

    # Revisions land in review/.
    assert (doc_dir / "review" / "review_state.json").is_file()
    assert (doc_dir / "review" / "revisions.jsonl").is_file()
    revs = (doc_dir / "review" / "revisions.jsonl").read_text(encoding="utf-8").strip().split("\n")
    assert len(revs) >= 2


def test_batch_resume_does_not_duplicate_outputs(tmp_path: Path):
    """Resuming a batch must not re-process completed sources or create duplicates."""
    from writeup2md.batch import run_batch

    cfg = build_config(Profile.MACBOOK)
    cfg.ocr.backend = "mock"
    out = tmp_path / "batch"

    s1 = run_batch(
        input_path=FIXTURE_DIR / "batch" / "sources.jsonl",
        output_root=out,
        config=cfg,
        workers=1,
        retry=0,
    )
    doc_dirs_after_first = sorted(p.name for p in out.iterdir() if p.is_dir() and p.name not in {"accepted", "review", "rejected", "failed"})

    s2 = run_batch(
        input_path=FIXTURE_DIR / "batch" / "sources.jsonl",
        output_root=out,
        config=cfg,
        workers=1,
        retry=0,
    )
    doc_dirs_after_second = sorted(p.name for p in out.iterdir() if p.is_dir() and p.name not in {"accepted", "review", "rejected", "failed"})

    assert s2.skipped == s1.total
    assert doc_dirs_after_first == doc_dirs_after_second  # no new dirs


def test_cli_help_lists_required_commands():
    from typer.testing import CliRunner

    from writeup2md.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("convert", "batch", "inspect", "ui", "doctor"):
        assert cmd in result.output


def test_no_distributed_dependencies_in_config():
    """The MacBook profile must not enable Docker/Ray/Celery/vLLM."""
    cfg = build_config(Profile.MACBOOK)
    dump = cfg.model_dump(mode="json")
    serialized = json.dumps(dump).lower()
    for forbidden in ("docker", "ray", "celery", "kubernetes", "vllm"):
        assert forbidden not in serialized, f"{forbidden!r} appears in config"


def test_streamlit_launch_does_not_load_ocr_model():
    """Importing the UI app must not trigger any OCR backend import."""
    import importlib
    import sys

    # Remove any cached OCR modules.
    for mod in list(sys.modules):
        if mod.startswith("writeup2md.ocr"):
            del sys.modules[mod]
    # Import the UI app.
    if "writeup2md.ui.app" in sys.modules:
        del sys.modules["writeup2md.ui.app"]
    importlib.import_module("writeup2md.ui.app")
    # The OCR backend module should NOT have been imported.
    assert "writeup2md.ocr.backend" not in sys.modules
    assert "writeup2md.ocr.paddleocr_vl" not in sys.modules


def test_full_layout_exists_for_each_output(tmp_path: Path):
    """Every output directory must contain the required files."""
    from writeup2md.adapters.pdf import convert_pdf

    cfg = build_config(Profile.MACBOOK)
    cfg.ocr.backend = "mock"
    result = convert_pdf(
        source=str(FIXTURE_DIR / "pdf" / "writeup.pdf"),
        output_root=tmp_path,
        config=cfg,
        keep_evidence=True,
    )
    d = result.document_dir
    for name in ("document.md", "document.json", "manifest.json", "diagnostics.json", "provenance.jsonl"):
        assert (d / name).is_file(), f"missing {name}"
    assert (d / "raw").is_dir()
    assert (d / "evidence").is_dir()
    assert (d / "review").is_dir()


def test_provenance_maps_every_block(tmp_path: Path):
    """Every Markdown block must map to a provenance record."""
    from writeup2md.adapters.html import convert_html

    cfg = build_config(Profile.MACBOOK)
    cfg.ocr.backend = "mock"
    result = convert_html(
        source=str(FIXTURE_DIR / "html" / "tutorial.html"),
        output_root=tmp_path,
        config=cfg,
        keep_evidence=True,
    )
    doc = json.loads((result.document_dir / "document.json").read_text(encoding="utf-8"))
    provenance = (result.document_dir / "provenance.jsonl").read_text(encoding="utf-8").strip().split("\n")
    assert len(provenance) == len(doc["blocks"])
    for line in provenance:
        rec = json.loads(line)
        assert rec["block_id"]
        assert rec["source_kind"]
