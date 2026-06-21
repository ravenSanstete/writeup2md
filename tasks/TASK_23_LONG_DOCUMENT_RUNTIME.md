# TASK_23 — Long-document runtime and bounded resources

Round 4 — Full-Book PDF Compilation.

## Goal

Make full-book conversion memory-safe and observable over hundreds of pages.

## Acceptance

- PDF processing remains streaming and does not load every page image into
  memory.
- PaddleOCR-VL model instances remain `1`; OCR concurrency remains `1`.
- Native-text pages avoid unnecessary high-DPI full-page rendering.
- Runtime metrics are emitted to `reports/FULL_BOOK_PERFORMANCE.jsonl` and
  `reports/FULL_BOOK_PERFORMANCE.md`.
- A long sequence demonstrates no uncontrolled page-count-tied memory growth.
