# Round 2 Baseline Audit

Date: 2026-06-20

## Purpose

Establish the verified state of the writeup2md project before starting TASK_08 through TASK_14. Distinguish behavior tested only with `MockOcrBackend` from behavior tested with real fixtures, real OCR models, or merely documented. Surface risks that could corrupt Markdown, evidence, provenance, batch state, or human revisions.

## Current test baseline

```
python -m pytest -q
171 passed, 5 warnings in 1.25s
```

The passing count is NOT evidence of real OCR quality. The vast majority of tests run against `MockOcrBackend`.

## Environment reality

### What is actually installed

| Package | Version | Status |
| --- | --- | --- |
| python | 3.12.7 | OK (≥3.11) |
| pydantic | 2.12.5 | OK |
| typer | 0.26.7 | OK |
| rich | (installed) | OK |
| yaml (PyYAML) | 6.0.3 | OK |
| fitz (PyMuPDF) | 1.27.2.3 | OK |
| playwright | (installed) + chromium | OK |
| streamlit | 1.58.0 | OK |
| PIL (Pillow) | 12.2.0 | OK |
| numpy | 2.4.6 | OK |
| rapidocr-onnxruntime | 1.4.4 | **INSTALLED — real OCR available** |
| mlx | 0.31.1 | installed |
| mlx-vlm | 0.3.9 | installed (MLX vision-language stack) |
| paddleocr | (NOT installed) | missing |
| paddle | (NOT installed) | missing |
| paddleocr_vl | (NOT installed) | missing |

### Critical gap

`PaddleOcrVlBackend` in `src/writeup2md/ocr/paddleocr_vl.py` tries `paddleocr` and `paddleocr_vl` import paths. **Neither is installed**. The doctor reports `paddleocr_vl: missing/optional`. As a result, every end-to-end run currently either uses `--ocr-backend mock` (the only working backend) or falls back to leaving visuals as `review_required`. No real OCR has ever been run in this project.

A real OCR engine IS available: `rapidocr-onnxruntime` works on this Mac (verified — loads in ~0.1s, processes `tests/fixtures/ocr/code_python.png` in ~0.8s, returns `[bbox, text, confidence]` tuples per region). `mlx-vlm` is also installed. The Round 2 real backend should target **rapidocr** as the primary real backend (it is the closest equivalent to PaddleOCR-VL that actually runs here, uses ONNX runtime which is Apple-Silicon friendly) and treat `paddleocr_vl` as an optional path that is wired in but cannot be validated on this machine.

## Behavior categorization

### A. Tested only with MockOcrBackend

- `tests/unit/test_ocr_backend.py` — backend instance reuse, inference lock serialization, mock registry.
- `tests/unit/test_ocr_postprocess.py` — line-number stripping, terminal command/output splitting, CRLF normalization.
- `tests/unit/test_ocr_router.py` — context + text classification, language detection.
- `tests/integration/test_ocr_enrichment.py` — enrich_document pipeline (mock-registered text).
- `tests/integration/test_acceptance.py` — 16 acceptance tests, all use `cfg.ocr.backend = "mock"`.
- `tests/integration/test_pdf_pipeline.py` — PDF conversion with mock backend.
- `tests/integration/test_url_pipeline.py` — URL conversion with mock backend.
- `tests/integration/test_batch.py` — batch + resume with mock backend.
- `tests/unit/test_render.py`, `test_quality.py`, `test_dom_extract.py` — pure functions, no OCR.
- `test_raw_evidence_unchanged_after_human_revision` (acceptance) — uses mock OCR for the pipeline but the assertion is about immutability, which is OCR-independent. Validated.

### B. Tested with real PDF / browser fixtures (no OCR)

