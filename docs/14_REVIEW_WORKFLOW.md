# Streamlit Review Workflow (TASK_13)

The review UI is the second-half of the writeup2md pipeline: where
human reviewers inspect OCR results, correct transcription errors,
verify blocks, and export their revisions for downstream consumption.

Launch:

```bash
writeup2md ui outputs/
# or:
streamlit run src/writeup2md/ui/app.py -- outputs/
```

## Resource discipline (preserved)

- **Lazy document loading**: only the selected document's `manifest.json`,
  `diagnostics.json`, `document.json`, and `document.md` are read.
- **Cached index**: a compact per-document summary is built once per
  result-root mtime change and reused across reruns.
- **No model loads**: the UI is read/review only. No OCR backend is
  instantiated.
- **Evidence on demand**: image bytes are read only when the user opens
  an OCR review block.
- **Pagination**: the dashboard caps at 50 rows per page.

## Full-text search

A search box at the top of the dashboard performs token-based search
across every document's `document.md`, `document.json` block text and
enrichment text, and `manifest.json` source fields.

- **Token search** (default): query is tokenized; documents matching any
  token are returned, ranked by term frequency.
- **Phrase search**: wrap the query in double quotes (`"import requests"`)
  for a literal case-insensitive substring match.
- CJK text is preserved as whole chunks (the tokenizer does not split on
  non-ASCII characters).

The search index is cached alongside the document index, keyed on the
result-root mtime signature.

## Filters

The dashboard exposes five filter controls:

1. **Status** — multiselect: accepted / review / rejected / failed.
2. **Source type** — multiselect: pdf / url / html.
3. **Coverage state** — multiselect: transcribed / native_text_used /
   decorative_with_reason / duplicate_with_reference /
   review_required / failed_with_diagnostic. A document matches if at
   least one of its visual blocks is in any selected state.
4. **Confidence range** — slider 0.0–1.0. A document matches if at least
   one visual block's enrichment.confidence falls in the range.
5. **Sort by** — document_id, status, captured_at, visual_count.

Coverage and confidence filters require lazy-loading `document.json`
for each candidate (the list is already narrowed by status/source at
that point, so the cost is bounded).

## Within-document filters (OCR Review tab)

The OCR Review tab exposes the same visual-type, coverage-state, and
confidence filters, applied to the current document's visual blocks
only. This lets the reviewer focus on, say, only `code` blocks in
`review_required` state with confidence below 0.5.

## Sort

Dashboard rows can be sorted by:

- `document_id` — ascending.
- `status` — alphabetical, then by document_id.
- `captured_at` — most recent first.
- `visual_count` — descending (approximated by block_count).

## Zoom

In the OCR Review tab, the evidence image renders at container width
by default. An expander labeled **"🔍 Zoom — view full-resolution
evidence"** shows the same image at its native size with a download
button for the original bytes.

## Diff

A toggle in the OCR Review tab enables a unified diff between the raw
OCR output (`enrichment.raw_text`) and the user-corrected text. The
diff uses Python's `difflib.unified_diff` with `fromfile="raw_ocr"`
and `tofile="corrected"`. When the two match, a success message is
shown instead.

The diff is computed from the current text-area contents (including
unsaved edits), so reviewers can iterate before saving.

## Keyboard navigation

The UI injects a small JavaScript snippet that captures `keydown`
events on the document level. Shortcuts (lowercase):

| Key     | Action                                  |
|---------|-----------------------------------------|
| `j`     | Next document (on dashboard)            |
| `k`     | Previous document (on dashboard)        |
| `n`     | Next visual block (in OCR Review tab)   |
| `p`     | Previous visual block (in OCR Review tab) |
| `/`     | Focus the search box                    |
| `Enter` | Accept (mark verified) the current block |

Shortcuts are a progressive enhancement — the visible Prev/Next buttons
remain the primary navigation. When the user is typing in a text field
or textarea, all shortcuts except `Escape` are suppressed.

> **Note**: Streamlit does not natively expose keyboard events to
> Python. The JS handler posts events into a hidden input mirrored
> into the parent frame; the Python side polls via session state.
> This works best in modern Chromium-based browsers.

## Review export

Human revisions live under `outputs/<doc_id>/review/`:

```
review/
├── review_state.json   # status, verified_blocks, corrections, notes
├── revisions.jsonl     # one record per human edit (append-only)
└── document.reviewed.md # optional: human-edited Markdown
```

Two export paths:

### In-UI export

The "Export reviews" button in the document header writes a JSONL
file to `outputs/<doc_id>/review/exported_reviews.jsonl`. Useful for
ad-hoc export while reviewing.

### CLI export

```bash
writeup2md inspect RESULT_DIR --export-reviews PATH
```

Writes a JSONL file with one record per line. The first record is
always a `review_state` snapshot:

```json
{
  "kind": "review_state",
  "document_id": "20af767e33bcaf27",
  "timestamp": "2026-06-20T03:36:41Z",
  "status": "accepted",
  "verified_blocks": {"b_000003": true},
  "corrections": {"b_000003": "import requests\nfrom bs4 import BeautifulSoup"},
  "notes": ""
}
```

Subsequent records are one per revision, annotated with `document_id`:

```json
{
  "kind": "revision",
  "document_id": "20af767e33bcaf27",
  "block_id": "b_000003",
  "field": "selected_text",
  "old_value": "importrequests",
  "new_value": "import requests",
  "user": null,
  "timestamp": "2026-06-20T03:35:10Z"
}
```

Fields `old_value` / `new_value` are untyped (string, bool, or null
depending on the `field`).

## Data integrity guarantees (preserved)

- The original `document.md`, `document.json`, `manifest.json`, raw
  OCR output, and evidence assets are NEVER modified by the UI or by
  the review store.
- All human edits land in `review/revisions.jsonl` (append-only) and
  `review/review_state.json` (atomic writes via
  `workspace.atomic_write_json`).
- The export is a read-only operation — it never writes to the source
  document directory except for the in-UI button's deterministic
  `exported_reviews.jsonl` path.
