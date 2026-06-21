# PaddleOCR-VL Integration — TASK_15 audit and progress

> This file is the live audit + progress record for TASK_15. It is
> written before any code changes and updated as work proceeds. The
> final completion report lives in `reports/TASK_15_COMPLETION.md`.

## 0. Model identity (verified 2026-06-20)

- HuggingFace repo: `PaddlePaddle/PaddleOCR-VL`
- Resolved commit SHA: `baee27eebcbf26cdeab160116679d765f13a3f27`
- Last modified: 2026-05-28
- Tags: `PaddleOCR`, `safetensors`, `paddleocr_vl`, `ERNIE4.5`,
  `PaddlePaddle`, `image-to-text`, `ocr`, `document-parse`, `layout`,
  `table`, `formula`, `chart`, `image-text-to-text`, `conversational`,
  `custom_code`, `en`, `zh`, `multilingual`,
  `arxiv:2510.14528`, `base_model:baidu/ERNIE-4.5-0.3B-Paddle`.
- Repo siblings (selected): `PP-DocLayoutV2/{config.json,inference.pdiparams,inference.pdmodel,inference.yml}`,
  `README.md`, `added_tokens.json`, `chat_template.jinja`, `config.json`,
  `configuration_paddleocr_vl.py`, `generation_config.json`,
  `image_processing_paddleocr_vl.py`, `inference.yml`, `model.safetensors`,
  `modeling_paddleocr_vl.py`, `preprocessor_config.json`,
  `processing_paddleocr_vl.py`, `processor_config.json`,
  `special_tokens_map.json`, `tokenizer.json`, `tokenizer.model`,
  `tokenizer_config.json`.
- The model is a 0.9B-parameter VLM built on
  `baidu/ERNIE-4.5-0.3B-Paddle`. It uses `custom_code`
  (`modeling_paddleocr_vl.py`, `processing_paddleocr_vl.py`,
  `image_processing_paddleocr_vl.py`, `configuration_paddleocr_vl.py`)
  which means `trust_remote_code=True` is required when loading via
  `transformers`.
- Two clearly separable runtime modes exist:
  1. **Full official pipeline** — `paddleocr` library wraps
     `PP-DocLayoutV2` (layout detection) + `PaddleOCR-VL` (recognition)
     + table/formula/chart branches. Inputs: whole page or image.
     Outputs: structured layout + recognized text per element.
  2. **Element-only VLM** — load `PaddleOCR-VL` directly with
     `transformers.AutoModelForImageTextToText` +
     `AutoProcessor`, feed pre-cropped element images, get text out.
     This is the path that works on Apple Silicon without
     PaddlePaddle's MPS gaps.

## 1. Audit — current implementation (pre-TASK_15)

### 1.1 `auto` silently resolves to RapidOCR

`src/writeup2md/ocr/backend.py`:

- `available_backends()` probes in order `("rapid", "paddle", "mlx")`
  and returns the names whose `_probe_backend` succeeds.
- `_resolve_auto()` returns `available_backends()[0]`. Because
  `rapidocr-onnxruntime` is installed and PaddleOCR is not, `auto`
  always resolves to `rapid` in this environment.
