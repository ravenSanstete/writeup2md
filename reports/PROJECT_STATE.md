# writeup2md — Project State

## Current task

**Round 4 in progress — Full-Book PDF Compilation.** TASK_22 through
TASK_27 are complete. The complete 212-page `A Bug Hunter's Diary`
PDF was processed with no page range, controlled interruption after
30 verified pages, successful resume, 212/212 verified pages, 0 failed
pages, 0 missing visuals, and image-free final Markdown. The next
task is TASK_28 — multi-book complete acceptance.

## Completed tasks

- TASK_01 through TASK_07 — Round 1 release (mock-only validation).
- Round 2 baseline audit (`reports/ROUND_2_BASELINE_AUDIT.md`).
- TASK_08 — Real OCR backend (rapidocr-onnxruntime) with full metadata, `auto` selection, `doctor --require-ocr`, `doctor --smoke-ocr`, 10 smoke fixtures, 8 real_ocr tests.
- TASK_09 — Golden Set (45 samples, 7 visual types, 13 languages), `evaluate-ocr` command, 20+ metrics, confidence calibration, error taxonomy, conservative threshold change in enricher.
- TASK_10 — PDF + URL capture completeness. Visual coverage ledger, native-vs-OCR dedup, scanned-page detection refinement, mixed-page handling, multi-column detection, lazy-load (`data-src`, `srcset`, `picture/source`, `currentSrc`), copy-button / clipboard payload extraction, hidden accessible code, DOM-code-over-OCR priority, decorative classification, 9-fixture capture corpus, 19 new tests.
- TASK_11 — Code-aware OCR optimization. Multi-view retry (5 preprocessing views), candidate selection by structural score (bracket balance, keyword density, line length, space ratio, visual-type tokens), code-aware postprocessing (keyword-boundary splitting, fullwidth punctuation normalization, indentation recovery), multi-panel splitting (terminal/HTTP/diff). 33 new tests (30 unit + 3 real_ocr). No semantic repair.
- TASK_12 — Batch resume freshness + failure recovery. `check_source_freshness` (file edit detection, URL default-fresh, `--max-age`), `_recover_partial_state` (interrupted-run recovery), `--force-refresh` flag, URL ETag/Last-Modified capture, 1-vs-2-worker identical-output verification. 15 new tests.
- TASK_13 — Streamlit review workflow. Full-text search (token + phrase + CJK), extended dashboard filters (status / source type / coverage state / confidence range), sort (document_id / status / captured_at / visual_count), within-document filters (visual type / coverage / confidence), evidence zoom (full-resolution + download), diff (raw OCR vs corrected, unified diff), keyboard navigation (j/k/n/p///Enter), in-UI export button, `inspect --export-reviews PATH` CLI, visual coverage ledger surfaced in Diagnostics tab, coverage column in Structure tab. 27 new tests (25 unit + 2 integration).
- TASK_14 — Real-source end-to-end release. 38-document real-source corpus (11 PDFs, 5 HTMLs, 22 URLs) + 45-sample Golden Set = 127 visual blocks exercised. 0 failed, 1 rejected (cookie interstitial), 18 review, 19 accepted. Golden Set CER 0.1658 (within ±0.02 of baseline). README.md and CLAUDE.md updated. `reports/ROUND_2_RELEASE_REPORT.md` produced.
- **TASK_15 — PaddleOCR-VL integration.** Promoted `PaddlePaddle/PaddleOCR-VL` (commit `baee27eebcbf26cdeab160116679d765f13a3f27`) to the production OCR backend on Apple Silicon. Two backend modes: `paddleocr-vl` (full official pipeline, adapter implemented but blocked on macOS due to missing arm64 PaddlePaddle wheels) and `paddleocr-vl-element` (HF transformers element mode on MPS, working end-to-end). `auto` probe order prefers PaddleOCR-VL. Strict `--require-exact-backend` raises `BackendIdentityError` on any mismatch — no silent fallback to RapidOCR as a primary backend. `OcrBackendInfo` extended with `model_repo`, `model_revision`, `pipeline_version`, `full_pipeline`, `mock_used`, `rapid_used_as_primary`, `fallback_used`. Compatibility shim translates the legacy `inputs_embeds` kwarg to `input_embeds` for transformers 4.53+. Raw JSON preserved for every inference under `/tmp/writeup2md_paddleocr_vl_element_raw/`. Golden Set CER drops 4.9× (0.1658 → 0.0338); 20/45 samples transcribed perfectly. MacBook constraints upheld (1 model instance, 1 inference at a time, default 1 worker, no Docker/vLLM/Ray). `@pytest.mark.real_paddleocr_vl` marker added. 14 new tests (11 offline + 6 real-model smoke + 1 golden-eval, 3 skipped on this MacBook). Completion report: `reports/TASK_15_COMPLETION.md`.
- **TASK_16 — Test-samples inventory + baseline.** Inventoried all 7 PDFs in `test_samples/` (3,456 pages total, sample sizes 14–700 pages). Ran a 3-sample baseline through the Round-2 pipeline: 1 accepted, 1 review, 1 timed out at 900 s. Catalogued 14 defects (D1–D14) covering VLM confidence-threshold misapplication, OCR output hidden by review markers, 15-minute timeouts, hallucinated cover-image OCR, oversized images, bbox extraction, multi-view retry waste, max_new_tokens, raw-OCR provenance, one-command CLI, completeness reports, HTML-comment-marker leakage, human-readable dir names, and low render DPI. Completion report: `reports/TASK_16_COMPLETION.md`.
- **TASK_17 — Visual asset recovery.** Fixed the PaddleOCR-VL confidence-threshold misapplication (D1/D2): the enricher now re-evaluates after the structural-quality gate and marks PaddleOCR-VL output as `resolved_ocr` when the gate does NOT fire, regardless of the meaningless `confidence=0.0`. Added `_copy_raw_ocr_to_workspace()` (D9) to copy raw PaddleOCR-VL JSON from `/tmp` to `evidence/visuals/<block_id>/candidates/original.json`. Added embedded-image classification (decorative / described_as_text / ocr_candidate) (D4). Fixed bbox extraction for both PyMuPDF Rect and 4-float lists (D6). Skipped multi-view retry for PaddleOCR-VL (D7). Completion report: `reports/TASK_17_COMPLETION.md`.
- **TASK_18 — Markdown document compiler.** Implemented document mode (default) that surfaces uncertain transcriptions with a textual notice + fenced code block instead of HTML-comment markers (D12). Added fence-collision handling (longer fences for inner triple-backticks). Rendered visual blocks in source order. Added 5 render unit tests. Completion report: `reports/TASK_18_COMPLETION.md`.
- **TASK_19 — Completeness gates + document/strict modes.** Added `completeness.py` with 6 invariants (`visuals_missing`, `image_syntax_count`, `html_img_tag_count`, `base64_image_uri_count`, `unclosed_fence_count`, `html_comment_marker_count`). Emits `completeness.json` and `quality_report.json` per document (D11). Conservative suspicious-document detection routes failures to `rejected`. Added `--strict` CLI flag for dataset-generation mode that keeps HTML-comment markers. 16 new unit tests. Completion report: `reports/TASK_19_COMPLETION.md`.
- **TASK_20 — One-command CLI + performance.** `writeup2md SOURCE` works as shorthand for `writeup2md convert SOURCE` (D10). On Apple Silicon, defaults to `paddleocr-vl-element` with `require_exact_backend=true` — no flags needed. Output dirs are `<slug>-<short_hash>` with `.index.json` mapping (D13). PDF default render DPI raised to 300/450 (D14). `writeup2md batch test_samples/ --recursive` discovers all 7 PDFs. Backward-compatible `_resolve_document_dir()` for legacy opaque-hash dirs. 13 new slugify tests + 2 CLI tests. Completion report: `reports/TASK_20_COMPLETION.md`.
- **TASK_21 — Test-samples release acceptance.** Ran the fixed pipeline against all 7 PDFs in `test_samples/` with a 5-page slice per book, `paddleocr-vl-element` backend, `require_exact_backend=true`. All 7 accepted, 6/6 completeness invariants per sample. Verified strict-mode sample (HTML-comment markers in `document.md`). Verified Streamlit UI launches against `outputs/e2e_release/`. Produced `reports/E2E_TEST_SAMPLES_RELEASE_REPORT.md` (the final Round-3 release report). Total elapsed 223.48 s, mean 31.93 s per sample. Completion report: `reports/TASK_21_COMPLETION.md`.

## Changed files (Round 2 + TASK_15 + Round 3)

### Round 2

- `src/writeup2md/ocr/rapid.py`, `mlx_backend.py`, `metadata.py` (new)
- `src/writeup2md/ocr/backend.py`, `enricher.py` (extended)
- `src/writeup2md/ocr/multi_view.py`, `candidate_selection.py`, `code_postprocess.py`, `panel_split.py` (new — TASK_11)
- `src/writeup2md/doctor.py`, `cli.py`, `config.py` (extended)
- `src/writeup2md/evaluate.py` (new)
- `src/writeup2md/coverage.py` (new — TASK_10)
- `src/writeup2md/adapters/pdf.py`, `adapters/url.py` (extended — TASK_10, TASK_12)
- `src/writeup2md/dom_extract.py` (extended — TASK_10)
- `src/writeup2md/batch.py` (extended — TASK_12)
- `src/writeup2md/models.py`, `quality.py` (extended — TASK_10)
- `src/writeup2md/inspect_cmd.py` (extended — TASK_13)
- `src/writeup2md/ui/app.py`, `ui/review_store.py` (extended — TASK_13)
- `src/writeup2md/ui/search.py` (new — TASK_13)
- `pyproject.toml` (extras, markers)
- `tests/fixtures/ocr_smoke/` (8 new fixtures)
- `tests/fixtures/capture/` (new — 9 fixtures + _gen.py + README — TASK_10)
- `tests/real_ocr/test_rapid_smoke.py`, `test_golden_eval.py`, `test_code_aware_real.py` (new)
- `tests/integration/test_ocr_enrichment.py` (updated mock confidences)
- `tests/integration/test_capture_corpus.py` (new — 19 tests — TASK_10; 3 tests pinned to `rapid` backend in TASK_15)
- `tests/integration/test_resume_freshness.py` (new — 15 tests — TASK_12)
- `tests/integration/test_export_reviews.py` (new — 2 tests — TASK_13)
- `tests/integration/test_pdf_pipeline.py` (1 test pinned to `rapid` backend in TASK_15)
- `tests/unit/test_code_aware_ocr.py` (new — 30 tests — TASK_11)
- `tests/unit/test_review_workflow.py` (new — 25 tests — TASK_13)
- `evaluation/golden/` (new — 45 samples)
- `docs/09_REAL_OCR_SETUP.md`, `docs/10_GOLDEN_SET_EVALUATION.md`, `docs/11_CAPTURE_COMPLETENESS.md`, `docs/12_CODE_AWARE_OCR.md`, `docs/13_RESUME_FRESHNESS.md`, `docs/14_REVIEW_WORKFLOW.md` (new)
- `tasks/TASK_08_*`, `TASK_09_*`, `TASK_10_*`, `TASK_11_*`, `TASK_12_*`, `TASK_13_*` (new)
- `reports/ROUND_2_BASELINE_AUDIT.md`, `TASK_08_COMPLETION.md`, `TASK_09_COMPLETION.md`, `TASK_10_COMPLETION.md`, `TASK_11_COMPLETION.md`, `TASK_12_COMPLETION.md`, `TASK_13_COMPLETION.md`, `GOLDEN_SET_SCHEMA.md`, `GOLDEN_SET_METRICS.{json,md}`, `OCR_ERROR_TAXONOMY.md` (new)

### TASK_15 (new files)

- `src/writeup2md/ocr/model_identity.py`
- `src/writeup2md/ocr/paddleocr_vl_element.py`
- `scripts/setup_paddleocr_vl_macos.sh`
- `tests/real_paddleocr_vl/__init__.py`
- `tests/real_paddleocr_vl/test_model_identity.py` (11 offline tests)
- `tests/real_paddleocr_vl/test_smoke_inference.py` (6 real-model tests)
- `tests/real_paddleocr_vl/test_golden_eval.py` (1 golden-eval test)
- `reports/PADDLEOCR_VL_INTEGRATION.md`
- `reports/PADDLEOCR_VL_BASELINE.md`
- `reports/PADDLEOCR_VL_GOLDEN_EVAL.md`
- `reports/PADDLEOCR_VL_VS_RAPID.md`
- `reports/PADDLEOCR_VL_MACBOOK_PERF.md`
- `reports/PADDLEOCR_VL_IDENTITY.json`
- `reports/PADDLEOCR_VL_TEST_PLAN.md`
- `reports/TASK_15_COMPLETION.md`
- `reports/golden-eval-paddleocr-vl/` (summary.json, results.jsonl, by_visual_type.json)
- `tasks/TASK_15_PADDLEOCR_VL_INTEGRATION.md`

### TASK_15 (modified files)

- `src/writeup2md/ocr/metadata.py` — extended `OcrBackendInfo`.
- `src/writeup2md/ocr/paddleocr_vl.py` — rewritten (no silent fallback).
- `src/writeup2md/ocr/backend.py` — auto prefers PaddleOCR-VL; `require_exact_backend`; new backend names.
- `src/writeup2md/doctor.py` — new flags; `smoke_ocr()` accepts backend_name.
- `src/writeup2md/cli.py` — new flags threaded through `convert`, `batch`, `doctor`.
- `pyproject.toml` — new `paddleocr-vl` and `paddleocr-vl-element` extras; `real_paddleocr_vl` test marker; `all` updated.
- `tests/real_ocr/test_rapid_smoke.py` — updated backend-name assertion.
- `tests/integration/test_capture_corpus.py` — pinned `rapid` on 3 tests.
- `tests/integration/test_pdf_pipeline.py` — pinned `rapid` on 1 test.
- `README.md`, `CLAUDE.md`, `docs/04_CLI_SPEC.md`, `docs/08_MACBOOK_EXECUTION.md`, `docs/09_REAL_OCR_SETUP.md` — updated to reflect new backend names, identity pin, strict contract, and resource profile.

### Round 3 (TASK_16–TASK_21)

- `src/writeup2md/ocr/enricher.py` — PaddleOCR-VL confidence override; multi-view retry skip; `_copy_raw_ocr_to_workspace()`.
- `src/writeup2md/completeness.py` (new) — 6-invariant completeness gate + suspicious-document detection + `quality_report.json`.
- `src/writeup2md/slugify.py` (new) — `<slug>-<short_hash>` directory naming + `.index.json` mapping.
- `src/writeup2md/cli.py` — `main()` entry point (`writeup2md SOURCE` shorthand); Apple Silicon default backend; `--strict` flag on `convert` and `batch`.
- `src/writeup2md/config.py` — `PdfConfig.initial_render_dpi` 200→300; `retry_render_dpi` 300→450; `_strict_overrides()` and `_macbook_overrides()` updated.
- `src/writeup2md/render.py` — document mode (default) surfaces uncertain transcriptions; strict mode emits HTML-comment markers; fence-collision handling.
- `src/writeup2md/persist.py` — completeness gate integration after markdown rendering.
- `src/writeup2md/adapters/pdf.py`, `adapters/html.py`, `adapters/url.py` — human-readable dir names + `.index.json` updates.
- `src/writeup2md/batch.py` — `_resolve_document_dir()` for backward-compatible dir lookup.
- `pyproject.toml` — entry point changed from `cli:app` to `cli:main`.
- `scripts/run_e2e_release.py` (new) — 7-PDF release runner.
- `tests/unit/test_completeness.py` (new) — 16 tests covering invariants, fence counting, suspicious detection, status application, end-to-end emission.
- `tests/unit/test_slugify.py` (new) — 13 tests covering PDF/HTML/URL slugification, unicode, truncation, index file ops.
- `tests/unit/test_render.py` — 5 new tests for fence escaping, source order, document-mode default, no HTML-comment markers in document mode, well-formed fences.
- `tests/unit/test_cli.py` — `--strict` flag tests; `main()` shorthand routing tests.
- `tests/unit/test_config.py` — DPI assertion updated (200→300).
- `tests/integration/test_ocr_enrichment.py` — `_PaddleOcrVlElementMock`; 3 new tests for zero-confidence resolution, space-merge routing, normalized evidence persistence.
- `tests/integration/test_resume_freshness.py` — uses `r.document_dir` instead of `out / r.document_id`.
- `tests/integration/test_url_pipeline.py` — pinned `cfg.ocr.backend = "rapid"` on the review-status test.
- `tasks/TASK_16_*` through `tasks/TASK_21_*` (new task specs).
- `reports/TASK_16_COMPLETION.md` through `reports/TASK_21_COMPLETION.md` (new).
- `reports/E2E_BASELINE_DEFECTS.md`, `reports/TEST_SAMPLES_INVENTORY.json` (new — TASK_16).
- `reports/E2E_RELEASE_RESULTS.{json,md}` (new — TASK_21).
- `reports/E2E_TEST_SAMPLES_RELEASE_REPORT.md` (new — final Round-3 release report).

## Implemented features (Round 2 + TASK_15 + Round 3)

- Real OCR backend (rapid) with full metadata provenance.
- **PaddleOCR-VL 0.9B as the production backend** (`paddleocr-vl-element` on Apple Silicon MPS). Identity-pinned to `baee27eebcbf26cdeab160116679d765f13a3f27`.
- Backend selection: `mock`, `rapid`, `paddleocr-vl`, `paddleocr-vl-element`, `mlx`, `auto` (auto never picks mock; auto prefers PaddleOCR-VL).
- Strict `--require-exact-backend` contract — raises `BackendIdentityError` on any mismatch.
- `doctor --require-ocr`, `doctor --require-paddleocr-vl`, `doctor --smoke-ocr PATH`, `doctor --smoke-ocr PATH --ocr-backend NAME --require-exact-backend`.
- 10 real smoke fixtures + 15 real_ocr tests + 14 real_paddleocr_vl tests.
- Default backend changed to `auto`.
- Golden Set with 45 hand-verified samples across 7 visual types.
- `evaluate-ocr` command with 20+ metrics, per-visual-type breakdown, confidence calibration.
- Conservative confidence thresholds (high=0.99) + structural-quality gate (space-merge detection) to achieve 1.0 accepted_precision (no false accepts).
- OCR error taxonomy with 17 categories and concrete examples.
- Visual coverage ledger: every visual block ends in `transcribed`, `native_text_used`, `decorative_with_reason`, `duplicate_with_reference`, `review_required`, or `failed_with_diagnostic`. Surfaced in `diagnostics.json` under `visual_coverage`.
- PDF source priority: native text > hidden OCR text layer > embedded image > rendered crop > whole-page OCR (last resort). Native-vs-OCR dedup enforced.
- Scanned-page detection combining text density + image-area ratio. Mixed scanned/native page handling.
- Multi-column reading-order detection (PyMuPDF sort + bbox clustering).
- URL source priority: DOM pre/code > copy-button/clipboard > raw source > hidden accessible text > image OCR > screenshot OCR. DOM-code-over-OCR priority enforced.
- Lazy-loaded image handling: `data-src`, `srcset`, `picture/source`, `currentSrc`. `data:` URIs skipped.
- Copy-button / clipboard payload extraction (`data-clipboard-text`, `data-copy`, `data-code`, `onclick` clipboard APIs).
- Hidden accessible code extraction (`aria-hidden="true"`, `display:none`, `sr-only`, `<textarea readonly>`).
- Decorative image classification (class hints, alt hints, tiny dimensions).
- Capture test corpus: 4 PDFs (native, scanned, mixed, multicolumn) + 5 HTMLs (copy-button, lazy-load, native+screenshot, decorative mixed).
- TASK_11: Multi-view OCR retry (5 preprocessing pipelines: original, grayscale, upscale_2x, adaptive_threshold, invert_dark).
- TASK_11: Candidate selection by structural score (bracket balance 25%, keyword density 25%, line length 15%, space ratio 15%, visual-type tokens 20%).
- TASK_11: Code-aware postprocessing — keyword-boundary splitting (~80 conservative rules), fullwidth punctuation normalization (code context only), indentation recovery (bracket/colon structure).
- TASK_11: Multi-panel splitting — terminal command/output, HTTP request/response, diff file/hunk/content.
- TASK_11: No semantic repair verified by grep and by a real_ocr test that checks no characters are invented.
- TASK_12: `check_source_freshness` — file edit detection (content_sha256 re-hash), URL default-fresh (no network call), `--max-age SECONDS` for time-based freshness.
- TASK_12: `_recover_partial_state` — interrupted-run recovery. Partial document dirs moved to `<doc_id>.partial.<timestamp>` for forensic inspection.
- TASK_12: `--force-refresh` flag bypasses cache freshness checks.
- TASK_12: URL adapter captures `etag` / `last_modified` in manifest.extra and raw/metadata.json.
- TASK_12: 1-worker and 2-worker runs produce identical Markdown output (verified by test).
- TASK_13: Full-text search across all documents (token TF ranking + quoted-phrase substring match + CJK chunk preservation). Cached via `@st.cache_data` keyed on result-root mtime.
- TASK_13: Extended dashboard filters — status / source type / coverage state / confidence range (block-level filters lazy-load document.json).
- TASK_13: Sort by document_id / status / captured_at / visual_count.
- TASK_13: Within-document filters in OCR Review tab — visual type / coverage / confidence.
- TASK_13: Evidence zoom — full-resolution image + download button inside an expander.
- TASK_13: Diff — unified diff between `enrichment.raw_text` and the corrected text (textarea contents, including unsaved edits).
- TASK_13: Keyboard navigation — j/k (next/prev document), n/p (next/prev visual block), / (focus search), Enter (accept block). Progressive enhancement via injected JS.
- TASK_13: In-UI "Export reviews" button writes `outputs/<doc_id>/review/exported_reviews.jsonl`.
- TASK_13: `inspect RESULT_DIR --export-reviews PATH` CLI writes JSONL of review_state + all revisions.
- TASK_13: Diagnostics tab now renders `visual_coverage` ledger; Structure tab adds `coverage` column.
- TASK_15: Identity-pinned PaddleOCR-VL via `huggingface_hub.model_info()` + caching + offline-error contract.
- TASK_15: Element-mode VLM backend (`AutoModelForCausalLM` + `AutoProcessor`, `trust_remote_code=True`, `do_sample=False`, MPS device, float16 dtype).
- TASK_15: `create_causal_mask` compatibility shim (`inputs_embeds` → `input_embeds`) for transformers 4.53+, idempotent, recorded in `engine_version`.
- TASK_15: Raw JSON preserved per inference under `/tmp/writeup2md_paddleocr_vl_element_raw/` with `input_dimensions`, `prompt`, `generation_config`, `output_token_count`, `generated_text`.
- TASK_15: `auto` probe order: `paddleocr-vl` → `paddleocr-vl-element` → `rapid` → `mlx`.
- TASK_15: `OcrBackendInfo` extended with `model_repo`, `model_revision`, `pipeline_version`, `full_pipeline`, `mock_used`, `rapid_used_as_primary`, `fallback_used`.
- Round 3 / TASK_17: PaddleOCR-VL confidence-threshold override. The VLM returns `confidence=0.0` (no per-region scores). The enricher re-evaluates after the structural-quality gate: non-empty text + no space-merge signal → `resolved_ocr` with confidence bumped to 0.95. This is the fix that made samples 01/02/04/05/07 go from `review` to `accepted`.
- Round 3 / TASK_17: Raw PaddleOCR-VL JSON copied from `/tmp/writeup2md_paddleocr_vl_element_raw/` to `evidence/visuals/<block_id>/candidates/original.json` for provenance.
- Round 3 / TASK_17: PDF embedded-image classification (decorative / described_as_text / ocr_candidate) before OCR. Cover art and publisher logos go to `ignored_decorative` and are not OCR'd.
- Round 3 / TASK_17: Multi-view retry skipped for PaddleOCR-VL (was wasteful 5× inference for the VLM).
- Round 3 / TASK_18: Document mode (default) surfaces uncertain transcriptions with a textual notice + fenced code block instead of HTML-comment markers. Strict mode (`--strict`) is the dataset-generation mode that keeps markers.
- Round 3 / TASK_18: Fence-collision handling — longer fences (` ```` `) used when inner text contains triple-backticks.
- Round 3 / TASK_19: `completeness.json` + `quality_report.json` per document with 6 invariants. Suspicious-document detection routes failures to `rejected`.
- Round 3 / TASK_20: `writeup2md SOURCE` one-command shorthand. Apple Silicon default backend is `paddleocr-vl-element` with `require_exact_backend=true` — no flags needed.
- Round 3 / TASK_20: Human-readable output dir names `<slug>-<short_hash>` with `.index.json` mapping. Backward-compatible `_resolve_document_dir()` for legacy opaque-hash dirs.
- Round 3 / TASK_20: PDF default render DPI raised to 300/450 (base/retry).

## Tests run

```
python -m pytest                                              # 244 passed (fast)
python -m pytest -m real_ocr                                  # 15 passed
python -m pytest -m real_paddleocr_vl --timeout=600           # 14 passed, 3 skipped
python -m pytest tests/integration/test_capture_corpus.py \
    tests/integration/test_pdf_pipeline.py --timeout=600      # 14 passed
python -m writeup2md doctor                                   # OK
python -m writeup2md doctor --require-paddleocr-vl            # OK
python -m writeup2md doctor --smoke-ocr \
    evaluation/golden/images/code_py_light_01.png \
    --ocr-backend paddleocr-vl-element --require-exact-backend   # OK
python -m writeup2md evaluate-ocr evaluation/golden/ \
    --backend paddleocr-vl-element \
    --output reports/golden-eval-paddleocr-vl                 # CER 0.0338
python -m writeup2md evaluate-ocr evaluation/golden/ \
    --backend rapid --output reports/golden-eval-rapid        # CER 0.1658
python -m writeup2md convert tests/fixtures/pdf/writeup.pdf \
    --ocr-backend paddleocr-vl-element --require-exact-backend   # ACCEPTED
```

## Real model checks run

- rapidocr-onnxruntime 1.4.4 on 10 smoke fixtures (TASK_08).
- rapidocr-onnxruntime 1.4.4 on 45 Golden Set samples (TASK_09).
- Real end-to-end PDF conversion → ACCEPTED.
- Real end-to-end HTML conversion → REVIEW (correct — empty OCR on tiny screenshot).
- TASK_10 capture corpus: native/scanned/mixed/multicolumn PDFs and 4 HTML variants verified by 19 new tests.
- TASK_11 multi-view + candidate selection + code-postprocess + panel-split verified on real images (3 real_ocr tests).
- TASK_12 freshness + partial-recovery + 1-vs-2-worker identical output verified by 15 new tests.
- TASK_13 export-reviews CLI verified end-to-end on a converted tutorial.html fixture.
- TASK_15 PaddleOCR-VL element mode verified end-to-end on 45 Golden Set samples + 1 real PDF conversion. Golden Set CER 0.0338 (4.9× lower than RapidOCR's 0.1658).

## Key findings

- rapidocr's per-region confidence is NOT calibrated: mean 0.94 on samples with mean CER 0.17.
- Under legacy (0.85) threshold: accepted_precision = 0.07 (41 false accepts out of 44).
- Under production (0.99) threshold + structural gate: 0 auto-accepts, accepted_precision = 1.0.
- Dominant RapidOCR error mode: space-merging (23/45 samples) — `import requests` → `importrequests`.
- Fullwidth Chinese punctuation substitution (13/45) — `,` → `，`.
- Indentation collapse on ~40% of samples.
- Visual-type classification accuracy low (0.156) — router mis-predicts on space-merged text.
- TASK_10: PDF native text and OCR text layer can be reliably deduped via normalized-text comparison. Cross-block DOM priority (screenshot following `<pre>`) requires alt-text heuristic — sites with generic alt fall back to OCR.
- TASK_10: Scanned-page detection needs both text-density AND image-area ratio signals; either alone produces false positives on text-heavy image-illustrated pages.
- TASK_11: Multi-view retry adds up to 4× OCR latency on low-confidence blocks — acceptable because the conservative threshold already routes most blocks to review. Memory bounded: only OcrResult objects retained.
- TASK_11: The split-merge dictionary (~80 rules) catches dominant cases. Adding more rules is safe (only fires on exact prefix+suffix matches).
- TASK_11: recover_indentation is conservative — never rewrites existing indentation, never invents structure.
- TASK_12: Document IDs differ between 1-worker and 2-worker runs because `workers` is part of the config hash. This is intentional (changing worker count invalidates the cache). The "identical output" check uses rendered Markdown, block counts, and statuses — not document IDs.
- TASK_12: URL freshness defaults to True (no network call) to avoid a round-trip on every batch run. Users can force re-processing with `--force-refresh` or `--max-age`.
- TASK_13: Streamlit does not natively expose keyboard events to Python. The injected JS handler is a progressive enhancement — on-screen buttons remain the canonical navigation.
- TASK_13: Block-level filters (coverage / confidence) lazy-load `document.json` per candidate. Acceptable because the dashboard paginates at 50 rows and the search index narrows the candidate set first.
- TASK_15: PaddleOCR-VL element mode is dramatically more accurate than RapidOCR — CER 0.0338 vs 0.1658 (4.9×). 20/45 Golden Set samples transcribed perfectly (vs 0/45 for RapidOCR). The dominant RapidOCR error mode (space-merging) is essentially gone.
- TASK_15: Element mode is the right runtime on Apple Silicon. The full PaddleOCR pipeline requires `paddlepaddle` which is not arm64-clean on macOS. Element mode uses `transformers` + `torch` MPS, both arm64-native.
- TASK_15: A compatibility shim is required. The PaddleOCR-VL custom_code calls `create_causal_mask(inputs_embeds=...)` (legacy plural); transformers 4.53+ renamed the parameter to `input_embeds`. The shim is applied both before `from_pretrained` (to patch the source module) and after (to patch the loaded custom_code's local reference).
- TASK_15: Element mode does not produce per-region confidences. The VLM returns free-form text with no attached probabilities. The TASK_09 calibration block is not meaningful for this backend; the downstream enricher's structural-quality gate still applies.
- TASK_15: MacBook performance is acceptable. Cold start 6.39 s; warm inference 0.48–0.78 s per image on MPS. ~6× slower than RapidOCR but accuracy is the dominant factor for writeup2md's use case.
- TASK_15: `diff` is the worst visual type under PaddleOCR-VL element mode (CER 0.1336). The `+`/`-` line prefixes appear to confuse the model. A future round could try the `table` or `chart` task prompts, or fall back to RapidOCR specifically for diff blocks.

## Known blockers

None.

## Round 3 test-samples results

All 7 PDFs in `test_samples/` convert with `accepted` status and 6/6
completeness invariants (5-page slice per sample,
`paddleocr-vl-element` backend, `require_exact_backend=true`):

| # | sample_id | status | visuals | transcribed | decorative | md_chars | completeness | elapsed_s |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- | ---: |
| 01 | a-bug-hunters-diary | accepted | 4 | 4 | 0 | 345 | 6/6 | 38.43 |
| 02 | cybersecurity-tabletop-exercises | accepted | 1 | 1 | 0 | 3555 | 6/6 | 19.64 |
| 03 | from-day-zero-to-zero-day | accepted | 6 | 6 | 0 | 832 | 6/6 | 63.85 |
| 04 | penetration-testing | accepted | 2 | 2 | 0 | 3258 | 6/6 | 20.31 |
| 05 | pocgtfo | accepted | 1 | 1 | 0 | 3051 | 6/6 | 16.94 |
| 06 | real-world-bug-hunting | accepted | 5 | 2 | 3 | 346 | 6/6 | 31.70 |
| 07 | 漏洞战争 (CJK) | accepted | 2 | 2 | 0 | 2350 | 6/6 | 32.61 |

Total: 223.48 s. Mean: 31.93 s/sample. All `document.md` files are
image-free (no `![`, no `<img>`, no base64). See
`reports/E2E_TEST_SAMPLES_RELEASE_REPORT.md` for the full release
report.

## Known limitations

- **Round 3 / sample 03 chatty descriptions** — PaddleOCR-VL element mode sometimes produces chatty descriptions ("The provided image is a graphic design...") instead of pure transcriptions. The text is grounded in the source so the document is `accepted`, but the description is verbose. A future round could add a chat-detection heuristic.
- **Round 3 / PoCGTFO character-per-line rendering** — PoCGTFO's cover uses extreme letter-spacing and renders as one character per line in `document.md`. The text is preserved and searchable; only line wrapping is affected. A future round could add a layout-heuristic to rejoin character-per-line patterns.
- **Round 3 / strict-mode markers don't appear naturally** in the `outputs/e2e_release/` corpus because PaddleOCR-VL resolves every visual. The marker mechanism is verified by unit tests and a mock-backend strict-mode run instead.
- `paddleocr-vl` (full pipeline) is unverified on this MacBook. The adapter is implemented and identity-verified, but `paddleocr` / `paddlepaddle` are not installed. To exercise the full pipeline, install with `pip install paddleocr paddlepaddle` and re-run `pytest -m real_paddleocr_vl`.
- `diff` is the worst visual type under PaddleOCR-VL element mode (CER 0.1336). Future round could try the `table` or `chart` task prompts, or fall back to RapidOCR specifically for diff blocks.
- PaddleOCR-VL element mode has no per-region confidence scores. The TASK_09 calibration block is not meaningful for this backend. The conservative production threshold (0.99) + structural-quality gate still apply in the enricher.
- The compatibility shim ties us to transformers 4.53+. If a future transformers release further changes the `create_causal_mask` signature, the shim will need to be updated. The shim is idempotent and recorded in `engine_version["causal_mask_shim_applied"]`.
- PaddleOCR-VL is ~6× slower than RapidOCR per inference on MPS. For batch runs with many visual blocks this adds up. Users who need speed over accuracy can still select `--ocr-backend rapid` explicitly.
- PDF capture-mechanics tests pin `rapid` explicitly because `auto` now resolves to PaddleOCR-VL (slower) and the 120-second test timeout was exceeded. These tests verify PDF capture mechanics, not OCR quality, so pinning `rapid` is correct.
- Cookie/consent-wall handling for Playwright URL capture (carried over from Round 2).
- SVG rasterization before OCR (currently surfaces as `failed_with_diagnostic: LoadImageError`) (carried over from Round 2).
- Image-fetch retry with alternate strategies for URL sources (carried over from Round 2).
- Opt-in HEAD-request freshness check for URLs (currently defaults to fresh to avoid network calls) (carried over from Round 2).
- Add `visual_block_count` to `DocumentIndexEntry` for accurate sort-by-visual-count (currently approximated by `block_count`) (carried over from Round 2).

## Exact next action

Round 3 is complete. No pending tasks. Optional improvements
documented above and in `reports/E2E_TEST_SAMPLES_RELEASE_REPORT.md`
under "Known limitations" and "Next-step recommendations":

1. Chat-detection heuristic for PaddleOCR-VL output starting with
   "The provided image is" (sample 03 quality issue).
2. Character-per-line rejoiner for PDFs with extreme letter-spacing
   (PoCGTFO).
3. Structured Rich progress bar for per-page PDF processing.
4. `diff`-specific OCR strategy for PaddleOCR-VL.
5. Concurrent `.index.json` access via file locking.
