# TASK_13 — Streamlit review workflow

## Goal

Upgrade the existing Streamlit review UI to a complete reviewer workflow:

1. Full-text search across all documents in the result root.
2. Filters: status (accepted/review/rejected/failed), visual type, coverage state, confidence range.
3. Sort: by document ID, by status, by capture time, by visual count.
4. Zoom: click an evidence image to view at full resolution.
5. Diff: side-by-side comparison of OCR output vs user-revised text.
6. Keyboard navigation: j/k for next/previous document, n/p for next/previous visual block, / to focus search, Enter to accept.
7. Review export commands: `writeup2md inspect RESULT_DIR --export-reviews PATH` writes a JSONL of all human revisions.

## Constraints

- Streamlit lazy-loading preserved: do not load all documents on every rerun.
- MacBook resource budget preserved: no model loads, no concurrent inference.
- Backward compatible: existing `review/` storage format preserved.
- No new mandatory dependencies (use Streamlit + stdlib only).

## Deliverables

- Extended `src/writeup2md/ui/index.py` (full-text search support + block-level metadata).
- Extended `src/writeup2md/ui/app.py` (filters, sort, zoom, diff, keyboard nav).
- New `src/writeup2md/ui/search.py` (FTS implementation).
- Extended `src/writeup2md/ui/review_store.py` (export-reviews helper).
- Extended `src/writeup2md/inspect_cmd.py` (`--export-reviews` flag).
- Extended `src/writeup2md/cli.py` (wire the new flag).
- New `docs/14_REVIEW_WORKFLOW.md`.
- New `tests/unit/test_review_workflow.py`.
- New `tests/integration/test_export_reviews.py`.
- `reports/TASK_13_COMPLETION.md`.

## Acceptance gates

```
python -m pytest                # all green, +new tests
python -m writeup2md inspect --export-reviews /tmp/reviews.jsonl RESULT_DIR  # JSONL written
```

Manual:
- Launch UI on a populated result root, verify search/filters/sort/zoom/diff/keyboard nav.
- Export reviews from a document with known revisions; JSONL contains expected records.