- This means **the production `auto` backend is RapidOCR, not
  PaddleOCR-VL**, and the existing CLI help string "auto (default)"
  is silently misleading. The CLAUDE.md mission statement ("PaddleOCR-VL
  is the default real backend") is not enforced.

### 1.2 Existing `paddleocr_vl.py` adapter has multiple silent-fallback paths

`src/writeup2md/ocr/paddleocr_vl.py`:

- Lines 55–65: tries `paddleocr.PaddleOCRVL()` then
  `paddleocr_vl.PaddleOCRVL()` inside a `for` loop with
  `except Exception: continue`. Every exception is swallowed. If
  neither import path works, the only diagnostic is `"Last error: ..."`
  in the final `RuntimeError`. There is no record of which path was
  attempted or why.
- Lines 96–119 (`_invoke_model`): tries `predict`, `ocr`,
  `__call__` in turn, each inside `except Exception: continue`. If all
  three fail, raises a generic `RuntimeError("no PaddleOCR-VL method
  accepted the image")`. The actual per-method exceptions are lost.
- Lines 78–94 (`recognize`): wraps the whole call in
  `except Exception as e: return OcrResult(raw_text="", ...,
  extra={"error": str(e)})`. **Failures are converted to empty OCR
  output** rather than raised. Downstream code cannot distinguish
  "model said nothing" from "model crashed".
- Line 152–153 (`_normalize`): when `text_conf` is a bare string
  (no confidence attached), the code assigns `conf = 0.9`. This is a
  fabricated confidence that will pollute Golden Set calibration.
- No call to `OcrBackendInfo` is ever made — `metadata` on the
  returned `OcrResult` is empty. There is no `model_repo`, no
  `model_revision`, no `load_duration_s`, no `inference_duration_s`,
  no `raw_output_path`. The provenance chain is broken.
- No verification that the loaded model is actually
  `PaddlePaddle/PaddleOCR-VL`. The constructor accepts `model_name`
  but never uses it to verify identity at load time.

### 1.3 MLX backend is NOT PaddleOCR-VL

`src/writeup2md/ocr/mlx_backend.py` loads
`mlx-community/paligemma-3b-mix-224-8bit` — a different VLM
(PaliGemma 3B, 8-bit quantized). Calling the MLX backend
"PaddleOCR-VL" or letting `auto` fall through to it as a
"PaddleOCR-VL substitute" would be incorrect.

### 1.4 `doctor` smoke test uses `auto`, which is RapidOCR

`src/writeup2md/doctor.py:171–236` (`smoke_ocr`) calls
`get_backend("auto")`. In this environment that returns
`RapidOcrBackend`. A user running `doctor --smoke-ocr` believes
they are testing "the OCR backend"; in reality they are testing
RapidOCR. There is no way to smoke-test PaddleOCR-VL specifically.

### 1.5 `evaluate-ocr` does not verify model identity

`src/writeup2md/evaluate.py` accepts a `backend_name` string and
passes it to `get_backend`. It records the resulting `backend` and
`backend_version` in `summary.json`, but never asserts that the
backend actually loaded `PaddlePaddle/PaddleOCR-VL` at a specific
commit. A run with `--backend paddle` today would silently produce
empty output (since PaddleOCR is not installed, the adapter's
`recognize` returns `OcrResult(raw_text="", extra={"error": ...})`),
and the evaluator would score that as 0% accuracy without flagging
the underlying load failure.

### 1.6 `OcrBackendInfo` lacks identity fields

`src/writeup2md/ocr/metadata.py`:

```python
@dataclass
class OcrBackendInfo:
    backend: str
    backend_version: str
    model_name: str
    device: str
    engine_version: dict[str, str] = ...
    load_duration_s: float = 0.0
    inference_duration_s: float = 0.0
    input_dimensions: tuple[int, int] | None = None
    preprocessing_used: list[str] = ...
    retry_used: bool = False
    raw_output_path: str | None = None
    is_mock: bool = False
```

Missing: `model_repo`, `model_revision` (commit SHA),
`pipeline_version` (full vs element), `full_pipeline` (bool),
`mock_used`, `rapid_used_as_primary`, `fallback_used`. Without these,
the production-readiness gates (exact-model identity, no silent
fallback, no RapidOCR-as-primary) cannot be verified from
`diagnostics.json` alone.

### 1.7 `pyproject.toml` is missing extras and markers

- No `paddleocr-vl` extra exists. The `paddle-ocr` extra points at
  `paddleocr>=2.6` but does not pull in `paddlepaddle` or
  `huggingface_hub` or `transformers` — all of which are required
  for either runtime mode.
- No `real_paddleocr_vl` test marker. Only `real_ocr` exists, and
  that marker is also satisfied by RapidOCR-only tests, which would
  mask a regression where PaddleOCR-VL stops working.
- `all` extra does not include PaddleOCR-VL dependencies.

### 1.8 Environment inventory (verified 2026-06-20)

| Package | Status | Version |
| --- | --- | --- |
| `huggingface_hub` | installed | 0.36.2 |
| `transformers` | installed | 4.57.6 |
| `torch` | installed | 2.12.0 |
| `PIL` | installed | 12.2.0 |
| `numpy` | installed | 2.4.6 |
| `rapidocr_onnxruntime` | installed | (no `__version__`) |
| `mlx` | installed | (unknown) |
| `mlx_vlm` | installed | 0.3.9 |
| `paddle` (PaddlePaddle) | **NOT INSTALLED** | — |
| `paddleocr` | **NOT INSTALLED** | — |
| `paddleocr_vl` | **NOT INSTALLED** | — |

Python 3.12.7 on macOS 15.7.3 arm64.

**Implication**: Path A (full official pipeline via `paddleocr`) is
blocked until `paddlepaddle` + `paddleocr` are installed. PaddlePaddle
3.3.1 is the latest release on PyPI; on Apple Silicon it runs on CPU
under Rosetta-free arm64 wheels. Path B (MLX-VLM) is not applicable —
MLX-VLM cannot run arbitrary HuggingFace transformers models with
custom_code; it would require a separate MLX-format checkpoint that
does not exist for PaddleOCR-VL. Path C (HF element mode via
`transformers` + `torch` MPS) is viable with the already-installed
`transformers 4.57.6` + `torch 2.12.0` + `huggingface_hub 0.36.2`.

## 2. Plan

The plan, in execution order, is:

1. **Extend `OcrBackendInfo`** with `model_repo`, `model_revision`,
   `pipeline_version`, `full_pipeline`, `mock_used`,
   `rapid_used_as_primary`, `fallback_used`. Existing callers that
   ignore the new fields keep working (additive change).
2. **Create `src/writeup2md/ocr/model_identity.py`** with
   `verify_model_identity(repo, revision)` using
   `huggingface_hub.model_info()` / `snapshot_download()` to resolve
   and pin an immutable commit SHA. Caches the SHA in process memory.
3. **Rewrite `src/writeup2md/ocr/paddleocr_vl.py`** as the strict
   full-pipeline backend (`paddleocr-vl`). Removes every silent
   `except: continue`. Verifies model identity on first load. Raises
   on any failure. Records full `OcrBackendInfo`. Preserves raw output
   to disk.
4. **Create `src/writeup2md/ocr/paddleocr_vl_element.py`** as the
   element-mode backend (`paddleocr-vl-element`) using
   `transformers.AutoModelForImageTextToText` +
   `AutoProcessor`, `trust_remote_code=True`, `do_sample=False`,
   MPS device on Apple Silicon. Same identity verification, same
   raw-output preservation.
5. **Update `backend.py`**:
   - `_resolve_auto()` prefers `paddleocr-vl` > `paddleocr-vl-element`
     > `rapid` > `mlx`.
   - `get_backend(name, *, require_exact_backend=False)`: when
     `require_exact_backend=True`, raise `BackendIdentityError` if the
     resolved backend is not the requested one (e.g. asking for
     `paddleocr-vl` and falling through to `rapid`).
   - `_instantiate()` accepts the new backend names and aliases
     `paddle` / `paddleocr_vl` / `paddleocr-vl` → full pipeline,
     `paddleocr-vl-element` → element mode.
6. **Update `doctor.py`**: add `--require-paddleocr-vl`,
   `--ocr-backend NAME`, `--require-exact-backend` flags.
   `smoke_ocr()` accepts `backend_name` and `require_exact_backend`.
7. **Update `cli.py`**: accept new backend names in `--ocr-backend`,
   thread `require_exact_backend` through.
8. **Update `pyproject.toml`**: add `paddleocr-vl` extra, add
   `real_paddleocr_vl` test marker, update `all`.
9. **Create `scripts/setup_paddleocr_vl_macos.sh`** documenting the
   Apple Silicon install path.
10. **Add tests** with `@pytest.mark.real_paddleocr_vl`:
    - identity verification (offline, uses cached SHA)
    - no silent fallback when `require_exact_backend=True`
    - `OcrBackendInfo` carries `model_repo` + `model_revision`
    - smoke inference on one Golden Set sample (skipped if backend
      cannot load — never faked)
    - Golden Set evaluation (skipped if backend cannot load)
    - raw output preserved on disk
    - regression: existing `real_ocr` tests still pass
11. **Run acceptance gates**:
    - `python -m pytest` (all existing tests still pass)
    - `python -m pytest -m real_paddleocr_vl` (new tests)
    - `python -m writeup2md doctor --require-paddleocr-vl`
    - `python -m writeup2md evaluate-ocr evaluation/golden/ --backend paddleocr-vl-element --output reports/golden-eval-paddleocr-vl`
    - `python -m writeup2md evaluate-ocr evaluation/golden/ --backend rapid --output reports/golden-eval-rapid` (comparison baseline)
12. **Write reports and update docs**:
    - `reports/TASK_15_COMPLETION.md`
    - `reports/PADDLEOCR_VL_BASELINE.md`
    - `reports/PADDLEOCR_VL_GOLDEN_EVAL.md`
    - `reports/PADDLEOCR_VL_VS_RAPID.md`
    - `reports/PADDLEOCR_VL_MACBOOK_PERF.md`
    - `reports/PADDLEOCR_VL_IDENTITY.json`
    - `reports/PADDLEOCR_VL_TEST_PLAN.md`
    - update `README.md`, `CLAUDE.md`, `docs/04_CLI_SPEC.md`,
      `docs/08_MACBOOK_EXECUTION.md`, `docs/09_REAL_OCR_SETUP.md`
    - update `reports/PROJECT_STATE.md`

## 3. Progress log

| Step | Status | Notes |
| --- | --- | --- |
| 1. Audit | complete | This section. |
| 2. `OcrBackendInfo` extension | pending | — |
| 3. `model_identity.py` | pending | — |
| 4. `paddleocr_vl.py` rewrite | pending | — |
| 5. `paddleocr_vl_element.py` | pending | — |
| 6. `backend.py` auto + require_exact | pending | — |
| 7. `doctor.py` + `cli.py` | pending | — |
| 8. `pyproject.toml` | pending | — |
| 9. macOS setup script | pending | — |
| 10. Tests | pending | — |
| 11. Acceptance gates | pending | — |
| 12. Reports + docs | pending | — |
