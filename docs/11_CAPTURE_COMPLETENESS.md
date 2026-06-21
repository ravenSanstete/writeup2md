# Capture Completeness (TASK_10)

This document covers PDF and URL capture completeness behavior added in
TASK_10. It is the source of truth for source priority orders, the visual
coverage ledger, and the capture test corpus.

## Source priority orders

### PDF

```text
valid native PDF text
> valid hidden OCR text layer
> embedded source image
> rendered page crop
> whole-page OCR (only as a last resort)
```

Implementation in `src/writeup2md/adapters/pdf.py`:

- `page.get_text("blocks", sort=True)` returns position-sorted blocks; we
  classify each as native text or hidden-OCR-layer using span-level
  inspection (`_is_ocr_text_layer_block`).
- `_dedup_native_vs_ocr` drops OCR-layer blocks whose normalized text is
  equal to or a substring of any native block's normalized text. This is
  the explicit dedup rule from the spec: "skip OCR text blocks that
  duplicate native text".
- Whole-page OCR is NEVER invoked by the adapter. A page flagged as
  scanned emits a single `review_required` visual block pointing at the
  rendered page image; OCR is deferred to the enricher.
- Mixed scanned/native page: when a page has both native blocks AND is
  dominated by an image, we emit the native blocks first (in reading
  order), then a single visual block for the scanned image region. The
  page is never wholly OCR'd if native text is present.

### URL

```text
DOM pre/code text
> copy-button or clipboard payload
> downloadable raw source
> accessible hidden text
> image OCR
> element screenshot OCR
```

Implementation in `src/writeup2md/dom_extract.py`:

- For each `<pre><code>` block, the text source is selected in priority
  order: copy-button payload (`data-clipboard-text`, `data-copy`,
  `data-code`, or `onclick` clipboard call) > hidden accessible code
  (`aria-hidden="true"`, `display:none`, `sr-only`, `readonly textarea`)
  > visible `<pre>` text. The chosen source is recorded in
  `block.extra["text_source"]` (`"copy_button"`, `"hidden_accessible"`,
  or `"pre"`).
- DOM-code-over-OCR priority: when a `<pre><code>` block exists, the
  adapter does NOT create a visual block for an inline screenshot of the
  same code. Two detection paths:
  1. If the image is INSIDE the `<pre>/<code>` element, no visual block
     is created (the DOM text is the source of truth).
  2. If the image is a SIBLING that immediately follows a NATIVE_CODE
     block AND its alt-text suggests it's a screenshot of the code
     (e.g. "screenshot of the code", "code block above"), no visual
     block is created.
  In both cases, the image is still recorded in the `images` list for
  provenance auditing.
- Lazy-loaded image handling: the adapter captures `data-src`,
  `data-original`, `data-lazy-src`, `srcset`, `data-srcset`,
  `picture/source` srcset, and (when supplied by the caller)
  `currentSrc`. The URL adapter's image handler calls `img.best_url()`
  which picks `current_src > data_src > picture_src > srcset first > src`.
  `data:` URIs are skipped (they would write massive inline blobs).
- Content-image vs decorative classification: `_is_decorative` returns
  `(True, reason)` for images with class hints (`emoji`, `icon`,
  `avatar`, `logo`, `decoration`, `sprite`, `ad-*`), alt hints, or
  tiny dimensions (≤32×32 CSS px). Decorative images get
  `visual_type=DECORATIVE`, `visual_state=IGNORED_DECORATIVE`, and a
  `decorative_with_reason` coverage state.

## Visual coverage ledger

Every visual block in the main content area ends in exactly one explicit
state. The canonical set is in `src/writeup2md/coverage.py`:

```text
transcribed
native_text_used
decorative_with_reason
duplicate_with_reference
review_required
failed_with_diagnostic
```

`apply_coverage_state(block, state, reason)` sets both
`block.coverage_state` and `block.enrichment.coverage_state` (when
enrichment exists). It validates the state against the canonical set.

`coverage_summary(blocks)` returns a counts dict with `by_state`,
`missing`, and `all_covered` fields. `assert_all_visuals_covered(blocks)`
raises if any visual block lacks both an explicit `coverage_state` AND
a resolvable `visual_state` (`resolved_*`, `ignored_decorative`,
`failed`).

The ledger is surfaced in `diagnostics.json` under the `visual_coverage`
key. The UI can read this to display how every visual was resolved.

## Multi-column reading order

PyMuPDF sorts blocks by position (`sort=True`). We additionally detect
column boundaries via bbox clustering (`_detect_columns`): if blocks
form two distinct horizontal clusters (left and right) at x < 0.8×mid
and x > 1.2×mid, AND their y-ranges overlap significantly, we report
2 columns. The detection is recorded as a `processing_warning` so the
user can verify the reading order is preserved.

## Scanned-page detection

`_extract_page_blocks` returns `(blocks, is_scanned, n_columns)`. A page
is flagged as scanned when:

- text density < 0.01 chars/pixel² AND native text < 20 chars; OR
- native text < 100 chars AND image-area ratio ≥ 0.5 (image dominates
  the page).

The image-area ratio is computed by summing all `get_image_info` bbox
areas and dividing by the page area.

## Capture test corpus

Located at `tests/fixtures/capture/`:

| Path | Type | Purpose |
| --- | --- | --- |
| `native.pdf` | PDF | Native-text PDF — native extraction works. |
| `scanned.pdf` | PDF | Image-only PDF — triggers scanned-page detection. |
| `mixed.pdf` | PDF | Page 1 native, page 2 scanned. |
| `multicolumn.pdf` | PDF | Two-column layout. |
| `copy_button.html` | HTML | `<button data-clipboard-text>` payload. |
| `lazy_load.html` | HTML | `data-src` and `srcset` lazy-loading. |
| `native_plus_screenshot.html` | HTML | `<pre><code>` AND a sibling screenshot — DOM priority. |
| `decorative_mixed.html` | HTML | Emoji, avatar, logo (decorative) + content image. |

PDFs are generated by `tests/fixtures/capture/_gen.py` (PyMuPDF).
