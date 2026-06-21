"""Real-OCR Golden Set evaluation tests.

Marked `real_ocr` + `slow`. Skipped when rapidocr-onnxruntime is not
installed. Run with:

    python -m pytest -m real_ocr -v
"""

from __future__ import annotations

from pathlib import Path

import pytest


GOLDEN_DIR = Path("evaluation/golden")


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
        reason="rapidocr-onnxruntime not installed",
    ),
]


@pytest.fixture(autouse=True)
def _reset_backend():
    from writeup2md.ocr.backend import reset_backend

    reset_backend()
    yield
    reset_backend()


def test_golden_set_has_at_least_40_samples():
    """Spec requires ≥40 high-quality manually verified samples."""
    manifest = GOLDEN_DIR / "manifest.jsonl"
    assert manifest.is_file(), f"manifest missing: {manifest}"
    n = sum(1 for ln in manifest.read_text(encoding="utf-8").splitlines() if ln.strip())
    assert n >= 40, f"Golden Set has {n} samples; spec requires ≥40"


def test_golden_set_covers_required_visual_types():
    manifest = GOLDEN_DIR / "manifest.jsonl"
    import json

    vtypes = set()
    for ln in manifest.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        vtypes.add(json.loads(ln)["visual_type"])
    required = {"code", "terminal", "http", "diff", "configuration", "log", "traceback"}
    missing = required - vtypes
    assert not missing, f"Golden Set missing required visual types: {missing}"


def test_evaluate_ocr_runs_and_produces_reports(tmp_path):
    """End-to-end evaluator run on the rapid backend."""
    from writeup2md.evaluate import evaluate_golden_set

    out = evaluate_golden_set(
        GOLDEN_DIR,
        backend_name="rapid",
        output_dir=tmp_path,
    )
    assert out["backend"] == "rapid"
    assert out["is_mock"] is False
    assert out["sample_count"] >= 40
    s = out["summary"]
    # Sanity bounds on metrics.
    assert 0.0 <= s["cer_mean"] <= 1.0
    assert 0.0 <= s["char_accuracy_mean"] <= 1.0
    assert 0.0 <= s["critical_token_recall_mean"] <= 1.0
    # Calibration under production thresholds must show no false accepts on
    # a high-precision policy.
    cal = out["calibration"]
    assert cal["accepted_precision"] >= 0.98 or cal["accepted_count"] == 0, (
        "production calibration must not produce false accepts"
    )
    # Reports written.
    assert (tmp_path / "results.jsonl").is_file()
    assert (tmp_path / "summary.json").is_file()
    assert (tmp_path / "by_visual_type.json").is_file()


def test_metrics_per_sample_have_required_fields():
    from writeup2md.evaluate import evaluate_golden_set

    import json

    out = evaluate_golden_set(GOLDEN_DIR, backend_name="rapid", output_dir=Path("reports/golden-eval"))
    # results.jsonl written by the previous test; re-read it.
    results_path = Path("reports/golden-eval/results.jsonl")
    assert results_path.is_file()
    records = [json.loads(l) for l in results_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(records) >= 40
    for r in records[:5]:
        if "error" in r:
            continue
        assert "cer" in r
        assert "char_accuracy" in r
        assert "exact_match" in r
        assert "critical_tokens" in r
        assert "visual_type" in r
        assert "raw_ocr_text" in r
        assert "gold_text" in r