- `tests/fixtures/pdf/writeup.pdf` — 2-page native PDF. Verified end-to-end via `convert_pdf` → ACCEPTED with mock OCR.
- `tests/fixtures/html/tutorial.html` — local HTML with mixed paragraphs, code blocks, headings, a `login_form.png` image. Verified → REVIEW (because mock OCR is empty).
- `test_pdf_pages_processed_sequentially` (acceptance) — uses real PDF + patched render function, no OCR.
- `test_full_layout_exists_for_each_output` (acceptance) — uses real PDF, no OCR (mock).
- `test_streamlit_launch_does_not_load_ocr_model` (acceptance) — verifies UI isolation by module inspection; no model.

### C. Tested with a real PaddleOCR-VL model

**None.** Zero tests. Zero end-to-end runs. The real backend path in `paddleocr_vl.py` has never executed on this machine.

### D. Documented but not verified

The following claims appear in `docs/` and `reports/` but have NOT been verified against real OCR:

1. `docs/03_OCR_CODE_ENRICHMENT.md` — describes PaddleOCR-VL enrichment. Never run for real.
2. `docs/08_MACBOOK_EXECUTION.md` — claims one model instance and serialized inference. Verified structurally (locks exist) but never under a real model load + real inference contention.
3. `reports/FINAL_IMPLEMENTATION_REPORT.md` — claims "PaddleOCR-VL enrichment is integrated through a replaceable backend". The integration is wired but the real backend has never run.
4. `reports/TASK_04_COMPLETION.md` — TASK_04 was accepted on mock-only tests.
5. README "Quick start" — `writeup2md convert tutorial.pdf --profile macbook` would silently fall back to review_required for every visual because the default backend (`paddleocr_vl`) is missing. The README does not mention this.
6. CLI `--ocr-backend` help string says "paddleocr_vl (default) or mock". On this machine neither paddleocr_vl nor any other real backend is selectable.
7. `doctor --ocr-smoke` uses a 1x1 transparent PNG. That is not a meaningful smoke test — even a working model returns nothing on it. It cannot distinguish a real backend from a mock that returns empty.

### E. Inconsistencies between code, tests, and documentation

1. **Default backend name.** `OcrConfig.backend` defaults to `"paddleocr_vl"` and `get_backend(None)` defaults to `"paddleocr_vl"`. Doctor reports it as missing. So a plain `writeup2md convert` run on this machine produces REVIEW output for every visual without any warning that OCR is unavailable. The enricher records a warning but the CLI does not surface it. **Risk**: user thinks conversion succeeded when nothing was actually OCRed.

2. **Backend name namespace.** `get_backend` accepts `"paddleocr_vl"` and `"paddleocr-vl"`. There is no `auto`, no `rapid`, no `mlx`. The Round 2 spec requires `mock`, `paddle`, `mlx`, `auto`.

3. **`doctor --ocr-smoke` semantics.** The current smoke uses a 1x1 PNG. A real model returns empty for it, indistinguishable from a failure. The spec wants `doctor --smoke-ocr PATH_TO_IMAGE` with real metadata, load time, inference time, raw output path, and a mock-not-used assertion.

4. **`doctor --require-ocr`** does not exist. The spec requires it.

5. **OcrResult schema** has `backend_version: str = ""` and `extra: dict`. It does NOT carry: model name/version separately, paddle/rapidocr version, device, load duration, per-region inference duration, input dimensions, preprocessing/retry flags. The Round 2 spec (TASK_08 2.2) requires all of these to be recorded.

6. **Confidence calibration.** `_HIGH_CONFIDENCE_THRESHOLD = 0.85`, `_LOW_CONFIDENCE_THRESHOLD = 0.6` are hard-coded in `enricher.py`. The Round 2 spec (TASK_09 3.4) demands these be calibrated against real accuracy and that a heuristic score must not be presented as a calibrated probability. There is currently no calibration data, no Golden Set, no `evaluate-ocr` command.

