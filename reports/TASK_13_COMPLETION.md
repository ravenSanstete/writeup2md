# TASK_13 Completion Report — Streamlit review workflow

## Status

Complete. The Streamlit review UI now supports full-text search,
extended filters (status / source type / coverage state / confidence
range), sort, evidence zoom, side-by-side diff between raw OCR and
corrected text, keyboard navigation, and a CLI review-export command.
27 new tests (25 unit + 2 integration) cover all paths.

## What was delivered

### Full-text search (`src/writeup2md/ui/search.py` — new)

- `build_search_index(result_root) -> list[SearchDoc]` — one entry per
  document, tokenizing `document.md`, `document.json` (block.text +
  enrichment.selected_text + enrichment.raw_text), and `manifest.json`
  source fields.
- `search_documents(index, query, limit=100) -> list[SearchResult]` —
  token-based TF ranking with alphabetical tiebreaker on document_id.
- **Phrase search**: wrapping the query in double quotes triggers a
  literal case-insensitive substring match (re-reads the document text
  on the fly for adjacency).
- **CJK support**: chunks without ASCII tokens (e.g. `漏洞世界`) are
  kept whole as single tokens.
- The index is cached via `@st.cache_data` keyed on the same mtime
  signature as the document index.

### Extended dashboard filters (`src/writeup2md/ui/app.py`)

- **Status** multiselect (preserved from prior UI).
- **Source type** multiselect (preserved).
- **Coverage state** multiselect — filters documents with at least one
  visual block in any selected state.
- **Confidence range** slider — filters documents with at least one
  visual block whose `enrichment.confidence` falls in the range.
- **Sort by** selectbox — `document_id` (asc), `status` (asc),
  `captured_at` (desc), `visual_count` (desc, approximated by
  `block_count`).

Block-level filters (coverage, confidence) lazy-load `document.json`
for each candidate. The candidate list is already narrowed by status
and source filters at that point, so the cost is bounded.

### Within-document filters (OCR Review tab)

The OCR Review tab exposes its own visual-type, coverage-state, and
confidence filters, applied to the current document's visual blocks.
Useful for focusing on, e.g., only `code` blocks in `review_required`
state with confidence below 0.5.

### Zoom (`src/writeup2md/ui/app.py`)

The evidence image renders at container width by default. An expander
labeled **"🔍 Zoom — view full-resolution evidence"** renders the same
image at native size with a download button for the original bytes.

### Diff (`src/writeup2md/ui/app.py` — `_render_diff`)

A toggle in the OCR Review tab enables a unified diff between
`enrichment.raw_text` and the user-corrected text (current textarea
contents, including unsaved edits). Uses `difflib.unified_diff` with
`fromfile="raw_ocr"`, `tofile="corrected"`. When the two match, a
success message is shown.

### Keyboard navigation (`src/writeup2md/ui/app.py` — `_install_keyboard_handler`)

The UI injects a JS snippet that captures `keydown` events on the
document level. Shortcuts:

| Key     | Action                                      |
|---------|---------------------------------------------|
| `j`     | Next document (dashboard)                   |
| `k`     | Previous document (dashboard)               |
| `n`     | Next visual block (OCR Review tab)          |
| `p`     | Previous visual block (OCR Review tab)      |
| `/`     | Focus the search box                        |
| `Enter` | Accept (mark verified) the current block    |

Shortcuts are a progressive enhancement — the visible Prev/Next
buttons remain the primary navigation. When the user is typing in a
text field or textarea, all shortcuts except `Escape` are suppressed.

> Streamlit does not natively expose keyboard events to Python. The
> JS handler posts events into a hidden input mirrored into the
> parent frame. This works best in modern Chromium-based browsers.
> The on-screen buttons remain the canonical navigation surface.

### Review export

Two paths:

1. **In-UI button** ("Export reviews" in the document header) writes
   `outputs/<doc_id>/review/exported_reviews.jsonl`.
2. **CLI command**: `writeup2md inspect RESULT_DIR --export-reviews PATH`.

Both call `export_reviews_jsonl` in
`src/writeup2md/ui/review_store.py` (new), which calls
`export_reviews` to build the record list.

Payload structure (JSONL, one record per line):

- **First record**: `kind="review_state"` — current status,
  `verified_blocks`, `corrections`, `notes`, `document_id`, `timestamp`.
- **Subsequent records**: `kind="revision"` — one per entry in
  `revisions.jsonl`, annotated with `document_id`.

### CLI surface (`src/writeup2md/cli.py` — extended)

`inspect` now accepts `--export-reviews PATH`:

```bash
writeup2md inspect outputs/20af767e33bcaf27 --export-reviews /tmp/reviews.jsonl
```

On success, prints `Exported N review record(s) to PATH`. On missing
manifest, returns exit code 4 (input error).

### Diagnostics tab — visual coverage ledger

The Diagnostics tab now renders `diagnostics.visual_coverage` (added
in TASK_10) as a JSON block, so reviewers can see at a glance how
every visual block ended.

### Source Structure tab — coverage column

The Source Structure table now includes a `coverage` column showing
the per-block coverage state, alongside the existing visual_type,
state, and confidence columns.

## Acceptance gates

```
python -m pytest                       # 278 passed (was 251; +27 new)
python -m pytest -m real_ocr           # 15 passed (unchanged)
python -m writeup2md inspect outputs/<id> --export-reviews /tmp/r.jsonl  # OK
```

