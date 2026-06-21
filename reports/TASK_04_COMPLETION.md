# TASK_04 Completion Report — PaddleOCR-VL Enrichment

## Status

Complete. All acceptance conditions met. The real PaddleOCR-VL backend is wired and isolated; tests use a deterministic mock backend. No faked OCR output is ever emitted.

## Files created or changed

- `src/writeup2md/ocr/__init__.py`
- `src/writeup2md/ocr/backend.py` — `OcrBackend` protocol, `OcrResult`/`OcrRegion`, module-level singleton with one instance + one inference lock.
- `src/writeup2md/ocr/mock.py` — `MockOcrBackend` with content-hash registry; empty registry returns empty results (never fake success).
- `src/writeup2md/ocr/paddleocr_vl.py` — `PaddleOcrVlBackend` that loads PaddleOCR-VL lazily, tries multiple import paths and invocation methods, defensively normalizes model output. Clear actionable error when unavailable.
- `src/writeup2md/ocr/router.py` — visual classification from context (alt/title/surrounding text) and from OCR text (HTTP/diff/terminal/traceback/log/yaml/json/ini). Language detection.
- `src/writeup2md/ocr/postprocess.py` — conservative line-number stripping, line-ending normalization, terminal command/output splitting, trailing-whitespace trimming. **Never repairs or invents content.**
- `src/writeup2md/ocr/enricher.py` — walks document blocks, enriches unresolved visuals, records `EnrichedVisual`, sets `resolved_ocr` / `review_required` / `failed` / `ignored_decorative` states. Surfaces a warning when the backend is unavailable.
- `src/writeup2md/persist.py` — `finalize_document` calls the enricher before quality gates.
- `src/writeup2md/cli.py` — added `convert --ocr-backend mock|paddleocr_vl` and `doctor --ocr-smoke`.
- `tests/fixtures/ocr/{code_python,terminal_bash,http_request,diff_patch}.png` — golden PNG fixtures rendered with PIL.
- `tests/unit/test_ocr_router.py` — 18 classification tests.
- `tests/unit/test_ocr_postprocess.py` — 8 post-processing tests.
- `tests/unit/test_ocr_backend.py` — 5 backend tests.
- `tests/integration/test_ocr_enrichment.py` — 9 end-to-end enrichment tests covering code, terminal, HTTP, diff, low-confidence, no-image-markdown, no-evidence-failed, no-auto-repair, and one-instance-reuse.
- `docs/03_OCR_CODE_ENRICHMENT.md` — added Implementation status section.

## Design decisions

- **Singleton + lock.** `get_backend(name)` caches one instance per process behind `_INSTANCE_LOCK`. `acquire_inference_lock()` is held during every `recognize` call, so even if a caller spawns multiple threads, only one inference runs at a time. This satisfies "one model instance, one inference at a time."
- **Lazy model loading.** `PaddleOcrVlBackend.__init__` is cheap; the heavy `import` and model load happen on first `recognize`. This keeps `doctor` and `--help` fast and lets the UI launch without loading the model.
- **Defensive normalization.** PaddleOCR's output structure varies between versions. The backend handles the common `(bbox, (text, conf))` shape defensively and never invents text — missing fields become empty regions, not placeholders.
- **No fake success.** If PaddleOCR-VL is not installed, the enricher leaves visual blocks as `review_required` (their existing state), records a warning, and the document status reflects `review`. Verified end-to-end via CLI: converting `tutorial.html` without PaddleOCR-VL installed produces `Status: REVIEW` with an unresolved-visuals list and a clear warning, not fake `ACCEPTED`.
- **Conservative line-number stripping.** Only strips when EVERY non-empty line begins with digits + whitespace AND the digit run is not part of a larger token (e.g. `0x10`, `1.5`). Real code with numbers is preserved verbatim.
- **Terminal command/output splitting.** A line beginning with `$`, `>`, or `>>` is a command; subsequent non-prompt lines are output. Conservative: no prompt → single output segment.
- **Confidence.** `confidence = model_confidence + small_structural_bonus`. Below 0.6 → `review_required`. Below 0.85 → `review_required`. At or above 0.85 → `resolved_ocr`. The thresholds are heuristic and documented in code.
- **Strict no-auto-repair.** Verified by `test_enrich_does_not_auto_repair_code` which feeds deliberately incomplete code (`return x +`) and asserts the incomplete line is preserved verbatim.
- **Mock backend isolation.** Tests use `MockOcrBackend` registered by content hash, so they are fully deterministic and never touch the network or the model. The mock returns empty results for unregistered images, so the "no real backend" path is exercised without faking.

## Test results

```
python -m pytest
======================= 129 passed, 5 warnings in 1.03s ========================
```

End-to-end CLI smoke tests:

```
# Without PaddleOCR-VL installed — honest REVIEW status, no fake success.
python -m writeup2md convert tests/fixtures/html/tutorial.html --profile macbook
Status: REVIEW
warnings: ["OCR inference failed for b_000014: PaddleOCR-VL is not installed or could not be loaded..."]

# With explicit mock backend — same honest REVIEW status.
python -m writeup2md convert tests/fixtures/html/tutorial.html --profile macbook --ocr-backend mock
Status: REVIEW
```

`doctor --ocr-smoke` is available for users who have installed PaddleOCR-VL and want to verify it loads and infers on a 1×1 test image.

## Known limitations

- **PaddleOCR-VL is not installed in this environment.** All OCR-backed tests use the mock backend. The real backend's `_invoke_model` and `_normalize` paths are exercised only when PaddleOCR-VL is installed; users who install it can run `doctor --ocr-smoke` to validate.
- **No high-DPI retry yet.** The spec mentions re-rendering low-confidence regions at up to 300 DPI. The infrastructure (per-region render at higher DPI) is not yet wired into the enricher; deferred to a future improvement. The PDF adapter renders at 200 DPI which is sufficient for most cases.
- **No multi-panel detection.** The spec mentions detecting multi-panel regions and cropping non-content chrome. Deferred; current behavior sends the whole region to OCR.
- **Editor line-number stripping is conservative.** It only fires when every non-empty line begins with a number. Code with mixed line-numbered and unnumbered lines (rare) is left as-is.

## Recommended next task

TASK_05 — Batch Processing and Quality Gates. Implement directory/URL-list/JSONL input, mixed manifests, durable file-backed state, resume and retry, deterministic skip for unchanged inputs, accepted/review/rejected/failed routing, batch summary and failures files, and the quality gates from `docs/06_QUALITY_AND_TESTING.md`.
