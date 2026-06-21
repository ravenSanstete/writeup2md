# Streamlit Review UI Specification

## Purpose

The UI is a reading and quality-review tool for processed documents. It is not a pipeline configuration console and not a general file manager.

Primary users should be able to:

- read the reconstructed Markdown comfortably;
- compare OCR-derived blocks with their original screenshot;
- filter to low-confidence or unresolved blocks;
- correct selected text without losing the raw model output;
- accept, flag or reject a document;
- navigate large batches quickly.

## Application layout

### Sidebar

- result-root selector;
- search by title, source URL, document ID or tag;
- status filter: accepted, review, rejected, failed;
- source-type filter: PDF, URL, HTML;
- quality-score range;
- unresolved-visual toggle;
- previous and next document controls.

### Header

Display:

- title;
- source link or local source path;
- document status;
- quality score;
- number of OCR-enriched blocks;
- number of unresolved blocks;
- captured/processed time;
- buttons: Open source, Download Markdown, Download JSON bundle.

### Main tabs

#### 1. Reader

- render final Markdown with comfortable typography;
- sticky table of contents;
- syntax-highlight fenced code blocks;
- source-block anchors;
- toggle to show block IDs and confidence badges;
- full-text search with highlighted matches.

#### 2. OCR Review

Two-column comparison:

- left: original evidence image with zoom;
- right: selected transcription in an editable code editor or text area.

Controls:

- block type selector;
- language selector;
- raw OCR output expander;
- transformation history;
- confidence indicators;
- previous/next OCR block;
- save correction;
- mark verified;
- mark needs review;
- reset to model output.

Corrections must be stored separately as human revisions. Never overwrite raw OCR output.

#### 3. Source Structure

- ordered block list;
- type, page/selector, confidence and resolution state;
- click a block to jump to Reader or OCR Review;
- filters for headings, code, terminal, HTTP, diff, table and unresolved visual.

#### 4. Diagnostics

- document-level metrics;
- warnings and errors;
- unresolved important visuals;
- quality-gate results;
- processing timeline;
- source and config hashes.

#### 5. Raw Artifacts

- manifest viewer;
- document JSON viewer;
- provenance JSONL viewer;
- raw HTML/PDF metadata;
- evidence file browser restricted to the selected document.

## Batch dashboard

When opened on a result root, the landing page shows:

- total, accepted, review, rejected and failed counts;
- quality-score distribution;
- unresolved-block counts;
- recent failures;
- sortable document table;
- one-click entry into the next review-required document.

## Review persistence

Human edits should be written to:

```text
outputs/<id>/review/
├── revisions.jsonl
├── review_state.json
└── document.reviewed.md
```

The original `document.md`, raw OCR output and evidence remain unchanged.

## Usability requirements

- first useful page must load without scanning the whole corpus repeatedly;
- cache a compact document index and parsed metadata;
- support documents with hundreds of blocks without preloading all blocks or evidence images;
- preserve scroll position when moving between comparison and reader views where practical;
- make keyboard navigation possible for previous/next review blocks;
- show evidence at readable resolution with zoom;
- never expose destructive bulk-delete actions.

## MacBook performance constraints

- Load one selected document at a time.
- Load only the selected OCR evidence image, with an optional on-demand zoom.
- Paginate the batch table instead of rendering the entire corpus.
- Do not create thumbnails for the full corpus at startup.
- Key caches by file modification time or content hash so manual corrections invalidate only affected views.
- Keep the UI read/review process separate from OCR inference; launching the UI must not automatically load PaddleOCR-VL.

## Implementation status (TASK_06)

- `src/writeup2md/ui/index.py` — compact `DocumentIndexEntry` list built from `manifest.json` + `diagnostics.json` + `document.json` + `document.md`. Cached via `@st.cache_data` keyed on a directory-mtime signature. Skips status subdirectories.
- `src/writeup2md/ui/review_store.py` — human revision persistence under `outputs/<id>/review/`:
  - `review_state.json` (human status, per-block verified flags, per-block corrections, notes);
  - `revisions.jsonl` (append-only audit log of every edit);
  - `document.reviewed.md` (human-edited Markdown, separate from original).
  - **Never mutates** `document.md`, `document.json`, raw evidence, or raw OCR output.
- `src/writeup2md/ui/app.py` — full Streamlit app:
  - Dashboard: counts, filters (status / source type / search), paginated table (50/page), one-click open.
  - Document view: header with metrics, Accept / Flag for review / Reject / Back buttons, 5 tabs.
  - Reader tab: rendered Markdown with toggle for source view and block IDs, download button, review-required markers visible.
  - OCR Review tab: prev/next block navigation, two-column evidence+transcription layout, raw OCR expander (read-only), editable correction text area, Save correction / Mark verified / Needs review buttons, per-block revision history.
  - Source Structure tab: dataframe of all blocks (order, id, type, visual_type, state, confidence, text preview).
  - Diagnostics tab: metrics, block counts, unresolved visuals, OCR confidence distribution, warnings, errors, hashes.
  - Raw Artifacts tab: expandable viewers for manifest, document.md, document.json, diagnostics.json, provenance.jsonl, and an evidence file browser (capped at 20 entries).
- `src/writeup2md/ui_runner.py` — launches Streamlit as a subprocess with the result root as positional arg.
- CLI: `writeup2md ui [RESULT_ROOT]` invokes the launcher.
- Launching the UI does NOT load PaddleOCR-VL — the UI is read/review only.
