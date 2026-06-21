"""Real-inference smoke tests for the PaddleOCR-VL backends (TASK_15).

These tests require the actual PaddleOCR-VL model to load. They are
marked ``@pytest.mark.real_paddleocr_vl`` and are skipped automatically
when no PaddleOCR-VL backend is available. They are NEVER faked — if
the model cannot run, the test skips with a clear reason rather than
passing on empty output.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from writeup2md.ocr.backend import (
    available_backends,
    get_backend,
    reset_backend,
)
from writeup2md.ocr.model_identity import (
    PADDLEOCR_VL_REPO,
    PADDLEOCR_VL_REVISION,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_DIR = REPO_ROOT / "evaluation" / "golden"
GOLDEN_IMAGE = GOLDEN_DIR / "images" / "code_py_light_01.png"


pytestmark = pytest.mark.real_paddleocr_vl


def _element_available() -> bool:
    return "paddleocr-vl-element" in available_backends()


def _full_available() -> bool:
    return "paddleocr-vl" in available_backends()


def test_element_backend_loads_with_exact_identity():
    if not _element_available():
        pytest.skip("paddleocr-vl-element not available")
    reset_backend()
    b = get_backend("paddleocr-vl-element", require_exact_backend=True)
    assert b.name == "paddleocr-vl-element"


def test_element_backend_smoke_inference_records_identity():
    if not _element_available():
        pytest.skip("paddleocr-vl-element not available")
    if not GOLDEN_IMAGE.is_file():
        pytest.skip(f"missing golden image: {GOLDEN_IMAGE}")
    reset_backend()
    b = get_backend("paddleocr-vl-element", require_exact_backend=True)
    result = b.recognize(GOLDEN_IMAGE.read_bytes())

    # Identity contract.
    assert result.metadata.get("model_repo") == PADDLEOCR_VL_REPO
    assert result.metadata.get("model_revision") == PADDLEOCR_VL_REVISION
    assert result.metadata.get("pipeline_version") == "element"
    assert result.metadata.get("full_pipeline") is False
    assert result.metadata.get("mock_used") is False
    assert result.metadata.get("rapid_used_as_primary") is False

    # Raw output preserved on disk.
    raw_path = result.metadata.get("raw_output_path")
    assert raw_path
    assert Path(raw_path).exists(), f"raw output not preserved at {raw_path}"
    raw_payload = json.loads(Path(raw_path).read_text(encoding="utf-8"))
    assert "generated_text" in raw_payload
    assert "prompt" in raw_payload

    # The model must have produced SOME text — never empty.
    assert result.raw_text.strip(), "PaddleOCR-VL produced empty text on a known-good image"


def test_element_backend_inference_is_deterministic():
    """Two runs on the same image must produce identical text
    (do_sample=False contract)."""
    if not _element_available():
        pytest.skip("paddleocr-vl-element not available")
    if not GOLDEN_IMAGE.is_file():
        pytest.skip(f"missing golden image: {GOLDEN_IMAGE}")
    reset_backend()
    b = get_backend("paddleocr-vl-element", require_exact_backend=True)
    img_bytes = GOLDEN_IMAGE.read_bytes()
    r1 = b.recognize(img_bytes)
    r2 = b.recognize(img_bytes)
    assert r1.raw_text == r2.raw_text, (
        "PaddleOCR-VL element-mode inference is not deterministic — "
        "do_sample=False may not be honored"
    )


def test_element_backend_input_dimensions_recorded():
    if not _element_available():
        pytest.skip("paddleocr-vl-element not available")
    if not GOLDEN_IMAGE.is_file():
        pytest.skip(f"missing golden image: {GOLDEN_IMAGE}")
    reset_backend()
    b = get_backend("paddleocr-vl-element", require_exact_backend=True)
    result = b.recognize(GOLDEN_IMAGE.read_bytes())
    dims = result.metadata.get("input_dimensions")
    assert dims is not None
    assert isinstance(dims, list)
    assert len(dims) == 2
    assert all(isinstance(d, int) and d > 0 for d in dims)


def test_element_backend_load_and_inference_durations_recorded():
    if not _element_available():
        pytest.skip("paddleocr-vl-element not available")
    if not GOLDEN_IMAGE.is_file():
        pytest.skip(f"missing golden image: {GOLDEN_IMAGE}")
    reset_backend()
    b = get_backend("paddleocr-vl-element", require_exact_backend=True)
    result = b.recognize(GOLDEN_IMAGE.read_bytes())
    assert result.metadata.get("load_duration_s", 0) >= 0
    assert result.metadata.get("inference_duration_s", 0) > 0


def test_full_backend_smoke_inference_records_identity():
    if not _full_available():
        pytest.skip("paddleocr-vl (full pipeline) not available")
    if not GOLDEN_IMAGE.is_file():
        pytest.skip(f"missing golden image: {GOLDEN_IMAGE}")
    reset_backend()
    b = get_backend("paddleocr-vl", require_exact_backend=True)
    result = b.recognize(GOLDEN_IMAGE.read_bytes())

    assert result.metadata.get("model_repo") == PADDLEOCR_VL_REPO
    assert result.metadata.get("model_revision") == PADDLEOCR_VL_REVISION
    assert result.metadata.get("pipeline_version") == "full"
    assert result.metadata.get("full_pipeline") is True
    assert result.metadata.get("mock_used") is False
    assert result.metadata.get("rapid_used_as_primary") is False
