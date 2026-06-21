# TASK_06: Streamlit Review UI

## Objective

Implement the review and reading experience defined in `docs/05_STREAMLIT_UI_SPEC.md`.

## Required implementation

- batch dashboard;
- document search and status filters;
- Markdown reader with table of contents and code highlighting;
- OCR review comparison with evidence zoom;
- editable human revision stored separately;
- previous/next review block controls;
- structure and diagnostics tabs;
- artifact viewers;
- document accept, review and reject actions;
- cached index for responsive loading.

## Non-negotiable behavior

- never overwrite raw OCR output;
- never overwrite evidence;
- human-reviewed Markdown is a separate artifact;
- no destructive corpus-wide operations.

## MacBook constraints

- use a cached compact index;
- paginate corpus tables;
- lazy-load the selected document and selected evidence image;
- do not preload corpus thumbnails;
- launching the UI must not load the OCR model;
- keep review persistence atomic and limited to the selected document.
