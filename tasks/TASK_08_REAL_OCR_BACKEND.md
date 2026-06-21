# TASK_08 — Real OCR Backend Integration and MacBook Validation

## Goal

Move from a mock-only-validated OCR stack to a real, verified OCR backend that runs on this MacBook. Wire `rapidocr-onnxruntime` as the primary real backend (it is the closest PaddleOCR-equivalent that actually runs on Apple Silicon here), keep the `paddleocr_vl` path for environments that have it, add `mlx` as an optional secondary path, and introduce `auto` which selects a real backend and never falls back to mock silently.

## Backend name vocabulary

```text
mock    # deterministic tests only
rapid   # rapidocr-onnxruntime (primary real backend on this Mac)
paddle  # paddleocr_vl (optional; validated only where installed)
mlx     # mlx-vlm based (optional; experimental)
auto    # pick the first available real backend in order [rapid, paddle, mlx]
```

`auto` MUST NOT select `mock`.

## Deliverables

1. `src/writeup2md/ocr/rapid.py` — RapidOcrBackend:
   - lazy model load, one instance per process (module-level singleton + lock)
   - serialized inference via the shared `_INFERENCE_LOCK`
   - records: backend name, rapidocr-onnxruntime version, onnxruntime provider, device, model load duration, per-region inference duration, input image dimensions, preprocessing/retry flags
   - preserves raw model output before normalization
   - never invents confidence (when rapidocr returns no confidence, the region is recorded with confidence 0.0 and the result is flagged)
   - raises a clear actionable error when rapidocr-onnxruntime is not installed
2. `src/writeup2md/ocr/mlx_backend.py` — MlxOcrBackend (best-effort, optional):
   - same metadata discipline
   - if mlx-vlm cannot produce usable OCR, `recognize` raises a clear error (never returns fake text)
3. `src/writeup2md/ocr/backend.py` — updated registry:
   - `_instantiate` accepts `mock`, `rapid`, `paddle`, `paddleocr_vl`, `mlx`, `auto`
   - `auto` probes `rapid` → `paddle` → `mlx` and returns the first that loads; raises if none available
   - `available_backends()` helper used by doctor and `auto`
4. `src/writeup2md/ocr/metadata.py` — `OcrBackendInfo` dataclass with: name, version, model_name, device, engine_version (rapidocr/onnxruntime/paddle/mlx), load_duration_s, inference_duration_s, input_dimensions, preprocessing_used, retry_used, raw_output_path
5. `OcrResult` schema extended with `metadata: dict[str, Any]` (additive; existing fields preserved)
6. `doctor.py`:
   - `--require-ocr` exits nonzero when no real backend loads
   - `--smoke-ocr PATH` loads the real model, runs one inference on the given image, prints backend/model metadata, load time, inference time, saves raw output to `reports/doctor_smoke_ocr.json`, asserts mock was not used
   - new check `ocr_backend:auto` that reports the first available real backend (or "none")
7. `tests/fixtures/ocr_smoke/` — 10 real screenshot fixtures (legally created, rendered visual text):
   - `code_python_light.png`
   - `code_python_dark.png`
   - `terminal_bash.png` (already present, reused)
   - `http_request.png` (already present, reused)
   - `config_yaml.png`
   - `code_with_line_numbers.png`
   - `low_resolution_code.png`
   - `command_plus_output.png`
   - `punctuation_heavy.png`
   - `indentation_sensitive.png`
8. `tests/real_ocr/test_rapid_smoke.py` — `@pytest.mark.real_ocr` tests that:
   - verify rapidocr loaded (skip if unavailable)
   - process at least 10 fixtures
   - assert backend name is `rapid` (not mock)
   - assert one instance reused
   - assert inference serialized (threading test)
   - assert metadata fields populated
   - assert raw outputs persisted to `reports/real_ocr_smoke/`
9. `pyproject.toml` — add `real_ocr` marker, add `rapidocr-onnxruntime` to a new `real-ocr` optional extra
10. `docs/09_REAL_OCR_SETUP.md` — installation, backend selection, smoke test procedure, offline behavior, model caching notes

## Acceptance gates

- `python -m pytest` (default) still passes (≥171 tests). Real-OCR tests are skipped by default.
- `python -m pytest -m real_ocr -v` runs and passes when rapidocr-onnxruntime is installed.
- `writeup2md doctor --require-ocr` exits 0 on this machine (rapidocr available).
- `writeup2md doctor --smoke-ocr tests/fixtures/ocr_smoke/code_python_light.png` runs a real inference, prints metadata, writes `reports/doctor_smoke_ocr.json`, and the JSON's `backend` field is `rapid` (not `mock`).
- One model instance reused across 10+ recognitions.
- Inference serialized (concurrent acquire fails).
- Missing dependencies produce actionable errors (rapidocr import path tested by simulating absence).

## Constraints

- No new model instances per call.
- No concurrent inference.
- No multi-process inference server.
- No Docker / Ray / Celery / vLLM.
- PIL images and rapidocr internal arrays released after each call.
- The `mock` backend remains ONLY for deterministic tests.
