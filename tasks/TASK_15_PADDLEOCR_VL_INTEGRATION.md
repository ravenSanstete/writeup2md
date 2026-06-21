# TASK_15 — PaddleOCR-VL Integration

> Status: P0. In progress.
>
> Source of truth: `reports/PADDLEOCR_VL_INTEGRATION.md` (live audit
> and progress log).

## Goal

Make `PaddlePaddle/PaddleOCR-VL` (commit
`baee27eebcbf26cdeab160116679d765f13a3f27`) the verified production
OCR backend for `writeup2md`. Eliminate every silent fallback to
RapidOCR-as-primary. Make every inference traceable to the exact
model repo and commit. Preserve raw model output on disk for audit.

## Non-goals

- Do NOT replace PaddleOCR-VL with PaddleOCR-VL-1.5 or 1.6 or any
  other model.
- Do NOT claim RapidOCR is PaddleOCR-VL.
- Do NOT silently fall back from `paddleocr-vl` to `rapid` when the
  user asked for `paddleocr-vl`.
- Do NOT do unrelated Round 3 improvements.
- Do NOT invent confidence values when the model does not provide
  them.

## Deliverables

### Code

1. `src/writeup2md/ocr/metadata.py` — extend `OcrBackendInfo` with
   `model_repo`, `model_revision`, `pipeline_version`,
   `full_pipeline`, `mock_used`, `rapid_used_as_primary`,
   `fallback_used`. Additive — no existing field removed.
2. `src/writeup2md/ocr/model_identity.py` (new) —
   `verify_model_identity(repo, revision=None)` resolves and pins an
   immutable HuggingFace commit SHA via
   `huggingface_hub.model_info()` / `snapshot_download()`. Caches
   the SHA in process memory. Raises `ModelIdentityError` on
   mismatch.
3. `src/writeup2md/ocr/paddleocr_vl.py` — rewrite as the strict
   full-pipeline backend `paddleocr-vl`. No silent `except`
   swallowing. Verifies identity on first load. Records full
   `OcrBackendInfo`. Preserves raw output to disk.
4. `src/writeup2md/ocr/paddleocr_vl_element.py` (new) — the
   element-mode backend `paddleocr-vl-element` using
   `transformers.AutoModelForImageTextToText` + `AutoProcessor`,
   `trust_remote_code=True`, `do_sample=False`, MPS on Apple
   Silicon. Same identity + raw-output contract.
5. `src/writeup2md/ocr/backend.py` — `_resolve_auto()` prefers
   PaddleOCR-VL; `get_backend(name, *, require_exact_backend=False)`
   raises `BackendIdentityError` on mismatch; new backend names
   registered.
6. `src/writeup2md/doctor.py` — add `--require-paddleocr-vl`,
   `--ocr-backend NAME`, `--require-exact-backend` flags;
   `smoke_ocr()` accepts `backend_name` + `require_exact_backend`.
7. `src/writeup2md/cli.py` — accept new backend names in
   `--ocr-backend`; thread `require_exact_backend`.
8. `pyproject.toml` — add `paddleocr-vl` extra; add
   `real_paddleocr_vl` marker; update `all`.
9. `scripts/setup_paddleocr_vl_macos.sh` (new) — Apple Silicon
   install path.

### Tests

`tests/real_paddleocr_vl/` with `@pytest.mark.real_paddleocr_vl`:

- `test_model_identity.py` — offline identity check (uses cached SHA).
- `test_no_silent_fallback.py` — `require_exact_backend=True` raises
  when PaddleOCR-VL is unavailable.
- `test_metadata_fields.py` — `OcrBackendInfo` carries `model_repo`
  + `model_revision` + `full_pipeline`.
- `test_smoke_inference.py` — one real inference on a Golden Set
  sample. Skipped (not faked) if backend cannot load.
- `test_raw_output_preservation.py` — raw output written to disk.
- `test_golden_eval.py` — Golden Set evaluation. Skipped if backend
  cannot load.

### Reports

