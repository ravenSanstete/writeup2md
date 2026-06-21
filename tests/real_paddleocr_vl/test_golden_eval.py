"""Golden Set evaluation against PaddleOCR-VL (TASK_15).

Marked ``@pytest.mark.real_paddleocr_vl``. Skipped (not faked) when
the backend cannot load.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from writeup2md.ocr.backend import available_backends, reset_backend


REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_DIR = REPO_ROOT / "evaluation" / "golden"


pytestmark = pytest.mark.real_paddleocr_vl


def _element_available() -> bool:
    return "paddleocr-vl-element" in available_backends()


def test_evaluate_ocr_paddleocr_vl_element_runs():
    if not _element_available():
        pytest.skip("paddleocr-vl-element not available")
    if not GOLDEN_DIR.is_dir():
        pytest.skip(f"missing golden dir: {GOLDEN_DIR}")
    from writeup2md.evaluate import evaluate_golden_set

    reset_backend()
    import tempfile

    out = Path(tempfile.mkdtemp()) / "golden-eval-paddleocr-vl-element"
    result = evaluate_golden_set(
        golden_dir=GOLDEN_DIR,
        backend_name="paddleocr-vl-element",
        output_dir=out,
    )
    summary = result["summary"]
    # Must produce a CER value (not crash). The exact value depends on
    # the model's accuracy, which is what we want to measure.
    assert "cer_mean" in summary
    assert 0.0 <= summary["cer_mean"] <= 1.0
    # Must record the backend identity.
    assert result["backend"] in ("paddleocr-vl-element", "paddleocr-vl")
    # Per-sample results must be on disk.
    results_jsonl = out / "results.jsonl"
    assert results_jsonl.is_file()
    sample_lines = results_jsonl.read_text(encoding="utf-8").strip().splitlines()
    assert len(sample_lines) >= 40  # Golden Set has 45 samples
