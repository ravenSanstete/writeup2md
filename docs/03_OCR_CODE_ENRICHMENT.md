# OCR and Code Enrichment

## Core decision

Use PaddleOCR-VL 0.9B as the primary visual-recognition model. Wrap it behind an internal interface so model version and execution backend can change without changing the IR or CLI.

## Recognition policy

Do not send an entire document to OCR by default. OCR only unresolved visual regions after native extraction and visual classification. Load one model instance and serialize inference on the MacBook-safe profile.

## Processing stages

1. Preserve the original region.
2. Detect whether the region is multi-panel.
3. Crop non-content chrome where safe.
4. Generate optional recognition views: original, upscaled and contrast-enhanced.
5. Run PaddleOCR-VL.
6. Classify output semantics.
7. Apply deterministic post-processing.
8. Compute confidence and review status.
9. Record all transformations.

## Semantic handling

### Code

- preserve visible line breaks and indentation;
- remove line numbers only when clearly part of editor chrome;
- detect language from context and syntax evidence;
- emit one fenced code block.

### Terminal

- detect shell prompts;
- separate commands and outputs when reliable;
- preserve output verbatim;
- never execute recognized commands.

### HTTP

- preserve request line, headers, blank line and body;
- use an `http` fenced block;
- do not normalize payloads or headers.

### Diff

- preserve `+`, `-`, context and hunk markers;
- use a `diff` fenced block.

### Configuration

- preserve indentation exactly;
- identify YAML, JSON, TOML, INI or shell where possible;
- do not repair malformed source text.

## Confidence

Confidence must combine more than model confidence. Suggested signals:

- OCR confidence;
- line completeness;
- indentation stability;
- balanced-delimiter signal;
- language-parser error ratio;
- crop completeness;
- context consistency.

Syntax parsers are diagnostic only. Parser failure must not trigger automatic repair.

## Unresolved visuals

An important visual with insufficient confidence must become `review_required`. In strict mode, the document cannot be accepted until it is resolved.

## MacBook execution constraints

- Initialize the model lazily and reuse it.
- Keep maximum concurrent inference at one.
- Never load a model per document worker.
- Process visual regions incrementally and release image objects after writing results.
- Use a small mock backend for most automated tests; keep real-model tests optional and explicitly marked.
- Prefer a 200 DPI initial render and selectively retry low-confidence regions at up to 300 DPI.

## Implementation status (TASK_04)

- `src/writeup2md/ocr/backend.py` — `OcrBackend` protocol, `OcrResult`/`OcrRegion` dataclasses, module-level singleton with `_INSTANCE_LOCK` and `_INFERENCE_LOCK`. `get_backend(name)` reuses one instance per process; `acquire_inference_lock()` serializes inference.
- `src/writeup2md/ocr/mock.py` — deterministic `MockOcrBackend` that looks up results by content hash. Empty registry returns empty results (never fakes success).
- `src/writeup2md/ocr/paddleocr_vl.py` — real `PaddleOcrVlBackend` that loads PaddleOCR-VL lazily on first `recognize`, tries multiple import paths and invocation methods, and normalizes the model output defensively. Raises a clear actionable error if the model is unavailable.
- `src/writeup2md/ocr/router.py` — visual classification from context (alt/title, surrounding text) and from OCR text (HTTP/diff/terminal/traceback/log/yaml/json/ini). Language detection.
- `src/writeup2md/ocr/postprocess.py` — conservative line-number stripping, line-ending normalization, terminal command/output splitting, trailing-whitespace trimming. Never repairs or invents content.
- `src/writeup2md/ocr/enricher.py` — walks document blocks, enriches unresolved visuals, records `EnrichedVisual`, sets `resolved_ocr` / `review_required` / `failed` / `ignored_decorative` states. Surfaces a warning when the backend is unavailable (never fakes success).
- `src/writeup2md/persist.py` — `finalize_document` calls the enricher before quality gates so resolved visuals can flip the status to `accepted`.
- CLI: `convert --ocr-backend mock|paddleocr_vl` and `doctor --ocr-smoke` for explicit real-model validation.

Confidence combines model confidence plus a small structural bonus for clean terminal splitting. Below 0.6 → `review_required`; below 0.85 → `review_required`; at or above 0.85 → `resolved_ocr`.
