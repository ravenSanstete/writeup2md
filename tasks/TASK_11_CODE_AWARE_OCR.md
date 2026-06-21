# TASK_11 — Code-aware OCR optimization

## Goal

Improve OCR accuracy on code-heavy visual blocks without ever inventing or
repairing code semantically. Concretely:

- selective multi-view retry on low-confidence or space-merged output;
- multi-panel splitting for clearly delineated panels (terminal command
  vs output, HTTP request vs response, diff header vs body);
- code-aware postprocessing: keyword-boundary splitting for space-merge
  errors, indentation recovery from structural cues;
- candidate selection across multiple OCR passes;
- backend comparison (rapid vs mlx) on a subset to inform future selection.

## Hard constraint — no semantic repair

Per the project mission: "Never silently invent, complete or repair code."
This task MUST NOT:

- look up missing tokens from a language model;
- auto-fix syntax errors to improve parser scores;
- complete partial identifiers;
- replace unknown characters with "likely" substitutes;
- merge or split lines based on language semantics.

Allowed operations are STRUCTURAL only:

- splitting a clearly-merged token at a known keyword boundary
  (`importrequests` → `import requests` — both `import` and `requests`
  are in the dictionary);
- normalizing fullwidth punctuation to ASCII when the surrounding
  context is code;
- recovering indentation by aligning with bracket/colon structure;
- splitting multi-panel output at clear visual boundaries (prompt
  characters, HTTP separators, diff hunk markers).

## Pipeline

```text
visual block
→ run OCR (single view)
→ postprocess (existing)
→ if confidence < high threshold OR space-merge signal:
    → run OCR with N alternate preprocessing pipelines
    → postprocess each
    → candidate selection by structural score
→ multi-panel splitting (terminal / HTTP / diff)
→ code-aware postprocessing (keyword split, punctuation normalize)
→ final block state (resolved_ocr or review_required)
```

## Deliverables

1. `src/writeup2md/ocr/multi_view.py` (new):
   - `preprocess_views(image_bytes) -> list[(view_name, image_bytes)]` —
     produces N alternate preprocessing pipelines (grayscale, adaptive
     threshold, upscale 2×, denoise, invert dark theme).
   - `run_multi_view(backend, image_bytes) -> list[OcrResult]` — runs
     OCR on each view, returns results.
   - Memory-bounded: each view is processed and discarded; results are
     text + metadata only.
2. `src/writeup2md/ocr/candidate_selection.py` (new):
   - `select_best(candidates: list[OcrResult], visual_type) -> OcrResult` —
     picks the best candidate by structural score (balanced brackets,
     keyword density, code-line ratio, indentation consistency).
   - `structural_score(text, visual_type) -> float` — pure function.
3. `src/writeup2md/ocr/code_postprocess.py` (new):
   - `split_space_merged_tokens(text, language) -> str` — splits tokens
     at known keyword boundaries using a small per-language dictionary.
   - `normalize_fullwidth_punct(text) -> str` — replaces `，` → `,`,
     `：` → `:`, `（` → `(`, etc. only in code contexts.
   - `recover_indentation(text, language) -> str` — best-effort
     indentation recovery from bracket/colon structure.
4. `src/writeup2md/ocr/panel_split.py` (new):
   - `split_panels(text, visual_type) -> list[dict]` — splits terminal
     output into command vs output, HTTP into request line / headers /
     body, diff into header / hunks. Returns segments with panel labels.
5. `src/writeup2md/ocr/enricher.py` (extended):
   - integrate multi-view retry when confidence < high threshold OR
     space-merge signal;
   - integrate panel splitting into `EnrichedVisual.segments`;
   - apply code-aware postprocessing after the existing postprocess step.
6. Tests in `tests/unit/` and `tests/real_ocr/`:
   - keyword-boundary splitting on `importrequests` → `import requests`;
   - fullwidth punctuation normalization;
   - indentation recovery;
   - terminal panel splitting (command vs output);
   - HTTP panel splitting (request line, headers, body);
   - diff panel splitting;
   - candidate selection picks the candidate with balanced brackets;
   - multi-view retry produces N candidates (mock backend test);
   - real_ocr: multi-view on a known-bad fixture improves the result
     (or honestly reports no improvement).

## Acceptance gates

- `python -m pytest` passes (≥220 tests, plus new ones added).
- `python -m pytest -m real_ocr -v` passes.
- No semantic repair anywhere in the codebase (grep for forbidden
  patterns: no `language_model`, no `predict_missing`, no `repair_code`).
- Keyword-boundary splitting test passes on the documented Golden Set
  space-merge samples.
- Visual coverage ledger remains complete (TASK_10 invariant preserved).
- Memory remains bounded: no retention of full multi-view image sets.
- One inference at a time (inference lock preserved).
