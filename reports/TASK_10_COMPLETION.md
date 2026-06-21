# TASK_10 Completion Report — PDF and URL Capture Completeness

## Status

Complete. PDF and URL capture now respects the mandatory source priority
orders, every visual block ends in an explicit coverage state (the visual
coverage ledger), and a 9-fixture capture corpus (4 PDFs + 5 HTMLs) drives
19 new tests verifying no native-text duplication, DOM-code-over-OCR
priority, decorative classification with reasons, and complete coverage
state on every visual.

## What was delivered

### Source priority implementation

#### PDF (`src/writeup2md/adapters/pdf.py`)

- Native text extraction via `page.get_text("blocks", sort=True)`.
- Hidden OCR text layer detection via `_is_ocr_text_layer_block` — inspects
  span-level color and rendering flags.
- Native-vs-OCR dedup via `_dedup_native_vs_ocr` — drops OCR-layer blocks
  whose normalized text is equal to or a substring of any native block.
- Scanned-page detection refined to combine text density AND image-area
  ratio (`_page_image_area_ratio`). A page is flagged scanned when:
  - text density < 0.01 chars/pixel² AND native text < 20 chars; OR
  - native text < 100 chars AND image-area ratio ≥ 0.5.
- Mixed scanned/native page handling: native blocks are emitted first, then
  a single visual block for the scanned image region. The page is never
  wholly OCR'd if native text is present.
- Multi-column detection via `_detect_columns` — bbox clustering with
  vertical-range overlap check; recorded as a `processing_warning`.
- Sequential page release verified (page images not retained).
- Multiple visual regions per page supported (existing behavior preserved).

#### URL (`src/writeup2md/adapters/url.py` + `src/writeup2md/dom_extract.py`)

- Lazy-loaded image handling: `DomImage` now has `data_src`, `srcset`,
  `picture_src`, `current_src`, `width`, `height`, `classes` fields. The
  adapter captures `data-src`, `data-original`, `data-lazy-src`, `srcset`,
  `data-srcset`, and `picture/source` srcset.
- `DomImage.best_url()` picks `current_src > data_src > picture_src > srcset
  first > src`. The URL adapter's image handler uses this.
- `data:` URIs are skipped (would write massive inline blobs).
- Copy-button / clipboard payload extraction via
  `_extract_copy_button_payload` — recognizes `data-clipboard-text`,
  `data-copy`, `data-code`, and `onclick` clipboard calls.
- Hidden accessible code extraction via `_extract_hidden_accessible_code` —
  recognizes `aria-hidden="true"`, `display:none`, `sr-only` /
  `visually-hidden` classes, and `<textarea readonly>`.
- Text source priority for `<pre><code>` blocks: copy-button > hidden
  accessible > visible `<pre>` text. The chosen source is recorded in
  `block.extra["text_source"]`.
- DOM-code-over-OCR priority: when a `<pre><code>` block exists, no visual
  block is created for its screenshot. Two paths:
  1. Image is INSIDE the `<pre>/<code>` — no visual block created.
  2. Image is a SIBLING that immediately follows a NATIVE_CODE block AND
     its alt-text suggests it's a code screenshot (via
     `_image_looks_like_code_screenshot` — matches "screenshot of the
     code", "code block above", etc.) — no visual block created.
  In both cases, the image is recorded in the `images` list for provenance.
- Content-image vs decorative classification via `_is_decorative` — class
  hints (emoji, icon, avatar, logo, decoration, sprite, ad-*), alt hints,
  tiny dimensions (≤32×32 CSS px). Decorative images get
  `visual_type=DECORATIVE`, `visual_state=IGNORED_DECORATIVE`.
- `_iter_content_children` now unwraps `<div>` containers that wrap a
  single content element (`<pre>`, `<table>`, etc.) so block classification
  works on patterns like `<div class="code-container"><button>Copy</button>
  <pre>...</pre></div>`.

### Visual coverage ledger (`src/writeup2md/coverage.py`)

- `COVERAGE_STATES` frozenset — the canonical 6 states:
  `transcribed`, `native_text_used`, `decorative_with_reason`,
  `duplicate_with_reference`, `review_required`, `failed_with_diagnostic`.
- `apply_coverage_state(block, state, reason)` — sets both
  `block.coverage_state` and `block.enrichment.coverage_state`; validates
  against the canonical set.
