# Real OCR Backend Setup

## Overview

writeup2md supports multiple real OCR backends. The default is `auto`, which
prefers PaddleOCR-VL and never silently falls back to `mock` (mock is reserved
for deterministic tests).

## Backend names

| Name | Package | Status on Apple Silicon |
| --- | --- | --- |
| `auto` | (selects first available real backend) | recommended default |
| `paddleocr-vl` | `paddleocr` + `paddlepaddle` | blocked — no arm64 wheels for PaddlePaddle on macOS |
| `paddleocr-vl-element` | `transformers` + `torch` + `huggingface_hub` | **production backend on this Mac** |
| `rapid` | `rapidocr-onnxruntime` | working — auxiliary CPU backend |
| `mlx` | `mlx-vlm` | experimental; uses paligemma (not PaddleOCR-VL) |
| `mock` | (built-in) | tests only — never selected by `auto` |

`auto` probes backends in this order: `paddleocr-vl` → `paddleocr-vl-element`
→ `rapid` → `mlx`. If none are available it raises a clear error rather than
degrading to mock. On this MacBook `auto` resolves to `paddleocr-vl-element`.

## Identity pin (TASK_15)

PaddleOCR-VL is identity-pinned to an immutable HuggingFace commit SHA:

- Repo: `PaddlePaddle/PaddleOCR-VL`
- Revision: `baee27eebcbf26cdeab160116679d765f13a3f27`
- Pin location: `src/writeup2md/ocr/model_identity.py`
- Verification: `huggingface_hub.model_info()` on first load (cached afterwards; offline mode raises if uncached).
- Recorded in `reports/PADDLEOCR_VL_IDENTITY.json`.

Every inference records `model_repo`, `model_revision`, `pipeline_version`
(`"full"` or `"element"`), and `full_pipeline` in `OcrBackendInfo`.

## Installation

### Minimum real-OCR install (RapidOCR)

```bash
pip install -e ".[real-ocr]"
```

This installs `rapidocr-onnxruntime`, `pillow`, and `numpy`. RapidOCR ships
the PaddleOCR PP-OCR detection + classification + recognition pipeline as ONNX
models that run via `onnxruntime` on CPU — no PaddlePaddle runtime required,
which makes it Apple-Silicon friendly.

### PaddleOCR-VL element mode (production on Apple Silicon)

```bash
pip install -e ".[paddleocr-vl-element]"
```

This installs `transformers`, `torch`, `huggingface_hub`, and `pillow`. The
model loads via `AutoModelForCausalLM.from_pretrained(..., trust_remote_code=True)`
and runs on the `mps` device (Metal Performance Shaders). No PaddlePaddle
runtime is required.

The macOS setup script handles this and verifies with `doctor`:

```bash
bash scripts/setup_paddleocr_vl_macos.sh element
```

### PaddleOCR-VL full pipeline (optional — not arm64-clean on macOS)

```bash
pip install -e ".[paddleocr-vl]"   # adds paddleocr + paddlepaddle
```

This is for Linux/CUDA or x86 macOS. On Apple Silicon the install may fail
because PaddlePaddle has no arm64 wheels. The adapter is implemented and
identity-verified but cannot be exercised on this MacBook.

### Optional backends

```bash
pip install -e ".[mlx-ocr]"      # adds mlx-vlm (experimental VLM path)
```

### Full install

```bash
pip install -e ".[all]"
playwright install chromium
```

## Verifying the installation

```bash
writeup2md doctor
```

Look for the `ocr_backend:auto` row — it lists the available real backends
(e.g. `paddleocr-vl-element,rapid,mlx`). The `paddleocr_vl:element` row
probes `torch` + `transformers`; the `paddleocr_vl:full` row probes
`paddleocr.PaddleOCRVL`.

```bash
writeup2md doctor --require-ocr
```

Exits nonzero if no real backend can run. Use this in CI or before batch runs
that must produce real OCR.

```bash
writeup2md doctor --require-paddleocr-vl
```

Exits nonzero if neither `paddleocr-vl` nor `paddleocr-vl-element` can run.
Use this before batch runs that must use the production backend.

```bash
writeup2md doctor --smoke-ocr evaluation/golden/images/code_py_light_01.png \
    --ocr-backend paddleocr-vl-element --require-exact-backend
```