7. **Resume freshness.** `_process_one` in `batch.py` skips when `content_sha256 + config_sha256 + manifest.json` match. For URLs, "content_sha256" is the SHA of the captured HTML. There is no ETag / Last-Modified / TTL / `--force-refresh` / `--max-age`. The Round 2 spec (TASK_12 6.1) requires URL freshness controls.

8. **Visual coverage ledger.** The spec (TASK_10 4.3) requires every visual block to end in one of `transcribed | native_text_used | decorative_with_reason | duplicate_with_reference | review_required | failed_with_diagnostic`. The current `VisualBlockState` enum is close but uses different names (`resolved_ocr`, `ignored_decorative`, `failed`, `review_required`) and does not have `duplicate_with_reference` or `native_text_used`. This is a schema gap, not a regression — but it must be reconciled in TASK_10.

9. **No `evaluate-ocr` command, no Golden Set, no error taxonomy, no performance report.** None of these exist. All required by TASK_09 / TASK_14.

10. **No `writeup2md review export` command.** Spec (TASK_13 7.4) requires it.

11. **Streamlit UI has no full-text search, no language/visual-type/confidence filters, no review-priority sort, no zoom, no diff view, no keyboard shortcuts, no SQLite FTS5 index.** Spec (TASK_13 7.1, 7.2) requires these.

12. **`paddleocr_vl.py` `_invoke_model` swallows every exception per method attempt.** If `predict` and `ocr` both raise, the code falls through to `__call__` and finally raises "no method accepted the image" with no diagnostic. Real backend integration must surface the original errors.

13. **`paddleocr_vl.py` `_normalize`** hard-codes `conf = 0.9` when the result item is a bare string. That is an invented confidence. Real backends must never invent confidence.

14. **`count_image_references` / `render_markdown` strip_images logic** — verified working in TASK_07. No issue, but the Round 2 real-OCR runs will exercise it more.

15. **PIL Image opening in `paddleocr_vl.py`** swallows exceptions and passes `image_bytes` directly to the model when PIL fails. Real backends should fail loudly when given unreadable bytes.

## Risks that could corrupt Markdown, evidence, provenance, batch state, or human revisions

### Markdown corruption risks

- **Silent OCR fallback to empty text.** If a real backend returns empty for a visual block, the enricher currently sets `review_required`. That is safe. But if the backend returns garbage text with high confidence, the block becomes `resolved_ocr` and the garbage lands in `document.md`. There is no syntax-validation gate. **Mitigation**: TASK_11 must add candidate selection with parser diagnostics, and TASK_09 must calibrate confidence thresholds.

- **Editor line-number stripping over-aggressiveness.** `_strip_editor_line_numbers` only fires when EVERY non-empty line begins with digits+whitespace. Safe. But the Round 2 multi-view retry may produce partial outputs where only some lines have numbers; current logic would NOT strip those. **Mitigation**: TASK_11 must handle partial line-number cases.

### Evidence corruption risks

- **`raw/` and `evidence/` immutability** is enforced by code paths that only ever `write_bytes` to new content-hash filenames. `review_store.py` writes only to `review/`. Verified by `test_raw_evidence_unchanged_after_human_revision` (SHA-256 snapshot). Low risk, but the new `--force-refresh` URL path in TASK_12 must NOT delete or overwrite existing evidence directories — it must write to a new document_id (because content_sha256 changes) or refuse if `--force` is unset.

### Provenance corruption risks

- **Provenance record count** must equal final Markdown block count. Verified by `test_provenance_maps_every_block`. Low risk.
- **TASK_11 multi-panel splitting** will add child regions. Each child must produce its own provenance record. **Mitigation**: when splitting, emit one block per child region, each with its own evidence ref and provenance entry.

### Batch state corruption risks

