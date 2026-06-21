"""Tests for the PaddleOCR-VL exact-model-identity contract (TASK_15).

These tests do NOT require the model to actually load. They verify the
identity-verification module, the metadata fields, and the no-silent-fallback
contract. Tests that require the real model live in
``test_smoke_inference.py`` and ``test_golden_eval.py`` and are marked
``@pytest.mark.real_paddleocr_vl``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from writeup2md.ocr.backend import (
    available_backends,
    BackendIdentityError,
    get_backend,
    reset_backend,
)
from writeup2md.ocr.metadata import OcrBackendInfo
from writeup2md.ocr.model_identity import (
    cached_identity,
    clear_cache,
    ModelIdentityError,
    PADDLEOCR_VL_REPO,
    PADDLEOCR_VL_REVISION,
    verify_model_identity,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_production_pin_constants_are_set():
    """The hard-coded production pin must be present and non-empty."""
    assert PADDLEOCR_VL_REPO == "PaddlePaddle/PaddleOCR-VL"
    assert PADDLEOCR_VL_REVISION
    assert len(PADDLEOCR_VL_REVISION) == 40  # git SHA-1


def test_identity_json_file_matches_pin():
    """reports/PADDLEOCR_VL_IDENTITY.json must agree with the code pin."""
    p = REPO_ROOT / "reports" / "PADDLEOCR_VL_IDENTITY.json"
    assert p.is_file(), f"missing identity file: {p}"
    payload = json.loads(p.read_text(encoding="utf-8"))
    assert payload["model_repo"] == PADDLEOCR_VL_REPO
    assert payload["model_revision"] == PADDLEOCR_VL_REVISION


def test_verify_model_identity_offline_raises_when_uncached():
    """Offline mode must raise ModelIdentityError when nothing is cached."""
    clear_cache()
    with pytest.raises(ModelIdentityError):
        verify_model_identity(offline=True)


def test_ocr_backend_info_has_identity_fields():
    """OcrBackendInfo must carry the TASK_15 identity + fallback fields."""
    info = OcrBackendInfo(
        backend="paddleocr-vl-element",
        backend_version="0.9B-element",
        model_name=PADDLEOCR_VL_REPO,
        device="mps",
    )
    # All TASK_15 fields must exist with defaults.
    assert info.model_repo == ""
    assert info.model_revision == ""
    assert info.pipeline_version == ""
    assert info.full_pipeline is False
    assert info.mock_used is False
    assert info.rapid_used_as_primary is False
    assert info.fallback_used == ""
    # And the to_dict round-trip includes them.
    d = info.to_dict()
    for key in (
        "model_repo",
        "model_revision",
        "pipeline_version",
        "full_pipeline",
        "mock_used",
        "rapid_used_as_primary",
        "fallback_used",
    ):
        assert key in d


def test_get_backend_paddleocr_vl_require_exact_raises_when_unavailable():
    """require_exact_backend=True must raise BackendIdentityError when
    paddleocr-vl is not installed. Never silently fall back to rapid."""
    reset_backend()
    avail = available_backends()
    if "paddleocr-vl" in avail:
        pytest.skip("paddleocr-vl is installed in this env; cannot test the unavailable path")
    with pytest.raises(BackendIdentityError):
        get_backend("paddleocr-vl", require_exact_backend=True)


def test_get_backend_paddleocr_vl_element_require_exact_raises_when_unavailable():
    """Same contract for paddleocr-vl-element."""
    reset_backend()
    avail = available_backends()
    if "paddleocr-vl-element" in avail:
        pytest.skip(
            "paddleocr-vl-element is installed in this env; cannot test the unavailable path"
        )
    with pytest.raises(BackendIdentityError):
        get_backend("paddleocr-vl-element", require_exact_backend=True)


def test_auto_require_exact_raises_when_paddleocr_vl_unavailable():
    """auto + require_exact_backend must raise when no PaddleOCR-VL
    backend is available (RapidOCR is auxiliary only)."""
    reset_backend()
    avail = available_backends()
    if any(b.startswith("paddleocr-vl") for b in avail):
        pytest.skip("a PaddleOCR-VL backend is installed; cannot test the unavailable path")
    with pytest.raises(BackendIdentityError):
        get_backend("auto", require_exact_backend=True)


def test_backend_aliases_resolve_to_canonical_names():
    """Legacy aliases must still work (back-compat)."""
    reset_backend()
    # We can't always instantiate (PaddleOCR may not be installed), but
    # we can check the canonical-name resolver. The alias->canonical
    # mapping is in backend.py:_canonical_name.
    from writeup2md.ocr.backend import _canonical_name

    assert _canonical_name("paddle") == "paddleocr-vl"
    assert _canonical_name("paddleocr_vl") == "paddleocr-vl"
    assert _canonical_name("paddleocr-vl") == "paddleocr-vl"
    assert _canonical_name("paddleocr-vl-element") == "paddleocr-vl-element"
    assert _canonical_name("paddleocr_vl_element") == "paddleocr-vl-element"
    assert _canonical_name("rapid") == "rapid"
    assert _canonical_name("mlx") == "mlx"
    assert _canonical_name("mock") == "mock"
    assert _canonical_name("nonexistent") is None


def test_available_backends_prefers_paddleocr_vl_first():
    """available_backends() must probe PaddleOCR-VL before rapid/mlx."""
    avail = available_backends()
    # If paddleocr-vl* is in the list, it must come before rapid.
    if "rapid" in avail:
        rapid_idx = avail.index("rapid")
        for pv in ("paddleocr-vl", "paddleocr-vl-element"):
            if pv in avail:
                assert avail.index(pv) < rapid_idx, (
                    f"{pv} must be preferred over rapid under auto"
                )


def test_doctor_reports_paddleocr_vl_checks():
    """run_doctor() must surface separate checks for full + element modes."""
    from writeup2md.doctor import run_doctor

    report = run_doctor()
    names = {c.name for c in report.checks}
    assert "paddleocr_vl:full" in names
    assert "paddleocr_vl:element" in names
    assert "huggingface_hub" in names


def test_cached_identity_returns_none_when_empty():
    clear_cache()
    assert cached_identity() is None