Loads the production model, runs one inference, prints backend metadata (name,
version, model, device, input dimensions, load time, inference time), and
writes a full raw-output JSON to `reports/doctor_smoke_ocr.json`. The smoke
test fails if the backend is `mock` — mock is never accepted as a real
result. `--require-exact-backend` makes it fail instead of silently falling
back to RapidOCR.

## Selecting a backend at the CLI

```bash
# Default — auto prefers paddleocr-vl-element on this machine
writeup2md convert tutorial.pdf

# Explicit production backend
writeup2md convert tutorial.pdf \
    --ocr-backend paddleocr-vl-element --require-exact-backend

# Explicit RapidOCR (faster, lower accuracy)
writeup2md convert tutorial.pdf --ocr-backend rapid

# Tests only
writeup2md convert tutorial.pdf --ocr-backend mock
```

## Strict backend contract (TASK_15)

`--require-exact-backend` enforces the production contract:

- `--ocr-backend auto --require-exact-backend` raises `BackendIdentityError` if `auto` resolves to a non-PaddleOCR-VL backend.
- `--ocr-backend paddleocr-vl-element --require-exact-backend` raises if element mode is unavailable (no silent fallback to RapidOCR).
- `--ocr-backend paddleocr-vl --require-exact-backend` raises if the full pipeline is unavailable.

Use this for any conversion that must use PaddleOCR-VL.

## Behavior when OCR is unavailable

If `auto` cannot find any real backend, conversion still proceeds but every
visual block is marked `review_required` and the document status is `review`
(or `rejected` if no native text was extracted either). The enricher records
a warning naming the missing backend. **writeup2md never reports fake OCR
output as successful.**

## Resource behavior

Regardless of backend:

- one model instance per process (module-level singleton + `_INSTANCE_LOCK`);
- one inference at a time (shared `_INFERENCE_LOCK`);
- PIL images and internal arrays released after each call;
- model loaded lazily on the first unresolved visual block.

These hold for `rapid`, `paddleocr-vl`, `paddleocr-vl-element`, and `mlx`. The
two-worker batch path (ThreadPoolExecutor) may schedule parsing concurrently,
but OCR inference, Playwright active page, and PDF page rendering remain
serialized by process-local locks.

For `paddleocr-vl-element` specifically, do not use `--workers 2` — the
singleton model + single-inference lock means the second worker would block.
The default `--workers 1` is the correct choice.

## Offline behavior

RapidOCR ships its ONNX models inside the wheel — no network access is needed
at inference time. `paddleocr-vl-element` downloads the model from
HuggingFace on first use (~1.8 GB) and caches it under
`~/.cache/huggingface/hub/`. Subsequent runs are offline unless the cache is
cleared. `paddleocr` (full pipeline) may download weights on first use.
`mlx-vlm` requires a pre-downloaded model (e.g. via `huggingface-cli download`).

## Raw output preservation (TASK_15)

Every PaddleOCR-VL inference writes the unnormalized model output to a temp
file under `/tmp/writeup2md_paddleocr_vl_element_raw/` (or
`/tmp/writeup2md_paddleocr_vl_raw/` for the full pipeline). The path is
recorded in `OcrBackendInfo.raw_output_path`. The raw payload includes
`input_dimensions`, `prompt`, `generation_config`, `output_token_count`, and
`generated_text`.

## Caching

OCR results are not currently cached across runs by content hash. Each
conversion re-runs OCR on unresolved visuals. Resume (batch) skips already-
completed documents entirely, so OCR is not re-run on resume. Per-image
content-hash caching is a future improvement (see known limitations in
`reports/FINAL_IMPLEMENTATION_REPORT.md`).

## Test markers

```bash
python -m pytest                                          # default — skips real_ocr and real_paddleocr_vl
python -m pytest -m real_ocr -v                           # runs real-OCR tests (requires rapidocr)
python -m pytest -m real_paddleocr_vl -v --timeout=600    # runs PaddleOCR-VL tests (requires [paddleocr-vl-element])
```

Real-OCR tests are marked `@pytest.mark.real_ocr` and `@pytest.mark.slow`.
PaddleOCR-VL tests are marked `@pytest.mark.real_paddleocr_vl`. Both sets
reuse a single model instance across the test session.
