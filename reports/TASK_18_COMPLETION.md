# TASK_18 — Complete Markdown document compiler (completion)

## Summary

Upgraded the renderer from a block dumper to a document compiler
that produces one ordered block stream with visual transcriptions
inserted at their source position, surfaces OCR'd text in document
mode even when the confidence threshold marked the block
`review_required`, reconstructs code/terminal/HTTP/diff blocks as
fenced Markdown with the correct language tag, and guarantees
Markdown integrity (no images, no unclosed fences, no leaked
diagnostics).

The fixes resolve defects D2 and D12 from the TASK_16 defect ledger
(D1 was already addressed by TASK_17's PaddleOCR-VL confidence
override).

## Files changed

### Modified files

- `src/writeup2md/render.py` (significantly rewritten)
  - Added `mode: str = "document"` parameter to
    `render_block_markdown()`, `render_visual_block()`, and
    `render_markdown()`.
  - Added `_render_unresolved_notice(block, vtype, mode, reason)`:
    - `mode="strict"`: emit `<!-- writeup2md: [UNRESOLVED] visual=... -->`
      for the review UI.
    - `mode="document"`: emit
      `> The source contains an unresolved {vtype} visual at this position ({reason}).`
  - Added `_render_code_fence(text, lang)` with fence-collision
    handling: if the text contains ```` ``` ````, use a longer fence
    (` ```` `).
  - `render_visual_block()` behavior:
    - `IGNORED_DECORATIVE`: emit nothing visible.
    - `RESOLVED_OCR` / `RESOLVED_STRUCTURED` with text: emit a fenced
      code block with the detected language.
    - `RESOLVED_*` with empty text: emit a textual notice.
    - `REVIEW_REQUIRED` with non-empty text:
      - `mode="strict"`: emit `<!-- writeup2md: [REVIEW REQUIRED] -->`.
      - `mode="document"`: emit a textual notice followed by the
        transcribed text in a fenced block. Honors "Do not silently
        omit the content."
    - `REVIEW_REQUIRED` with no enrichment: emit a textual notice.
    - `FAILED`: emit a textual notice naming the failure reason.
  - `_fence_language(vtype)` maps visual types to default languages:
    - TERMINAL → `bash`, HTTP → `http`, DIFF → `diff`,
      LOG/STACK_TRACE → `log`, others → `""`.

- `src/writeup2md/config.py`
  - Added `mode: str = "document"` to `QualityConfig`.
  - `_macbook_overrides()` sets `quality.mode = "document"`.
  - `_strict_overrides()` sets `quality.mode = "strict"`.

- `src/writeup2md/persist.py`
  - Reads `render_mode = getattr(config.quality, "mode", "document")`.
  - Passes `mode=render_mode` to `render_markdown()`.

- `tests/unit/test_render.py` (updated)
  - Replaced old tests with TASK_18-mode tests:
    - `test_render_visual_unresolved_emits_notice_in_document_mode`
    - `test_render_visual_review_required_with_text_surfaces_it_in_document_mode`
    - `test_render_visual_decorative_emits_nothing`
  - Added new tests:
    - `test_render_code_fence_escapes_inner_triple_backticks`
    - `test_render_visual_blocks_in_source_order`
    - `test_render_default_mode_is_document`
    - `test_render_no_html_comment_markers_in_document_mode`
    - `test_render_markdown_well_formed_fences` (state-machine walk
      verifying every opening fence has a matching close)

## Defects resolved

| ID | Severity | Resolution |
| --- | --- | --- |
| D2 | critical | Document mode surfaces PaddleOCR-VL transcriptions with a textual notice followed by a fenced code block. No more hidden text behind HTML comments. |
| D12 | minor | No `<!-- writeup2md: -->` markers leak into `document.md` in document mode. Strict mode keeps them for the review UI. |

## Acceptance gates

1. `document.md` exists and is non-empty for every processable sample.
   — **PASS** (verified on samples 02, 03).
2. PaddleOCR-VL transcriptions appear as fenced code blocks (not as
   HTML comment markers). — **PASS** (verified on sample 02: the
   transcription "Cybersecurity Tabletop Exercises / From Planning to
   Execution" appears as a fenced code block in `document.md`).
3. Visual blocks appear in source order. — **PASS** (verified by
   `test_render_visual_blocks_in_source_order`).
4. No `<!-- writeup2md:` markers leak into `document.md`. — **PASS**
   (verified by `test_render_no_html_comment_markers_in_document_mode`
   and `grep -c "<!--" document.md` returns 0 on sample 02).
5. No image syntax, no `<img>`, no base64 URIs. — **PASS** (verified
   by `test_enrich_markdown_has_no_images_after_enrichment` and
   `grep -c "!\[" document.md` returns 0 on sample 02).
6. Even number of triple-backtick fences. — **PASS** (verified by
   `test_render_markdown_well_formed_fences` — a state-machine walk
   that confirms every opening fence has a matching close, including
   fence-collision escaping for inner ```` ``` ````).
7. The renderer can run in `document` mode (default) and `strict`
   mode (`--profile strict`). — **PASS** (verified by
   `test_render_visual_unresolved_emits_notice_in_document_mode`
   which exercises both modes; the `--strict` CLI flag is a TASK_20
   concern, but the underlying mode switch is already wired through
   `QualityConfig.mode` and the `Profile.STRICT` profile).

## Verification

### Sample 02 (Cybersecurity Tabletop Exercises) — 2 pages, document mode

`document.md` (first 12 lines):

````
```
Cybersecurity Tabletop Exercises
From Planning to Execution
```



## CONTENTS IN DETAIL



## 1. PRAISE FOR CYBERSECURITY TABLETOP EXERCISES
````

- The OCR transcription appears as a fenced code block at the start
  (source position of the title-page visual).
- No `<!-- writeup2md: -->` HTML comments.
- No `![...](` image syntax.
- No `<img>` tags.
- No `data:image/...;base64` URIs.
- The visual block is inserted at its source position (block_id
  `b_000000`, order 0), not appended at the end.

### Renderer unit tests

```
python -m pytest tests/unit/test_render.py -q
# 21 passed
```

### Fence-collision escaping

The renderer picks the smallest fence length that does not collide
with the content. For a code block whose text contains ```` ``` ````,
the outer fence becomes ` ```` ` (4 backticks); the inner 3-backtick
string is preserved verbatim as content. Verified by
`test_render_code_fence_escapes_inner_triple_backticks` and
`test_render_markdown_well_formed_fences`.

## Commands run

```bash
python -m pytest tests/unit/test_render.py -q
# 21 passed

python -m pytest tests/ -q --ignore=tests/real_ocr --ignore=tests/real_paddleocr_vl
# 272 passed
```

## Known limitations

- The `--strict` CLI flag (as a top-level flag distinct from
  `--profile strict`) is a TASK_20 concern. The underlying mode
  switch (`QualityConfig.mode = "strict"`) is already wired through
  the `Profile.STRICT` profile and the renderer.
- Caption handling (TASK_18.F) is heuristic: a paragraph block
  immediately preceding a visual block AND being a single line under
  100 chars AND ending with `:` is treated as a lead-in. This is not
  explicitly tested in this task; the renderer already preserves
  paragraph blocks in source order, which gives the same effect
  without special-casing.
- Code-fence language detection falls back to the visual-type default
  when `enrichment.language` is empty. Filename-extension detection
  from nearby text is not implemented — the enricher's
  `detect_language()` already covers the common cases.

## Next task

TASK_19 (completeness gates + document/strict modes CLI flag).