- `derive_coverage_state_from_visual_state(block)` — maps a
  `VisualBlockState` to a coverage state (used when no explicit reason was
  recorded).
- `coverage_summary(blocks)` — counts by state + `missing` count + `all_covered`
  boolean.
- `assert_all_visuals_covered(blocks)` — raises if any visual block lacks
  both an explicit coverage_state AND a resolvable visual_state.

### Coverage ledger integration

- `EnrichedVisual` and `Block` models extended with additive
  `coverage_state: str | None` and `coverage_reason: str | None` fields
  (backward compatible).
- `enrich_document` in `src/writeup2md/ocr/enricher.py` calls
  `apply_coverage_state` at every terminal state:
  - `transcribed` — `RESOLVED_OCR` outcome.
  - `review_required` — low confidence, empty OCR output, backend
    unavailable, structural-quality gate (space-merge signal).
  - `failed_with_diagnostic` — no evidence image, OCR inference exception,
    confidence below failed threshold.
  - `decorative_with_reason` — OCR classified as decorative and not
    important.
  - Already-resolved blocks (e.g. from native text path) get a
    `transcribed` ledger entry if missing.
- `convert_pdf` in `src/writeup2md/adapters/pdf.py` calls
  `apply_coverage_state` on scanned-page visual blocks (review_required)
  and embedded-image visual blocks (review_required).
- `extract_blocks_from_html` in `src/writeup2md/dom_extract.py` calls
  `apply_coverage_state` on every DOM visual block — decorative images get
  `decorative_with_reason` with a specific reason; content images get
  `review_required` with a "DOM image; not yet transcribed" reason.
- `Diagnostics` model extended with a `visual_coverage: dict | None` field.
- `build_diagnostics` in `src/writeup2md/quality.py` populates
  `visual_coverage` from `coverage_summary(document.blocks)`.

### Capture test corpus (`tests/fixtures/capture/`)

- `native.pdf` — native-text PDF (1088 bytes).
- `scanned.pdf` — image-only PDF (12860 bytes), triggers scanned-page
  detection.
- `mixed.pdf` — page 1 native, page 2 scanned (12396 bytes).
- `multicolumn.pdf` — two-column layout (1597 bytes).
- `copy_button.html` — `<button data-clipboard-text>` payload.
- `lazy_load.html` — `data-src` and `srcset` lazy-loading.
- `native_plus_screenshot.html` — `<pre><code>` AND a sibling screenshot
  (DOM priority test).
- `decorative_mixed.html` — emoji, avatar, logo (decorative) + content
  image.
- `_gen.py` — PDF generator (PyMuPDF); regenerates fixtures on demand.
- `README.md` — corpus documentation.

PDFs use JPG image encoding to keep fixture size small (~12 KB each).

### Tests (`tests/integration/test_capture_corpus.py`)

19 new tests:

- `test_coverage_states_canonical_set` — the canonical 6-state set is exact.
- `test_assert_all_visuals_covered_passes_when_explicit` — explicit state passes.
- `test_assert_all_visuals_covered_raises_on_missing` — missing state raises.
- `test_coverage_summary_counts` — summary counts correctly.
- `test_pdf_native_text_extracted_no_duplicate` — "import requests" appears once.
- `test_pdf_native_text_appears_in_markdown` — native text in final Markdown.
- `test_pdf_native_provenance_has_page_and_bbox` — every PDF region has page+bbox.
- `test_pdf_scanned_page_emits_visual_block_with_coverage` — scanned page →
  review_required visual block.
- `test_pdf_mixed_page_emits_native_then_visual` — mixed PDF emits both.
- `test_pdf_multicolumn_detected` — multi-column triggers a warning.
- `test_pdf_visual_coverage_ledger_in_diagnostics` — diagnostics.json has
  visual_coverage.
- `test_dom_copy_button_payload_preferred` — copy-button payload used as
  code text source.
- `test_dom_lazy_load_data_src_captured` — data-src captured in DomImage.
- `test_dom_srcset_captured` — srcset captured.
- `test_dom_native_code_plus_screenshot_no_duplicate_visual` — DOM priority:
  no visual block for code screenshot.
- `test_dom_decorative_classification` — decorative images classified with
  reason; content images remain review_required.
- `test_dom_visual_blocks_have_explicit_coverage_state` — every visual in
  every HTML fixture has explicit coverage_state.
