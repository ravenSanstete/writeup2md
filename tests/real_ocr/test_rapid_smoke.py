"""Real-OCR smoke tests for the rapidocr-onnxruntime backend.

These tests are marked `real_ocr` and `slow`. They are SKIPPED by default
(`python -m pytest` does not run them) and require rapidocr-onnxruntime.

Run them with:
    python -m pytest -m real_ocr -v

The tests verify that:
- rapidocr loaded (skip if unavailable);
- the backend name is `rapid`, NOT `mock`;
- one model instance is reused across calls;
- inference is serialized (a second concurrent acquire fails);
- all 10 smoke fixtures produce non-empty output with metadata;
- raw outputs are persisted to reports/real_ocr_smoke/.
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

import pytest


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "ocr_smoke"
SMOKE_REPORT_DIR = Path("reports") / "real_ocr_smoke"


def _rapid_available() -> bool:
    try:
        import rapidocr_onnxruntime  # type: ignore  # noqa: F401

        return True
    except Exception:
        return False


pytestmark = [
    pytest.mark.real_ocr,
    pytest.mark.slow,
    pytest.mark.skipif(
        not _rapid_available(),
        reason="rapidocr-onnxruntime not installed; install with: pip install rapidocr-onnxruntime",
    ),
]


@pytest.fixture(autouse=True)
def _reset_backend():
    from writeup2md.ocr.backend import reset_backend

    reset_backend()
    yield
    reset_backend()


SMOKE_FIXTURES = [
    "code_python_light.png",
    "code_python_dark.png",
    "config_yaml.png",
    "code_with_line_numbers.png",
    "low_resolution_code.png",
    "command_plus_output.png",
    "punctuation_heavy.png",
    "indentation_sensitive.png",
    # Two reused fixtures from the original ocr/ dir:
    "../ocr/terminal_bash.png",
    "../ocr/http_request.png",
]


def test_backend_name_is_rapid_not_mock():
    from writeup2md.ocr.backend import get_backend

    b = get_backend("rapid")
    assert b.name == "rapid"
    assert b.name != "mock"


def test_auto_selects_a_real_backend():
    from writeup2md.ocr.backend import available_backends, get_backend

    avail = available_backends()
    assert "rapid" in avail, "rapidocr should be available for this test"
    b = get_backend("auto")
    assert b.name != "mock", "auto must never select mock"
    # TASK_15: auto may resolve to paddleocr-vl, paddleocr-vl-element,
    # rapid, or mlx. The legacy "paddle" name was renamed to
    # "paddleocr-vl".
    assert b.name in ("rapid", "paddleocr-vl", "paddleocr-vl-element", "mlx")


def test_one_instance_reused_across_calls():
    from writeup2md.ocr.backend import get_backend

    b1 = get_backend("rapid")
    data = (FIXTURE_DIR / "code_python_light.png").read_bytes()
    b1.recognize(data)
    b2 = get_backend("rapid")
    assert b1 is b2, "rapid backend must be a process-wide singleton"


def test_inference_lock_is_serialized():
    """Two threads cannot run rapidocr inference at the same time."""
    from writeup2md.ocr.backend import acquire_inference_lock, get_backend

    b = get_backend("rapid")
    lock = acquire_inference_lock()
    data = (FIXTURE_DIR / "code_python_light.png").read_bytes()

    # Hold the lock from the main thread; the worker must block.
    acquired_main = lock.acquire(blocking=False)
    assert acquired_main
    worker_acquired = {"v": None}

    def _try():
        # Non-blocking acquire must fail while main holds the lock.
        worker_acquired["v"] = lock.acquire(blocking=False)
        if worker_acquired["v"]:
            lock.release()

    t = threading.Thread(target=_try)
    t.start()
    t.join()
    try:
        assert worker_acquired["v"] is False
    finally:
        lock.release()


def test_all_smoke_fixtures_produce_output_with_metadata():
    from writeup2md.ocr.backend import get_backend

    b = get_backend("rapid")
    SMOKE_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    results_summary = []

    for rel in SMOKE_FIXTURES:
        p = (FIXTURE_DIR / rel).resolve()
        if not p.is_file():
            pytest.skip(f"fixture missing: {p}")
        data = p.read_bytes()
        result = b.recognize(data)

        # Persist raw output for audit.
        out_path = SMOKE_REPORT_DIR / (p.stem + ".json")
        out_path.write_text(
            json.dumps(
                {
                    "fixture": str(p),
                    "backend": result.backend,
                    "is_mock": result.metadata.get("is_mock"),
                    "input_dimensions": result.metadata.get("input_dimensions"),
                    "load_duration_s": result.metadata.get("load_duration_s"),
                    "inference_duration_s": result.metadata.get("inference_duration_s"),
                    "region_count": len(result.regions),
                    "model_confidence": result.model_confidence,
                    "regions": [
                        {"text": r.text, "confidence": r.confidence, "bbox": r.bbox}
                        for r in result.regions
                    ],
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        # Metadata discipline.
        assert result.backend == "rapid"
        assert result.metadata.get("is_mock") is False
        assert result.metadata.get("input_dimensions") is not None
        assert result.metadata.get("load_duration_s", 0) >= 0
        assert result.metadata.get("inference_duration_s", 0) > 0
        assert "engine_version" in result.metadata
        # Some fixtures (low_resolution) may legitimately produce little text,
        # but most must produce something. We assert non-empty for at least 8
        # of 10 to allow for one or two edge cases.
        results_summary.append((p.name, len(result.regions), result.raw_text.strip()))

    non_empty = sum(1 for _, _, t in results_summary if t)
    assert non_empty >= 8, (
        f"expected at least 8 of {len(results_summary)} fixtures to produce text, "
        f"got {non_empty}: {results_summary}"
    )


def test_metadata_records_versions_and_durations():
    from writeup2md.ocr.backend import get_backend

    b = get_backend("rapid")
    data = (FIXTURE_DIR / "code_python_light.png").read_bytes()
    result = b.recognize(data)
    md = result.metadata
    assert md["backend"] == "rapid"
    assert md["model_name"]
    assert md["device"]
    assert "rapidocr_onnxruntime" in md.get("engine_version", {})
    assert md["input_dimensions"] == [640, 132]


def test_missing_backend_raises_clear_error():
    """Requesting an unknown backend name must raise ValueError."""
    from writeup2md.ocr.backend import get_backend

    with pytest.raises(ValueError, match="unknown OCR backend"):
        get_backend("does_not_exist")


def test_mock_is_never_selected_by_auto():
    """auto must not pick mock even if listed as an option."""
    from writeup2md.ocr.backend import available_backends, get_backend

    avail = available_backends()
    assert "mock" not in avail
    b = get_backend("auto")
    assert b.name != "mock"
