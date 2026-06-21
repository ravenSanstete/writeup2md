"""TASK_11 real-OCR tests for code-aware post-processing.

These tests use the real rapid backend to verify that:
- multi-view retry runs without crashing on real images;
- candidate selection produces a valid result;
- code-aware post-processing does not damage good OCR output.

These tests are marked `real_ocr` and skipped by default. Run with:
    pytest -m real_ocr
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.real_ocr


SMOKE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "ocr_smoke"


def _load_backend():
    from writeup2md.ocr.backend import available_backends, get_backend

    avail = available_backends()
    if not avail:
        pytest.skip("no real OCR backend available")
    return get_backend("auto")


def test_multi_view_runs_on_real_image():
    """Multi-view retry produces at least one candidate on a real image."""
    backend = _load_backend()
    from writeup2md.ocr.multi_view import run_multi_view

    img_path = SMOKE_DIR / "code_python_light.png"
    if not img_path.is_file():
        pytest.skip("smoke fixture missing")
    image_bytes = img_path.read_bytes()
    results = run_multi_view(backend, image_bytes, max_views=4)
    # At least the original view must produce a result.
    assert len(results) >= 1
    # The original view's result should be in the candidate list.
    assert any(vr.view_name == "original" for vr in results)


def test_candidate_selection_picks_non_empty_on_real_image():
    """Candidate selection on real multi-view output picks a non-empty result."""
    backend = _load_backend()
    from writeup2md.ocr.multi_view import run_multi_view
    from writeup2md.ocr.candidate_selection import select_best

    img_path = SMOKE_DIR / "code_python_light.png"
    if not img_path.is_file():
        pytest.skip("smoke fixture missing")
    image_bytes = img_path.read_bytes()
    results = run_multi_view(backend, image_bytes, max_views=4)
    candidates = [vr.result for vr in results]
    best = select_best(candidates, "code")
    assert best is not None


def test_code_postprocess_does_not_damage_clean_text():
    """Code-aware postprocessing on already-clean code text is a no-op
    or produces only minor transformations (never damages content).
    """
    backend = _load_backend()
    img_path = SMOKE_DIR / "code_python_light.png"
    if not img_path.is_file():
        pytest.skip("smoke fixture missing")
    image_bytes = img_path.read_bytes()
    result = backend.recognize(image_bytes)
    text = result.joined_text
    if not text.strip():
        pytest.skip("backend returned empty text")

    from writeup2md.ocr.code_postprocess import (
        normalize_fullwidth_punct,
        recover_indentation,
        split_space_merged_tokens,
    )

    # Apply all three code-postprocess operations.
    out1, _ = split_space_merged_tokens(text, "python")
    out2, _ = normalize_fullwidth_punct(out1)
    out3, _ = recover_indentation(out2, "python")
    # The result should not be empty.
    assert out3.strip()
    # The result should not have INVENTED new tokens — only split / normalized.
    # We check this by ensuring the set of characters in `out3` is a subset of
    # the characters in `text` plus ASCII punctuation that we may have
    # introduced via normalization.
    original_chars = set(text) | set(" \n\t,.()[]{}:;\"'<>=+-*/\\&|#$%@^~`'")
    out_chars = set(out3)
    # Allow ASCII characters that we may have introduced.
    extra = out_chars - original_chars
    # The only allowed extras are ASCII punctuation we may have introduced
    # via fullwidth normalization (already in original_chars).
    allowed_extras = set("")
    assert extra <= allowed_extras, f"unexpected characters introduced: {extra!r}"