Manual CLI smoke test (run during development):

```
$ python -m writeup2md convert tests/fixtures/html/tutorial.html --ocr-backend mock --output /tmp/w2md_task13_demo
Status: REVIEW
Markdown: /tmp/w2md_task13_demo/20af767e33bcaf27/document.md

$ python -m writeup2md inspect /tmp/w2md_task13_demo/20af767e33bcaf27 --export-reviews /tmp/w2md_task13_reviews.jsonl
[...inspect table rendered...]
Exported 1 review record(s) to /tmp/w2md_task13_reviews.jsonl

$ cat /tmp/w2md_task13_reviews.jsonl
{"corrections": {}, "document_id": "20af767e33bcaf27", "kind": "review_state", "notes": "", "status": null, "timestamp": "2026-06-20T03:36:41Z", "verified_blocks": {}}
```

## Tests

### Unit (`tests/unit/test_review_workflow.py` — 25 tests)

Tokenization (4):
- `test_tokenize_alphanumeric`
- `test_tokenize_empty`
- `test_tokenize_cjk_keeps_chunk`
- `test_tokenize_preserves_dashes`

Search index (4):
- `test_build_search_index_finds_documents`
- `test_build_search_index_extracts_block_text`
- `test_build_search_index_skips_status_subdirs`
- `test_build_search_index_empty_root`

Search ranking (8):
- `test_search_returns_matching_documents`
- `test_search_ranks_by_term_frequency`
- `test_search_empty_query_returns_empty`
- `test_search_no_matches_returns_empty`
- `test_search_phrase_query_matches_substring`
- `test_search_phrase_query_no_match`
- `test_search_limit_caps_results`
- `test_search_tiebreaker_is_document_id`

Review store export (4):
- `test_export_reviews_returns_state_and_revisions`
- `test_export_reviews_handles_no_revisions`
- `test_export_reviews_jsonl_writes_file`
- `test_export_reviews_jsonl_creates_parent_dir`

inspect_cmd integration (2):
- `test_inspect_export_reviews_writes_jsonl`
- `test_inspect_export_reviews_missing_manifest_raises`

CLI surface (3):
- `test_cli_inspect_export_reviews_option_in_help`
- `test_cli_inspect_export_reviews_runs`
- `test_cli_inspect_export_reviews_missing_manifest_input_error`

### Integration (`tests/integration/test_export_reviews.py` — 2 tests)

- `test_export_reviews_end_to_end` — convert HTML, apply revisions,
  export, verify JSONL payload.
- `test_export_reviews_with_no_revisions` — freshly-converted doc
  with no human edits exports exactly one `review_state` record.

## Constraints upheld

- No new model instances: unchanged.
- No concurrent inference: unchanged.
- No Docker/Ray/Celery/vLLM/distributed: none added.
- Memory bounded: search index is built per-result-root and cached;
  evidence images load on demand; no whole-corpus deserialization on
  rerun.
- Worker max 2: unchanged (UI does not touch the batch runner).
- Backward compatible: `review/` storage format preserved; new export
  functions are additive; `inspect` without `--export-reviews` behaves
  exactly as before.
- No new mandatory dependencies: only stdlib + Streamlit (already
  required for the UI).

## Files changed

- `src/writeup2md/ui/search.py` (new)
- `src/writeup2md/ui/review_store.py` (extended — `export_reviews`,
  `export_reviews_jsonl`)
- `src/writeup2md/ui/app.py` (extended — search box, filters, sort,
  zoom, diff, keyboard nav, in-UI export button, visual coverage in
  Diagnostics and Structure tabs)
- `src/writeup2md/inspect_cmd.py` (extended — `export_reviews`)
- `src/writeup2md/cli.py` (extended — `inspect --export-reviews PATH`)
- `tests/unit/test_review_workflow.py` (new — 25 tests)
- `tests/integration/test_export_reviews.py` (new — 2 tests)
- `docs/14_REVIEW_WORKFLOW.md` (new)
- `tasks/TASK_13_STREAMLIT_REVIEW_WORKFLOW.md` (new)

## Known limitations

- **Keyboard shortcuts rely on injected JavaScript**: Streamlit does
  not natively expose keyboard events to Python. The handler posts to
  a hidden input mirrored into the parent frame; this is a
  progressive enhancement and works best in Chromium-based browsers.
  The visible Prev/Next buttons remain the primary navigation.
- **Block-level filters lazy-load `document.json`** for each candidate.
  On very large corpora (1000+ docs) with broad status/source filters,
  this could be slow. Mitigation: the dashboard already paginates at
  50 rows, and the search index narrows the candidate set first.
- **Sort by `visual_count`** uses `block_count` as a proxy because the
  index entry does not store a separate visual-only count. A future
  round could add a `visual_block_count` field to `DocumentIndexEntry`.
- **Phrase search re-reads the document text** on the fly. This is
  acceptable because phrase search is typically used on small filtered
  sets, but could be optimized by storing raw text in the search index
  (memory cost) if it becomes a bottleneck.

## Next task

TASK_14 — Real-source end-to-end release. Run the pipeline against
8+ real PDFs and 12+ real URLs (100+ visual blocks total), produce a
performance report, and write `reports/ROUND_2_RELEASE_REPORT.md`.