- **`batch_state.json` atomic writes** — uses `atomic_write_json` (tempfile + os.replace). Safe.
- **Two-worker path** copies state by value (`local_state = dict(state)`) then merges under a lock. There is a subtle TOCTOU: worker A reads state, worker B reads state, both process, both merge. Skip decisions could double-execute a source. **Mitigation**: TASK_12 must add a per-source lock or pre-claim step. For now workers=1 (default) avoids this.
- **Resume determinism** — verified by `test_batch_resume_does_not_duplicate_outputs`. But the URL freshness gap (item 7 above) means a stale URL capture is silently reused forever. **Mitigation**: TASK_12.

### Human revision corruption risks

- **`review_store.py` never overwrites raw.** Verified.
- **`set_block_correction`** stores corrections in `review_state.json["corrections"][block_id]`. If block IDs change between runs (e.g. because the document is reprocessed with a different config and block ordering shifts), corrections silently detach from blocks. **Mitigation**: TASK_12 must document that reprocessing creates a new document_id (config_sha is part of the ID), so old review state is preserved under the old ID and never silently reattached.

## Summary of required Round 2 work

| Gap | Task |
| --- | --- |
| Real OCR backend (rapidocr + paddle path + auto + mlx) | TASK_08 |
| `doctor --require-ocr`, `doctor --smoke-ocr PATH` with real metadata | TASK_08 |
| Real smoke-test pack (10+ screenshots, dark/light/terminal/http/config/line-numbers/low-res/command+output/punctuation/indentation) | TASK_08 |
| Golden Set schema + 40+ samples + evaluate-ocr command + metrics + calibration + error taxonomy | TASK_09 |
| PDF capture priority, dedup, multi-column, mixed scanned/native | TASK_10 |
| URL capture priority, lazy-load, copy-button, DOM-over-OCR | TASK_10 |
| Visual coverage ledger state machine | TASK_10 |
| Selective multi-view retry, multi-panel split, code-aware postprocess, no semantic repair, candidate selection | TASK_11 |
| Backend comparison (rapid vs mlx) | TASK_11 |
| Resume freshness (file SHA, config SHA, URL ETag/Last-Modified/TTL/force-refresh/max-age) | TASK_12 |
| State machine recovery, failure cases, concurrency verification | TASK_12 |
| Streamlit full-text search, filters, sort, zoom, diff, keyboard nav | TASK_13 |
| `writeup2md review export / export-all / stats` commands | TASK_13 |
| Real-source corpus (8 PDFs, 12 URLs, 100+ visual blocks, 5+ types) | TASK_14 |
| Final release checks + performance report + ROUND_2_RELEASE_REPORT | TASK_14 |

## Decisions taken before starting

1. **Primary real backend = rapidocr-onnxruntime.** Justification: actually installed, actually runs on this Mac, returns the same `[bbox, text, conf]` shape as PaddleOCR's classic API. We will keep the `paddleocr_vl` adapter as an optional path but cannot validate it on this machine — documented as a known limitation.
2. **Secondary real backend = mlx-vlm.** Available; TASK_11 will compare. May or may not produce usable OCR for code screenshots; if not, documented as a limitation.
3. **Backend names**: `mock`, `rapid`, `paddle`, `mlx`, `auto`. `auto` picks the first available real backend in order `[rapid, paddle, mlx]`. `auto` MUST NOT pick `mock`.
4. **No new schema version bump** unless TASK_10's visual-coverage ledger cannot be expressed as additive `extra` fields. Prefer additive `extra` over enum changes to keep backward compatibility.
5. **Test markers**: `@pytest.mark.real_ocr` and `@pytest.mark.slow` for real-model tests. Default `python -m pytest` skips them. Run with `python -m pytest -m real_ocr`.
6. **No Docker, Ray, Celery, Kubernetes, vLLM, distributed, multi-process, workers>2.** Maintained throughout.
7. **Real source corpus**: 7 real cybersecurity PDFs are in `test_samples/` (legally accessed local copies). The 8th PDF requirement will be met by including `tests/fixtures/pdf/writeup.pdf`. The 12 URLs will come from the kanxue.com thread and other publicly accessible technical writeup pages; where network is unstable we preserve local HTML captures.
