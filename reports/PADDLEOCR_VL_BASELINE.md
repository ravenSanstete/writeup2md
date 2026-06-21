# PaddleOCR-VL Baseline Capability Report (TASK_15)

## What was delivered

PaddleOCR-VL is now the production OCR backend for writeup2md. Two
clearly separated runtime modes are implemented:

### Mode 1: `paddleocr-vl` (full official pipeline)

- Wraps `paddleocr.PaddleOCRVL()` (the v1 pipeline).
- Includes PP-DocLayoutV2 layout detection + PaddleOCR-VL recognition
  + table/formula/chart branches.
- **Status on this MacBook**: blocked. `paddleocr` and `paddlepaddle`
  are not installed. The adapter is implemented and identity-verified
  but cannot be exercised on this machine.
- Implementation: `src/writeup2md/ocr/paddleocr_vl.py`.

### Mode 2: `paddleocr-vl-element` (HF transformers element mode)

- Loads `PaddlePaddle/PaddleOCR-VL` directly via
  `transformers.AutoModelForCausalLM` + `AutoProcessor` with
  `trust_remote_code=True`.
- Runs on Apple Silicon MPS (or CPU fallback).
- Uses `do_sample=False` for deterministic generation.
- **Status on this MacBook**: working. Verified end-to-end on the
  Golden Set and on real PDF conversion.
- Implementation: `src/writeup2md/ocr/paddleocr_vl_element.py`.

## Identity contract

Every inference records:

- `model_repo = "PaddlePaddle/PaddleOCR-VL"`
- `model_revision = "baee27eebcbf26cdeab160116679d765f13a3f27"` (the pinned commit SHA)
- `pipeline_version = "full"` or `"element"`
- `full_pipeline = True` (full) or `False` (element)
- `mock_used = False`
- `rapid_used_as_primary = False`
- `fallback_used = ""` (empty — no fallback under `require_exact_backend=True`)

The pin lives in `src/writeup2md/ocr/model_identity.py` and is
verified live against HuggingFace on first load via
`huggingface_hub.model_info()`.

## Silent fallback elimination

The legacy `paddleocr_vl.py` adapter had multiple `except: continue`
blocks that silently swallowed import errors, method-probing errors,
and inference errors — returning empty `OcrResult` or routing to
RapidOCR without telling the user. TASK_15 eliminates every one of
those paths:

| Legacy behavior | TASK_15 behavior |
| --- | --- |
| `try paddleocr.PaddleOCRVL(); except: continue` | `import paddleocr` raises `BackendUnavailableError` if missing |
| `try predict(); try ocr(); try __call__()` | `predict()` only — missing method raises `BackendUnavailableError` |
| `except: return OcrResult(raw_text="")` | All exceptions propagate |
| `conf = 0.9` for string text_conf | `conf = 0.0` when no numeric confidence is provided |
| No `OcrBackendInfo` recorded | Full `OcrBackendInfo` with identity fields |
| `auto` resolves to `rapid` | `auto` prefers `paddleocr-vl` > `paddleocr-vl-element` > `rapid` > `mlx` |
| `--require-exact-backend` did not exist | Raises `BackendIdentityError` on any mismatch |

Verified by `tests/real_paddleocr_vl/test_model_identity.py` (offline)
and `tests/real_paddleocr_vl/test_smoke_inference.py` (real model).

## Compatibility shim

The PaddleOCR-VL custom_code (`modeling_paddleocr_vl.py` at the
pinned commit) calls `create_causal_mask(..., inputs_embeds=...)`
(legacy plural spelling). Transformers 4.53+ renamed the parameter
to `input_embeds` (singular). The element-mode backend applies an
idempotent compatibility shim in `_apply_causal_mask_compatibility_shim()`
that translates the legacy kwarg before calling the real function.

The shim is:

- Applied before `from_pretrained` triggers the custom_code import.
- Re-applied after import via `_patch_custom_code_causal_mask()` to
  patch the local reference inside the loaded `transformers_modules.*`
  module.
- Idempotent (`_w2md_patched` attribute).
- Recorded in `engine_version["causal_mask_shim_applied"] = True`.

Without this shim, `model.generate()` raises
`TypeError: create_causal_mask() got an unexpected keyword argument
'inputs_embeds'` on any transformers >= 4.53.

## Raw output preservation

Every inference writes the unnormalized model output to a temp file
under `/tmp/writeup2md_paddleocr_vl_element_raw/` (or
`/tmp/writeup2md_paddleocr_vl_raw/` for full pipeline). The path is
recorded in `OcrBackendInfo.raw_output_path`.

The raw payload for element mode includes:

- `input_dimensions` (width, height)
- `prompt` (the task prompt, e.g. `"OCR:"`)
- `generation_config` (`max_new_tokens`, `do_sample`, `use_cache`)
- `output_token_count`
- `generated_text` (the decoded VLM output)

Verified by
`tests/real_paddleocr_vl/test_smoke_inference.py::test_element_backend_smoke_inference_records_identity`.

## Determinism

`do_sample=False` is hard-coded in the element-mode backend. Verified
by
`tests/real_paddleocr_vl/test_smoke_inference.py::test_element_backend_inference_is_deterministic`:
two consecutive `recognize` calls on the same image produce byte-identical
text.

## What is NOT delivered

- `paddleocr-vl` (full pipeline) has never been exercised on this
  MacBook. The adapter is implemented and identity-verified, but
  `paddleocr` / `paddlepaddle` are not installed. This is documented
  as a known limitation in `reports/TASK_15_COMPLETION.md`.
- The `diff` visual type has the worst CER (0.1336) under
  PaddleOCR-VL element mode. A future round could try the `table` or
  `chart` task prompts for diff content, or fall back to RapidOCR
  specifically for diff blocks.
- PaddleOCR-VL element mode does not produce per-region confidence
  scores. The TASK_09 calibration block is therefore not meaningful
  for this backend. The downstream enricher's structural-quality gate
  still applies.
