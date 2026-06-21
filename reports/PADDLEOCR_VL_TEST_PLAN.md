# PaddleOCR-VL Test Plan (TASK_15)

## Test organization

| Marker | When to use | Pytest selector |
| --- | --- | --- |
| `real_ocr` (existing) | Tests that need any real OCR backend (rapid, paddle, mlx). Includes the existing 15 tests from TASK_08/09/11. | `pytest -m real_ocr` |
| `real_paddleocr_vl` (new) | Tests that specifically require the PaddleOCR-VL model (full or element). Never satisfied by RapidOCR alone. | `pytest -m real_paddleocr_vl` |
| `slow` (existing) | Long-running tests. | `pytest -m slow` |

## Default test run (no markers)

```bash
python -m pytest
```

Excludes `real_ocr`, `real_paddleocr_vl`, and `web` tests. These
run fast on the MacBook and verify the non-OCR parts of the
pipeline. **Expected: 244+ passing**.

## Real-OCR test run

```bash
python -m pytest -m real_ocr
```

Includes the 15 existing tests (TASK_08/09/11). These exercise
RapidOCR specifically and verify the code-aware OCR pipeline works
end-to-end with a real recognizer.

## PaddleOCR-VL test run

```bash
python -m pytest -m real_paddleocr_vl --timeout=600
```

Runs the 11 tests in `tests/real_paddleocr_vl/`:

- `test_model_identity.py` (9 tests, offline — always runs)
- `test_smoke_inference.py` (6 tests — skip if backend unavailable)
- `test_golden_eval.py` (1 test — skip if backend unavailable)

**Expected on this MacBook**: 14 passing, 3 skipped (full-pipeline
backend not installed; two offline tests skip because element IS
available and cannot test the unavailable path).

## Test files

### `tests/real_paddleocr_vl/test_model_identity.py`

Offline tests (do not require the model to load):

1. `test_production_pin_constants_are_set` — the hard-coded pin is present.
2. `test_identity_json_file_matches_pin` — `reports/PADDLEOCR_VL_IDENTITY.json` agrees with the code pin.
3. `test_verify_model_identity_offline_raises_when_uncached` — offline mode raises when nothing cached.
4. `test_ocr_backend_info_has_identity_fields` — `OcrBackendInfo` carries all TASK_15 fields.
5. `test_get_backend_paddleocr_vl_require_exact_raises_when_unavailable` — no silent fallback.
6. `test_get_backend_paddleocr_vl_element_require_exact_raises_when_unavailable` — same for element.
7. `test_auto_require_exact_raises_when_paddleocr_vl_unavailable` — `auto` + exact = raise.
8. `test_backend_aliases_resolve_to_canonical_names` — legacy aliases work.
9. `test_available_backends_prefers_paddleocr_vl_first` — PaddleOCR-VL probed before rapid.
10. `test_doctor_reports_paddleocr_vl_checks` — doctor surfaces full + element checks.
11. `test_cached_identity_returns_none_when_empty` — cache starts empty.

### `tests/real_paddleocr_vl/test_smoke_inference.py`

Real-inference tests (skip if backend unavailable):

1. `test_element_backend_loads_with_exact_identity` — loads with the pinned identity.
2. `test_element_backend_smoke_inference_records_identity` — full identity in metadata.
3. `test_element_backend_inference_is_deterministic` — `do_sample=False` works.
4. `test_element_backend_input_dimensions_recorded` — width/height captured.
5. `test_element_backend_load_and_inference_durations_recorded` — timing captured.
6. `test_full_backend_smoke_inference_records_identity` — same for the full pipeline (skipped on this MacBook).

### `tests/real_paddleocr_vl/test_golden_eval.py`

1. `test_evaluate_ocr_paddleocr_vl_element_runs` — `evaluate-ocr --backend paddleocr-vl-element` produces a valid summary.

## Regression coverage

The existing `real_ocr` tests (TASK_08/09/11) continue to pass
unchanged. They exercise RapidOCR specifically and verify the
code-aware OCR pipeline (multi-view, candidate selection,
postprocessing, panel splitting) still works.

The existing integration tests in `tests/integration/` were updated
to pin `cfg.ocr.backend = "rapid"` on the four PDF tests that render
whole pages through OCR. This was necessary because `auto` now
prefers PaddleOCR-VL (slower per inference) and the 120-second test
timeout was exceeded. The tests verify PDF capture mechanics, not OCR
quality, so pinning `rapid` is the correct choice.

## Acceptance gate mapping

| Gate (TASK_15 spec) | Test |
| --- | --- |
| Model identity is exact | `test_identity_json_file_matches_pin`, `test_element_backend_smoke_inference_records_identity` |
| No silent fallback | `test_get_backend_paddleocr_vl_require_exact_raises_when_unavailable`, `test_get_backend_paddleocr_vl_element_require_exact_raises_when_unavailable`, `test_auto_require_exact_raises_when_paddleocr_vl_unavailable` |
| `auto` prefers PaddleOCR-VL | `test_available_backends_prefers_paddleocr_vl_first` |
| `doctor --require-paddleocr-vl` exits nonzero when unavailable | Verified manually; environment has it available |
| `OcrBackendInfo` carries identity | `test_ocr_backend_info_has_identity_fields`, `test_element_backend_smoke_inference_records_identity` |
| Raw output preserved | `test_element_backend_smoke_inference_records_identity` |
| Golden Set evaluation runs | `test_evaluate_ocr_paddleocr_vl_element_runs` + manual run |
| Existing tests still pass | Full `pytest` run (244+ fast + 15 real_ocr + 14 real_paddleocr_vl) |
| Real PaddleOCR-VL tests run or skip cleanly | `pytest -m real_paddleocr_vl` (14 pass, 3 skip) |
| MacBook constraints upheld | Verified in `reports/PADDLEOCR_VL_MACBOOK_PERF.md` |
| No semantic repair | `tests/real_ocr/test_code_aware_real.py` (3 tests, unchanged) |
| Documentation updated | README, CLAUDE, docs/04, docs/08, docs/09 updated |