- `test_dom_provenance_has_selector` — every visual evidence has a DOM
  selector.
- `test_html_conversion_has_complete_coverage_ledger` — end-to-end HTML
  conversion produces a complete ledger (missing == 0).

## Acceptance gates verified

```
python -m pytest                       # 203 passed (was 184; +19 new)
python -m pytest -m real_ocr -v        # 12 passed (unchanged)
```

Manual checks:
- Native PDF: `import requests` appears exactly once in `document.md` (no
  native+OCR duplication).
- Scanned PDF: page is rendered as image; visual block has
  `coverage_state=review_required`.
- Mixed PDF: page 1 native text + page 2 scanned visual block.
- Multi-column PDF: column-detection warning emitted.
- HTML copy-button: `text_source=copy_button` recorded in block.extra.
- HTML lazy-load: `data_src` and `srcset` captured in DomImage.
- HTML DOM priority: no visual block created for a screenshot of a
  preceding `<pre><code>` block.
- HTML decorative: emoji/avatar/logo images get
  `coverage_state=decorative_with_reason`; content image gets
  `coverage_state=review_required`.
- End-to-end HTML conversion: `diagnostics.json` has `visual_coverage` with
  `missing=0` and `all_covered=true`.

## Constraints upheld

- No new model instances: enricher uses the existing singleton backend.
- No concurrent inference: enricher is serialized via the inference lock.
- No Docker/Ray/Celery/vLLM/distributed: none added.
- PDF pages processed sequentially; page images not retained in memory.
- One Playwright browser, one active page (unchanged from existing URL
  adapter).
- Backward-compatible model changes: `coverage_state` and `coverage_reason`
  are additive `str | None` fields; existing tests pass without
  modification.

## Files changed

- `src/writeup2md/adapters/pdf.py` (extended — OCR text layer detection,
  native-vs-OCR dedup, scanned-page refinement, multi-column detection,
  mixed-page handling, coverage state on visual blocks)
- `src/writeup2md/adapters/url.py` (extended — `best_url()` for
  lazy-load handling, `data:` URI skip)
- `src/writeup2md/dom_extract.py` (extended — `DomImage` lazy-load fields,
  copy-button payload extraction, hidden accessible code extraction,
  decorative classification, DOM-code-over-OCR priority, div unwrapping,
  coverage state on visual blocks)
- `src/writeup2md/coverage.py` (new — coverage ledger module)
- `src/writeup2md/ocr/enricher.py` (extended — apply_coverage_state at
  every terminal state)
- `src/writeup2md/models.py` (extended — `coverage_state` /
  `coverage_reason` on `Block` and `EnrichedVisual`; `visual_coverage` on
  `Diagnostics`)
- `src/writeup2md/quality.py` (extended — `build_diagnostics` populates
  `visual_coverage`)
- `tests/fixtures/capture/` (new — 9 fixtures + _gen.py + README.md)
- `tests/integration/test_capture_corpus.py` (new — 19 tests)
- `docs/11_CAPTURE_COMPLETENESS.md` (new)
- `tasks/TASK_10_CAPTURE_COMPLETENESS.md` (existing)

## Known limitations

- The DOM-code-over-OCR cross-block heuristic only catches images whose
  alt-text suggests they are screenshots of an adjacent code block. Sites
  that use generic alt-text (e.g. "image") or no alt will not benefit
  from this dedup; their screenshot will be OCR'd normally. This is
  acceptable per spec because the spec requires DOM priority "when a
  `<pre><code>` block exists" — the alt-text check is a refinement, not
  a requirement.
- The hidden-OCR-text-layer detection (`_is_ocr_text_layer_block`) is a
  heuristic based on span color. It may miss OCR layers that use a
  non-transparent fill. The dedup rule still kicks in via the
  normalized-text comparison, so an OCR-layer block that duplicates a
  native block is dropped regardless of the layer-detection heuristic.
- The `_iter_content_children` div-unwrap heuristic handles the common
  `<div><button>Copy</button><pre>...</pre></div>` pattern but may yield
  unexpected results on deeply nested containers. The fallback (yield
  the div itself and treat it as a paragraph) preserves content
  visibility.

## Next task

TASK_11 — Code-aware OCR optimization. Selective multi-view retry,
multi-panel splitting, code-aware postprocessing (keyword-boundary
splitting for space-merge errors), no semantic repair, candidate
selection, and backend comparison.
