# TASK_17 — Visual asset recovery

## Goal

Every visible main-content visual in a PDF or webpage must end with
one explicit final state. No visual may disappear silently.

For PDF sources, the recovery ladder is:

```
1. embedded source image
2. image xref extraction
3. vector region rasterization
4. page rendering plus region crop
5. whole-page rendering only when targeted extraction is impossible
```

For URL and HTML sources:

```
1. already captured network-response bytes
2. browser currentSrc
3. src
4. data-src
5. srcset / picture source
6. download with browser-context cookies, Referer, headers
7. data URI decoding
8. blob URI extraction in page context
9. inline SVG extraction
10. external SVG download
11. SVG rasterization
12. canvas export
13. CSS background-image extraction
14. locator screenshot
15. full-page screenshot plus DOM bounding-box crop
```

The PDF path is the priority for this round because `test_samples/`
contains 7 PDF books and no HTML/URLs.

## TASK_16 defect findings driving this task

- **D2**: PDF adapter treats every embedded raster image as a
  `review_required` visual block, including book cover art, photos,
  publisher logos. The PaddleOCR-VL backend then hallucinates
  ("I am the world", runs of "0"s) on these huge non-code images.
- **D3**: OCR on huge (4387×2784) images takes minutes per image and
  produces garbage. The VLM was not trained on multi-megapixel images.
- **D1**: PaddleOCR-VL element mode returns confidence 0.0 because
  the VLM does not produce per-region scores. The TASK_09 confidence
  threshold (0.99) then marks every transcription as `review_required`
  and the renderer hides the text. This is a TASK_18 renderer issue
  but it shares root cause with how we treat VLM results.

## Implementation

### 17.A PDF visual classification

Before sending any PDF embedded image to OCR, classify it:

1. **Decorative** — large image (> 50% page area) with no nearby
   native text containing code-like tokens (`def`, `class`, `import`,
   `$`, `HTTP/`, `---`, `@@`), AND no caption marker like
   "Figure", "Listing", "Code", "Example". Mark
   `ignored_decorative` and skip OCR entirely.
2. **Photograph / illustration** — image area > 25% of page and the
   page is mostly body text (not a code-heavy page). Mark as
   `described_as_text` and produce a one-line textual placeholder
   that names the page and the image's role.
3. **Code-like visual** — image area < 25% of page AND either the
   surrounding context contains code-like tokens OR the page has
   other native code blocks. Send to OCR.
4. **Scanned page** — page has < 20 chars of native text AND image
   area > 50%. Render the page and send to OCR.

### 17.B Image normalization before OCR

Before sending any image to PaddleOCR-VL element mode:

1. Inspect magic bytes (PNG / JPEG / WebP / TIFF / AVIF / SVG / PDF).
2. If SVG, rasterize via `cairosvg` (or skip if not available).
3. Decode via PIL.
4. If max dimension > 1568 px (the typical training resolution for
   the VLM), downscale preserving aspect ratio so the longest side
   is 1568 px. Save as PNG.
5. Preserve the original asset under `evidence/visuals/<block_id>/original/`.
6. Save the normalized OCR input under
   `evidence/visuals/<block_id>/normalized/`.
7. Send only the normalized input to the OCR backend.

The original is never overwritten. The OCR backend receives only a
sized-appropriate PNG.

### 17.C Persistent evidence

Move PaddleOCR-VL raw output from `/tmp` into the document workspace
atomically. Layout:

```
outputs/<document_id>/evidence/visuals/<block_id>/
├── original/
│   └── <sha>.<ext>
├── normalized/
│   └── input.png
├── candidates/
│   └── original.json     # raw model output, identity, latency
├── selected.json         # the chosen transcription + reason
├── provenance.json       # source page, bbox, extractor path
└── diagnostics.json      # view name, normalization steps, errors
```

The `/tmp` directory may still be used as a scratch space, but
successful inferences must be copied into the workspace before
finalize_document.

### 17.D Explicit visual outcomes

Every visual block in the document body ends with one final state
from the TASK_17.4 list. The state is recorded in
`diagnostics.json` under `visual_coverage` AND in
`document.json`'s `block.visual_state`.

When OCR fails or returns unusable text on a code/terminal/HTTP/diff
visual, the renderer (TASK_18) inserts a textual notice:

```markdown
> The source contains an unresolved terminal screenshot at this position.
> A partial transcription follows:

```text
<transcribed text or empty>
```
```

No image links. No silent omission.

## Acceptance gates

1. SVG input never reaches PaddleOCR-VL element directly.
2. Every main-content visual has one final state in
   `visual_coverage`.
3. `visuals_missing == 0` in every conversion.
4. Original and normalized evidence are stored separately under
   `evidence/visuals/<block_id>/`.
5. Raw OCR JSON survives removal of `/tmp` (copied to workspace).
6. PaddleOCR-VL never receives an image larger than 1568 px on its
   longest side.
7. Decorative PDF images (cover art, photos) are NOT sent to OCR.
8. Book PDFs no longer produce hallucinated transcriptions like
   "I am the world" or runs of "0".
