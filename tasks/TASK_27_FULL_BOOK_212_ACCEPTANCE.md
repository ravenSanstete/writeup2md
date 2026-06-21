# TASK_27 — Complete 212-page book acceptance

Round 4 — Full-Book PDF Compilation.

## Goal

Process the complete `A Bug Hunter's Diary` PDF with no page slice and prove
interruption/resume on at least 30 verified pages.

## Acceptance

- Exact PDF path is resolved from `test_samples/`.
- `writeup2md "<path>" --output outputs/full_book_release --resume` runs with
  no page range.
- Controlled interruption verifies at least 30 pages before stopping.
- Resume skips verified pages and completes the book.
- Final hard invariants pass for the exact PyMuPDF page count.
- Manual review is recorded in
  `reports/FULL_BOOK_212_MANUAL_REVIEW.md`.
