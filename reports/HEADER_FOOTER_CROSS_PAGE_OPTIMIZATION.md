# Header/Footer and Cross-page Reconstruction Optimization

## Summary

Implemented conservative, traceable cleanup for page furniture and stronger
cross-page continuation for prose/code. This addresses the two observed
full-book output issues: meaningless headers/footers/page numbers leaking into
Markdown, and body/code content being interrupted at page boundaries.

## What Changed

- Page furniture detection now supports normalized signatures for page numbers,
  `Chapter N` running headers, alternating running-title variants, and known
  PDF generator artifacts such as `Powered by TCPDF`.
- Furniture removal requires edge-page location and strong recurrence evidence,
  except known generator/page-number artifacts which have their own conservative
  rules.
- Removed furniture is written to `reconstruction_removed.jsonl` with page,
  block id, bbox, reason, evidence count, pages, signature, and confidence.
- Cross-page prose merging now runs after furniture removal and supports safe
  prose dehyphenation.
- Cross-page code merging now supports code-like visual blocks, native code,
  matching language/type, line-number continuity, unbalanced syntax, and
  indentation continuation.
- Reconstruction diagnostics are written to `reconstruction_diagnostics.json`
  and surfaced in `full_document_completeness.json` / `.md`.

## Validation Run

Only lightweight static/unit checks were run. No full-book conversion and no
PaddleOCR-VL/model command was executed.

```bash
python -m py_compile src/writeup2md/reconstruction.py src/writeup2md/pdf_checkpoint.py
python -m pytest tests/unit/test_reconstruction.py tests/unit/test_full_document_completeness.py -q
# 16 passed in 0.11s
```

## Manual Full-book Check Later

When the machine is idle, rerun one book manually and compare:

```bash
writeup2md "<book.pdf>" --output outputs/full_book_release --resume
```

Inspect:

- `document.md`
- `reconstruction_removed.jsonl`
- `reconstruction_diagnostics.json`
- `full_document_completeness.md`

Expected improvements:

- fewer `Powered by TCPDF`, running-title, footer, and page-number leaks;
- fewer page-boundary paragraph breaks;
- cleaner continuation for code blocks split across pages;
- skipped uncertain merges are listed instead of silently guessed.
