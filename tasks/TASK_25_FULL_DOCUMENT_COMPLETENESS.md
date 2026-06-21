# TASK_25 — Full-document completeness and anomaly detection

Round 4 — Full-Book PDF Compilation.

## Goal

Report page-by-page and whole-document completeness for full-book PDF output.

## Acceptance

- Every page has a completeness record.
- `full_document_completeness.json` and
  `full_document_completeness.md` are written.
- Hard full-book invariants cover page coverage, failed pages, sequence gaps,
  missing visuals, fallback count, image-free Markdown, and fence integrity.
- Suspicious pages are listed with reasons.
- Native text coverage is compared against final Markdown text volume to
  catch catastrophic omissions.
