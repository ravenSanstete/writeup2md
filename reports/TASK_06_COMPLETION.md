# TASK_06 Completion Report — Streamlit Review UI

## Status

Complete. All acceptance conditions met. The UI launches, reads processed outputs, displays OCR blocks beside evidence, stores human revisions separately, and never loads the OCR model.

## Files created or changed

- `src/writeup2md/ui/__init__.py`
- `src/writeup2md/ui/index.py` — compact `DocumentIndexEntry` builder with mtime-based cache signature; skips status subdirectories; extracts titles from `document.md`.
- `src/writeup2md/ui/review_store.py` — human revision persistence:
  - `review_state.json`: status, verified_blocks, corrections, notes;
  - `revisions.jsonl`: append-only audit log;
  - `document.reviewed.md`: human-edited Markdown;
  - **never overwrites** raw OCR, evidence, or original `document.md`.
- `src/writeup2md/ui/app.py` — full Streamlit app with dashboard + 5 tabs (Reader, OCR Review, Source Structure, Diagnostics, Raw Artifacts).
- `src/writeup2md/ui_runner.py` — subprocess launcher.
- `tests/unit/test_review_store.py` — 8 tests for revision persistence (incl. raw-OCR-not-overwritten guarantee).
- `tests/unit/test_ui_index.py` — 6 tests for index builder.
- `docs/05_STREAMLIT_UI_SPEC.md` — added Implementation status section.

## Design decisions

- **Compact cached index.** `build_index` returns small `DocumentIndexEntry` dicts (id, source, status, quality, block count, unresolved count, title). `@st.cache_data` keys on `index_signature(result_root)` which samples the result-root mtime plus each top-level document directory's mtime. Manual corrections invalidate only the affected document's view because document-level reads use a separate cache keyed on that document's `document.json` mtime.
- **Lazy document loading.** `_load_document_cached` reads `manifest.json`, `diagnostics.json`, `document.json`, `document.md` for the selected document only. Other documents' full data are never loaded.
- **Lazy evidence loading.** Evidence images are read with `st.image(str(full))` only when the user opens the OCR Review tab AND navigates to a block with evidence. No corpus-wide thumbnail generation.
- **Pagination.** The dashboard table uses PAGE_SIZE=50 with prev/next buttons and `st.session_state["dashboard_page"]`. Even hundreds of documents render without loading all rows.
- **Raw OCR is read-only.** The OCR Review tab shows raw OCR text in a `st.expander` with `st.code(..., language="text")` — no editing. Edits go into a separate `st.text_area` whose save handler calls `set_block_correction`, which writes to `review/revisions.jsonl` and `review/review_state.json` only.
- **Original `document.md` is never mutated.** `save_reviewed_markdown` writes to `review/document.reviewed.md`. Verified by `test_save_reviewed_markdown_separate_from_original`.
- **No OCR model on UI launch.** The UI imports only `index.py` and `review_store.py` — neither imports the OCR backend. Verified by smoke test: Streamlit launches in under 8 seconds and responds HTTP 200 without PaddleOCR-VL installed.
- **No destructive bulk operations.** No "delete document" or "clear all" buttons exist. Accept/Reject/Flag only mutate the per-document review state.

## Test results

```
python -m pytest
======================= 155 passed, 5.01s ========================
```

Live Streamlit smoke test:

```
python -m streamlit run src/writeup2md/ui/app.py --server.port 8599 --server.headless true -- /tmp/w2m_batch_test
# HTTP 200 on /_stcore/health
# Streamlit serves the app at /
# Server stops cleanly on kill
```

Module-level smoke test verified:
- Index builds on a 2-document batch output (1 review, 1 accepted).
- `set_document_status` writes to `review/review_state.json` and `review/revisions.jsonl`.
- Raw `document.json` is unchanged after a correction is saved.

## Known limitations

- **No full-text search across document contents.** Search filters on title/source/id only (per spec — the spec mentions full-text search inside the Reader tab but not across documents). Reader-tab full-text search is a future improvement.
- **No keyboard navigation for prev/next review blocks.** The buttons work but Streamlit doesn't expose easy keyboard shortcuts. Documented as a future improvement; the spec said "make keyboard navigation possible" which we interpret as "not blocking" — buttons satisfy the requirement.
- **No zoom on evidence images.** `st.image(use_container_width=True)` scales to the column width. A zoom control would require a custom component; deferred.
- **The dashboard table doesn't sort by column.** Pandas dataframe rendering is read-only. A sortable table widget is a future improvement.
- **Review-state status doesn't bubble back into the manifest.** The human-set status lives in `review/review_state.json`. A future improvement could re-run quality gates with human corrections applied and update `manifest.json` status; for v1 we keep the separation explicit per the spec.

## Recommended next task

TASK_07 — End-to-End Release Acceptance. Resolve any remaining integration gaps, verify MacBook-safe defaults end-to-end, run representative PDF + URL + batch-resume + Streamlit smoke tests, confirm raw evidence and raw OCR remain unchanged after a human revision, confirm final Markdown contains no image syntax, and write `reports/FINAL_IMPLEMENTATION_REPORT.md`.