- `reports/PADDLEOCR_VL_INTEGRATION.md` — audit + progress (live).
- `reports/TASK_15_COMPLETION.md` — final completion report.
- `reports/PADDLEOCR_VL_BASELINE.md` — backend capability baseline.
- `reports/PADDLEOCR_VL_GOLDEN_EVAL.md` — Golden Set results.
- `reports/PADDLEOCR_VL_VS_RAPID.md` — head-to-head comparison.
- `reports/PADDLEOCR_VL_MACBOOK_PERF.md` — MacBook performance.
- `reports/PADDLEOCR_VL_IDENTITY.json` — resolved repo + SHA.
- `reports/PADDLEOCR_VL_TEST_PLAN.md` — test plan.

### Docs

- `README.md` — backend table updated.
- `CLAUDE.md` — in-scope + completion definition updated.
- `docs/04_CLI_SPEC.md` — new flags documented.
- `docs/08_MACBOOK_EXECUTION.md` — PaddleOCR-VL resource profile.
- `docs/09_REAL_OCR_SETUP.md` — install + verification steps.

## Acceptance gates (hard)

| # | Gate | Verification |
| --- | --- | --- |
| 1 | Model identity is exact | `reports/PADDLEOCR_VL_IDENTITY.json` records `repo=PaddlePaddle/PaddleOCR-VL`, `sha=baee27eebcbf26cdeab160116679d765f13a3f27`. |
| 2 | No silent fallback | `get_backend("paddleocr-vl", require_exact_backend=True)` raises `BackendIdentityError` when PaddleOCR-VL unavailable, never returns RapidOCR. |
| 3 | `auto` prefers PaddleOCR-VL | `available_backends()` order puts PaddleOCR-VL first; when installed, `auto` resolves to `paddleocr-vl`. |
| 4 | `doctor --require-paddleocr-vl` exits nonzero when unavailable | Verified locally. |
| 5 | `OcrBackendInfo` carries identity | Every inference records `model_repo`, `model_revision`, `pipeline_version`, `full_pipeline`. |
| 6 | Raw output preserved | Every inference writes raw model output to disk; `raw_output_path` set. |
| 7 | Golden Set evaluation runs | `evaluate-ocr --backend paddleocr-vl-element` produces `summary.json` + `results.jsonl`. |
| 8 | Existing tests still pass | `python -m pytest` green. |
| 9 | Real PaddleOCR-VL tests run or skip cleanly | `python -m pytest -m real_paddleocr_vl` either runs (when backend available) or skips with a clear reason (never fails, never fakes). |
| 10 | MacBook constraints upheld | 1 model instance, 1 inference at a time, max 2 workers, no Docker/vLLM/Ray. |
| 11 | No semantic repair | Existing `test_no_semantic_repair` still passes. |
| 12 | Documentation updated | README, CLAUDE, docs/04, docs/08, docs/09 all reflect the new backend names and flags. |

## Blocked execution handling

If PaddleOCR-VL cannot run on this MacBook (e.g. PaddlePaddle wheels
missing for arm64, model download blocked, MPS kernel crash), then:

- The error is preserved in `reports/PADDLEOCR_VL_BASELINE.md` and
  `reports/PROJECT_STATE.md`.
- Path C (element mode via `transformers` + `torch` MPS) is tried as
  the fallback runtime. If Path C also fails, `paddleocr-vl` is
  declared unavailable, `auto` falls through to `rapid`, and
  `doctor --require-paddleocr-vl` exits nonzero with a clear message.
- TASK_15 is **not** declared complete. `reports/PROJECT_STATE.md`
  is set to `BLOCKED_REAL_MODEL_EXECUTION` with the precise blocker.
- The integration code, tests, and reports are still merged so that
  the moment PaddleOCR-VL can run, the acceptance gates can be
  re-tried without re-implementing the adapter.

## Continuous execution

Proceed through every step of the plan in
`reports/PADDLEOCR_VL_INTEGRATION.md` without waiting for approval.
Record assumptions in the completion report. Ask the user only if
progress is impossible without external credentials or a product
decision that would irreversibly contradict this spec.
