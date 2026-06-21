# TASK_18 — Complete Markdown document compiler

## Goal

Upgrade the renderer from a block dumper to a document compiler
that:

1. produces one ordered block stream with visual transcriptions
   inserted at their original position (never appended at the end);
2. surfaces OCR'd text in document mode even when the confidence
   threshold marked the block `review_required`;
3. reconstructs code / terminal / HTTP / diff blocks as fenced
   Markdown with the correct language tag;
4. guarantees Markdown integrity (no images, no unclosed fences, no
   leaked diagnostics);
5. handles captions and figure references sensibly.

## TASK_16/17 defect findings driving this task

- **D1**: PaddleOCR-VL element mode returns confidence 0.0; the
  TASK_09 threshold model (high=0.99) marks every transcription as
  `review_required`; the renderer emits `<!-- [REVIEW REQUIRED] -->`
  comments instead of the actual OCR text. The Markdown ends up
  empty of OCR'd content even when the OCR was good.
- **D5**: HTML comment markers like
  `<!-- writeup2md: [REVIEW REQUIRED] visual=code block=b_000003 -->`
  leak into user-facing Markdown.
- **D7**: The renderer emits nothing for `failed` or
  `review_required` visuals, so visuals silently disappear from the
  document body.

## Implementation

### 18.A Document mode vs strict mode

Introduce a `mode` field on `WriteupConfig.quality`:

- `document` (default): always produce `document.md`, surface
  uncertain transcriptions with a textual notice.
- `strict`: route uncertain transcriptions to `review_required` and
  allow the document status to be `rejected` or `review`.

`writeup2md convert SOURCE` defaults to document mode.
`writeup2md convert SOURCE --strict` switches to strict mode.

### 18.B Renderer behavior in document mode

For a visual block:

- `resolved_ocr` / `resolved_structured`: emit a fenced code block
  with the OCR'd text and the detected language.
- `ignored_decorative`: emit nothing visible (the visual is
  decorative and was removed).
- `review_required` with non-empty `enrichment.selected_text`:
  emit a textual notice followed by the transcribed text in a fenced
  block. This honors TASK_17.4: "Do not silently omit the content."
- `review_required` with no enrichment (e.g. backend unavailable):
  emit a textual notice that the source contained a visual at this
  position that could not be transcribed.
- `failed`: emit a textual notice naming the failure reason.

No HTML comment markers leak into user-facing Markdown. They remain
available in `document.json` for the review UI.

### 18.C Visual block insertion order

The renderer already sorts blocks by `block.order`. Visual blocks
are inserted at their source position by the PDF / HTML / URL
adapters, so this is already correct. TASK_18 verifies it with an
explicit reading-order test.

### 18.D Code fence language detection

The enricher's `enrichment.language` field is the source of truth.
When that is empty, fall back to:

1. filename or extension in nearby text;
2. visual-type default (terminal→bash, http→http, diff→diff,
   log→log, configuration→ini);
3. `text` when nothing else applies.

### 18.E Markdown integrity

After rendering, the compiler verifies:

- zero `![...](` image syntax;
- zero `<img>` HTML tags;
- zero `data:image/...;base64` URIs;
- even number of triple-backtick fences;
- no fence collision inside code (a literal ``` inside a code block
  is escaped with a longer fence ````);

These checks are recorded in `completeness.json` (TASK_19).

### 18.F Caption handling

When a paragraph block immediately precedes a visual block AND the
paragraph is a single line under 100 chars AND ends with `:` (e.g.
"Run the following command:"), keep it as a lead-in. Do NOT emit
generic "Figure 3" labels as separate paragraphs.

## Acceptance gates

1. `document.md` exists and is non-empty for every processable sample.
2. PaddleOCR-VL transcriptions appear as fenced code blocks (not as
   HTML comment markers).
3. Visual blocks appear in source order.
4. No `<!-- writeup2md:` markers leak into `document.md`.
5. No image syntax, no `<img>`, no base64 URIs.
6. Even number of triple-backtick fences.
7. The renderer can run in `document` mode (default) and `strict`
   mode (`--strict`).
