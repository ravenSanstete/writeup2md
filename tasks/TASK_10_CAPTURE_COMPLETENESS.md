# TASK_10 — PDF and URL Capture Completeness

## Goal

Audit and improve PDF and URL capture so that:
- native text is preferred over OCR (never both emitted for the same content);
- every visual block in the main content area ends in an explicit state
  (the visual coverage ledger);
- reading order is correct;
- image-to-context placement is correct;
- memory remains bounded;
- provenance identifies PDF page+bbox or URL+DOM location.

## PDF source priority (mandatory)

```text
valid native PDF text
> valid hidden OCR text layer
> embedded source image
> rendered page crop
> whole-page OCR (only as a last resort)
```

Do not OCR a whole page when native text plus targeted visual regions are sufficient.

## URL source priority (mandatory)

```text
DOM pre/code text
> copy-button or clipboard payload
> downloadable raw source
> accessible hidden text
> image OCR
> element screenshot OCR
```

If usable code exists in DOM or clipboard data, do not OCR the rendered code block.

## Visual coverage ledger

Every visual block in the main content area must end in exactly one explicit state:

```text
transcribed
native_text_used
decorative_with_reason
duplicate_with_reference
review_required
failed_with_diagnostic
```

The state and reason are persisted in document JSON and diagnostics. No main-content visual may disappear silently.

## Deliverables

1. `src/writeup2md/adapters/pdf.py` improvements:
   - dedup native text vs OCR text layer (skip OCR text blocks that duplicate native text);
   - multi-column reading order detection (PyMuPDF blocks are already sorted by position; verify and document);
   - scanned-page detection refinements (text-density + image-area ratio);
   - mixed scanned/native page handling (process native blocks then render only the scanned image regions);
   - sequential page release verified;
   - multiple visual regions per page supported (already supported — verify);
   - fallback to page-region rendering only when embedded extraction is insufficient.
2. `src/writeup2md/adapters/url.py` and `src/writeup2md/dom_extract.py` improvements:
   - lazy-loaded image handling: scroll + wait for `networkidle` (already); also capture `data-src`, `srcset`, `picture/source`, `currentSrc`;
   - copy-button / clipboard payload extraction (`<button>` with `data-copy`, `onclick` clipboard APIs);
   - hidden accessible code extraction (`<code aria-hidden="true">` siblings, `<pre>` with `display:none` text);
   - content-image vs decorative classification (size, alt, classes, position);
   - DOM-code-over-OCR priority: when a `<pre><code>` block exists, do NOT also create a visual block for its screenshot.
3. `src/writeup2md/models.py` — extend `EnrichedVisual` (or `Block.extra`) with a `coverage_state` field and `coverage_reason`. Additive only — backward compatible.
4. `src/writeup2md/quality.py` and `diagnostics` — surface the coverage ledger in `diagnostics.json` so the UI can show it.
5. Capture test corpus under `tests/fixtures/capture/`:
   - native PDF (existing `tests/fixtures/pdf/writeup.pdf` reused);
   - a synthetic scanned PDF (rendered image-only) — generated for tests;
   - a synthetic mixed PDF (some native pages, some scanned);
   - multi-column PDF — generated;
   - static HTML with code blocks (existing `tutorial.html` reused);
   - HTML with copy-button code blocks;
   - HTML with lazy-loaded images (`data-src`);
   - HTML with native code + code screenshot (DOM priority test);
   - HTML with decorative + content images mixed.
6. Tests in `tests/unit/` and `tests/integration/`:
   - native text not duplicated by OCR layer;
   - DOM code preferred over visual;
   - decorative images classified with reason;
   - all main-content visuals have explicit coverage state;
   - provenance includes page+bbox or DOM selector.

## Acceptance gates

- `python -m pytest` passes (≥180 tests, plus new ones added).
- No duplicate native text + OCR text on any fixture.
- DOM code blocks do not produce a duplicate visual block.
- Every visual block in the test corpus has an explicit `coverage_state`.
- Provenance identifies PDF page+bbox or URL+DOM location.
- Memory remains bounded (no whole-PDF retention; no corpus-wide image preload).
- PDF pages and browser pages are released in `finally` blocks.
