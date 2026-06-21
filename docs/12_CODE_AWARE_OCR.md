# Code-aware OCR optimization (TASK_11)

This document covers the code-aware OCR optimization pipeline added in
TASK_11. The defining constraint is **no semantic repair**: we never
invent, complete, or repair code. All operations are STRUCTURAL only.

## Pipeline

```text
visual block
→ run OCR (single view)
→ postprocess (existing — line-number strip, terminal split, etc.)
→ code-aware postprocess:
    → split_space_merged_tokens (keyword-boundary splitting)
    → normalize_fullwidth_punct (fullwidth → ASCII in code contexts)
    → recover_indentation (bracket/colon structure)
→ if confidence < high threshold OR space-merge signal:
    → run_multi_view (N alternate preprocessing pipelines)
    → select_best by structural_score
    → re-postprocess the winner
→ split_panels (terminal / HTTP / diff)
→ final block state (resolved_ocr or review_required)
```

## Modules

### `src/writeup2md/ocr/multi_view.py`

`preprocess_views(image_bytes) -> list[(view_name, image_bytes)]` produces
up to 5 views:

- `original` — no preprocessing (baseline).
- `grayscale` — luminance-only.
- `upscale_2x` — 2× upscale with LANCZOS.
- `adaptive_threshold` — binarize via blurred-subtract threshold.
- `invert_dark` — invert dark-theme screenshots.

`run_multi_view(backend, image_bytes, max_views=4)` runs OCR on each view
and returns `ViewResult` records with the view name annotated in
`result.extra["view"]`. Memory-bounded: each view is processed and
discarded; only `OcrResult` objects are retained.

### `src/writeup2md/ocr/candidate_selection.py`

`structural_score(text, visual_type) -> float` returns a score in `[0, 1]`
combining:

- bracket balance (25%) — `()`, `[]`, `{}` must be balanced;
- keyword density (25%) — fraction of common keywords present as
  standalone words;
- line length (15%) — penalizes long lines without whitespace;
- space ratio (15%) — penalizes space-merged text;
- visual-type structural tokens (20%) — `HTTP/\\d` for HTTP, `@@` for
  diff, `$`/`>` for terminal, `:`/`;` for code.

`select_best(candidates, visual_type) -> OcrResult | None` picks the
highest-scoring candidate, breaking ties by model confidence then by text
length (capped at 1000 chars to avoid rewarding junk).

### `src/writeup2md/ocr/code_postprocess.py`

`split_space_merged_tokens(text, language) -> (text, transformations)` —
splits clearly-merged tokens at known keyword boundaries. The dictionary
is deliberately conservative: we only split when BOTH the prefix and the
suffix are known keywords/identifiers. Never invents a token boundary.

Examples:
- `importrequests` → `import requests`
- `sudoapt update` → `sudo apt update`
- `Content-Type:application` → no change (the merged form doesn't match
  any rule because `Content-Type:` is already a complete token)

`normalize_fullwidth_punct(text) -> (text, transformations)` — replaces
fullwidth punctuation with ASCII equivalents (`,→,`, `： →:`, `（ →(`,
etc.) ONLY when the text looks like code. Natural Chinese text is left
untouched.

`recover_indentation(text, language) -> (text, transformations)` —
best-effort indentation recovery. After a line ending with `:` (Python)
or `{` (JS/C/Go), the next line gets 4 spaces of indent. Before a line
starting with `}`/`)`/`]`, indent is decreased first. Lines that already
have leading whitespace are NOT re-indented. Empty lines are left empty.

### `src/writeup2md/ocr/panel_split.py`

`split_panels(text, visual_type) -> list[dict]` dispatches to:

- `split_terminal_panels` — command (line begins with `$`/`>`) vs output.
- `split_http_panels` — request_line, request_header, request_body,
  status_line, response_header, response_body.
- `split_diff_panels` — file_header, hunk_header, hunk_content.

Segments are stored in `EnrichedVisual.segments` with `role` and `text`
fields. The panel_split transformation is recorded when splitting
produces >1 segment.

### `src/writeup2md/ocr/enricher.py` (extended)

The enricher integrates all four modules:

1. After the existing `postprocess()`, apply code-aware postprocessing
   (split → normalize → indent).
2. When `result.model_confidence < _HIGH_CONFIDENCE_THRESHOLD` OR
   `_looks_space_merged(pp_selected_text)` fires, run multi-view retry
   with `max_views=4` and pick the best candidate via `select_best`.
3. Apply panel splitting; store segments in `EnrichedVisual.segments`.
4. Apply a small confidence boost (≤0.05) when code-aware postprocessing
   produced transformations — finding structural patterns to fix is a
   positive signal.

## Hard constraint — no semantic repair

This task MUST NOT (and does not):

- look up missing tokens in a language model;
- auto-fix syntax errors;
- complete partial identifiers;
- replace unknown characters with likely substitutes;
- merge or split lines based on language semantics.

Verified by `grep -rE "language_model|predict_missing|repair_code|invent_token|complete_identifier" src/` — no matches.

## Tests

### Unit (`tests/unit/test_code_aware_ocr.py`)

30 tests covering:

- keyword-boundary splitting (5 tests) — including the `importrequests`
  classic case, multiple-keyword text, and the "do not split inside
  identifiers" guard.
- fullwidth punctuation normalization (3 tests) — code context, natural
  Chinese text skip, HTTP header context.
- indentation recovery (4 tests) — Python colon, JS braces, existing
  indentation preserved, empty lines untouched.
- panel splitting (5 tests) — terminal, HTTP, diff, dispatch by visual
  type, no-prompt fallback.
- candidate selection (10 tests) — bracket balance, keyword density,
  line length, space ratio, combined structural score, `select_best`
  picks the balanced candidate, returns None on empty.
- multi-view (2 tests) — preprocess_views produces multiple views,
  run_multi_view with mock backend produces annotated candidates.

### Real OCR (`tests/real_ocr/test_code_aware_real.py`)

3 tests marked `real_ocr`:

- multi-view runs without crashing on a real image;
- candidate selection picks a non-empty result;
- code-aware postprocessing does not damage clean OCR output (the set of
  characters in the output is a subset of the input characters plus ASCII
  punctuation that we may have introduced via normalization).

## Acceptance gates

```
python -m pytest                # 236 passed (was 203; +33 new)
python -m pytest -m real_ocr    # 15 passed (was 12; +3 new)
```

Manual check: `grep -rE "language_model|predict_missing|repair_code|invent_token|complete_identifier" src/` returns no matches — the no-semantic-repair constraint is upheld.

Visual coverage ledger (TASK_10 invariant) preserved — all new
transformations flow through `apply_coverage_state`.

Memory bounded: multi-view processes one view at a time; only
`OcrResult` objects (text + metadata) are retained.

One inference at a time: each `backend.recognize()` call is already
guarded by the inference lock in the backend implementation.
