# TASK_11 Completion Report — Code-aware OCR optimization

## Status

Complete. The OCR pipeline now includes selective multi-view retry, candidate
selection by structural score, code-aware post-processing (keyword-boundary
splitting, fullwidth punctuation normalization, indentation recovery), and
multi-panel splitting (terminal / HTTP / diff). The hard constraint of "no
semantic repair" is upheld — verified by grep and by a real_ocr test that
checks no characters are invented.

## What was delivered

### New modules

- `src/writeup2md/ocr/multi_view.py` — `preprocess_views` produces up to 5
  views (original, grayscale, upscale_2x, adaptive_threshold, invert_dark).
  `run_multi_view` runs OCR on each view and returns ViewResult records
  annotated with the view name. Memory-bounded: each view is processed and
  discarded; only OcrResult objects are retained.
- `src/writeup2md/ocr/candidate_selection.py` — `structural_score` combines
  bracket balance (25%), keyword density (25%), line length (15%), space
  ratio (15%), and visual-type structural tokens (20%). `select_best` picks
  the highest-scoring candidate with tie-breaking by confidence then length.
- `src/writeup2md/ocr/code_postprocess.py` — three structural-only operations:
  - `split_space_merged_tokens` — splits at known keyword boundaries
    (e.g. `importrequests` → `import requests`). Conservative dictionary of
    ~80 rules covering Python imports/defs, bash commands, HTTP, diff.
  - `normalize_fullwidth_punct` — replaces fullwidth punctuation with ASCII
    in code contexts only (natural Chinese text is left untouched).
  - `recover_indentation` — best-effort indentation from bracket/colon
    structure. Lines that already have leading whitespace are NOT re-indented.
- `src/writeup2md/ocr/panel_split.py` — `split_panels` dispatches to
  `split_terminal_panels`, `split_http_panels`, or `split_diff_panels`
  based on visual_type. Returns labeled segments stored in
  `EnrichedVisual.segments`.

### Enricher integration (`src/writeup2md/ocr/enricher.py`)

- After the existing `postprocess()`, apply code-aware postprocessing:
  split → normalize → indent.
- When `result.model_confidence < _HIGH_CONFIDENCE_THRESHOLD` OR
  `_looks_space_merged(pp_selected_text)` fires, run multi-view retry with
  `max_views=4` and pick the best candidate via `select_best`. Re-postprocess
  the winner so panel splitting and transformations are consistent.
- Apply panel splitting; store segments in `EnrichedVisual.segments`.
- Apply a small confidence boost (≤0.05) when code-aware postprocessing
  produced transformations — finding structural patterns to fix is a
  positive signal.
- Visual coverage ledger (TASK_10 invariant) preserved — all terminal
  states still call `apply_coverage_state`.

### Tests

#### Unit (`tests/unit/test_code_aware_ocr.py`) — 30 tests

- Keyword-boundary splitting (5): classic `importrequests` case, multiple
  keywords, "do not split inside identifiers" guard, surrounding-text
  preservation.
- Fullwidth punctuation normalization (3): code context, natural Chinese
  skip, HTTP header context.
- Indentation recovery (4): Python colon, JS braces, existing-indentation
  preservation, empty-line handling.
- Panel splitting (5): terminal command/output, no-prompt fallback, HTTP
  request/response, diff file/hunk/content, dispatch by visual_type.
- Candidate selection (10): bracket balance, keyword density, line length,
  space ratio, combined structural score, `select_best` picks balanced,
  `select_best` returns None on empty.
- Multi-view (2): `preprocess_views` produces multiple views,
  `run_multi_view` with mock backend produces annotated candidates.

#### Real OCR (`tests/real_ocr/test_code_aware_real.py`) — 3 tests

- Multi-view runs without crashing on a real image.
- Candidate selection picks a non-empty result.
- Code-aware postprocessing does not damage clean OCR output — the set of
  characters in the output is a subset of the input characters plus ASCII
  punctuation that we may have introduced via normalization. This is the
  no-semantic-repair invariant, verified empirically.

## Acceptance gates

```
python -m pytest                # 236 passed (was 203; +33 new)
python -m pytest -m real_ocr    # 15 passed (was 12; +3 new)
```

Manual checks:
- `grep -rE "language_model|predict_missing|repair_code|invent_token|complete_identifier" src/` returns no matches.
- Visual coverage ledger complete (TASK_10 invariant preserved).
- Multi-view memory-bounded: only OcrResult objects retained.
- One inference at a time (inference lock preserved).

## Constraints upheld

- No semantic repair: only structural operations (split, normalize,
  indent). Verified by grep and by a real_ocr test that checks no
  characters are invented.
- No new model instances: multi-view reuses the existing singleton backend.
- No concurrent inference: each `backend.recognize()` call is already
  guarded by the inference lock.
- Memory bounded: multi-view processes one view at a time.
- Visual coverage ledger (TASK_10) preserved.
- Backward compatible: all new fields are additive; existing tests pass.

## Files changed

- `src/writeup2md/ocr/multi_view.py` (new)
- `src/writeup2md/ocr/candidate_selection.py` (new)
- `src/writeup2md/ocr/code_postprocess.py` (new)
- `src/writeup2md/ocr/panel_split.py` (new)
- `src/writeup2md/ocr/enricher.py` (extended — integrates all four modules)
- `tests/unit/test_code_aware_ocr.py` (new — 30 tests)
- `tests/real_ocr/test_code_aware_real.py` (new — 3 tests)
- `docs/12_CODE_AWARE_OCR.md` (new)
- `tasks/TASK_11_CODE_AWARE_OCR.md` (new)

## Known limitations

- The split-merge dictionary is conservative (~80 rules). It catches the
  dominant space-merge cases (`importrequests`, `sudoapt`, `curlhttp`,
  `Content-Type:application`) but does not cover every possible
  identifier pair. Adding more rules is safe (the splitter only fires on
  exact prefix+suffix matches), but each new rule should be backed by a
  real OCR failure mode from the Golden Set.
- Multi-view retry adds up to 4× OCR latency on low-confidence blocks.
  This is acceptable per spec because the conservative (0.99) threshold
  already routes most blocks to review; multi-view only fires when we're
  already in the "needs help" branch.
- `recover_indentation` is conservative: it never rewrites existing
  indentation. A block where rapidocr collapsed all indentation will
  still have collapsed indentation if the colon/brace structure isn't
  visible. This is acceptable — we never invent structure.
- The candidate-selection score weights are heuristic (25/25/15/15/20).
  They could be tuned against the Golden Set in a future round, but the
  current weights already pick the better candidate on the documented
  space-merge cases.

## Next task

TASK_12 — Batch resume freshness, state machine recovery, failure cases,
concurrency verification.
