# TASK_22 Completion — Page Checkpointing

Round 4 — Full-Book PDF Compilation.

## Summary

Implemented durable page-level checkpointing for full-book PDF conversion.
Ordinary unsliced PDF conversion now uses page shards under
`outputs/<document-dir>/pages/000001/`, `pages/000002/`, etc., while the
user-facing artifact remains one `document.md`.

## 22.1 Resume Audit Findings

Before TASK_22:

- Completed pages were not independently reusable. `convert_pdf()` accumulated
  all blocks in memory and called `finalize_document()` once at the end.
- A process interruption during single-PDF conversion caused the whole PDF to
  restart.
- OCR candidates were not reusable per page except as incidental final
  evidence assets after a successful document-level run.
- No page-level state existed.
- Final Markdown could not be rebuilt from page artifacts without rerunning
  extraction/OCR, because page artifacts were not canonical.
- Failed pages could not be retried independently.
- Batch resume was source-level only. It skipped or reran a whole document
  based on cached manifest/config/source state.

After TASK_22:

- Each page has a persistent shard with `page.json`, `page.md`,
  `completeness.json`, `provenance.jsonl`, `page_state.json`, and `evidence/`.
- Runtime state is recorded in `state/document_state.json`,
  `state/page_state.sqlite`, and `state/events.jsonl`.
- Verified pages are skipped on resume.
- Failed pages are retried only with `--restart-failed`.
- Final `document.md` is rebuilt from verified page shards with
  `compile_document_from_page_shards()` and does not rerun OCR.
- Corrupt page shards are detected and rebuilt.

## Files Changed

- `tasks/TASK_22_PAGE_CHECKPOINTING.md`
- `tasks/TASK_23_LONG_DOCUMENT_RUNTIME.md`
- `tasks/TASK_24_CROSS_PAGE_RECONSTRUCTION.md`
- `tasks/TASK_25_FULL_DOCUMENT_COMPLETENESS.md`
- `tasks/TASK_26_OPTIONAL_GENERAL_VLM.md`
- `tasks/TASK_27_FULL_BOOK_212_ACCEPTANCE.md`
- `tasks/TASK_28_MULTI_BOOK_ACCEPTANCE.md`
- `tasks/TASK_29_FULL_BOOK_RELEASE.md`
- `src/writeup2md/adapters/pdf.py`
- `src/writeup2md/pdf_checkpoint.py`
- `src/writeup2md/pipeline.py`
- `src/writeup2md/cli.py`
- `tests/integration/test_pdf_checkpointing.py`
- `docs/01_ARCHITECTURE.md`
- `docs/04_CLI_SPEC.md`

## Implementation Notes

- `page_state.sqlite` is runtime state only. Files remain canonical for page
  content and evidence.
- Page completion is atomic at the directory level: artifacts are written to a
  temporary page directory, then renamed to `pages/<page>/` only after
  `page_state.json` reaches `verified`.
- `source_pdf_sha256`, checkpoint config hash, extraction schema, model repo,
  and model revision are recorded in document and page state.
- The checkpoint config hash intentionally excludes worker count, max workers,
  and resume policy so worker-count changes do not invalidate page content.
- The production identity constants remain
  `PaddlePaddle/PaddleOCR-VL` @
  `baee27eebcbf26cdeab160116679d765f13a3f27`.
- `writeup2md status outputs/<document-dir>` reports page progress.
- `writeup2md convert` now exposes `--resume/--no-resume` and
  `--restart-failed`.

## Tests Run

```bash
python -m py_compile src/writeup2md/pdf_checkpoint.py \
  src/writeup2md/pipeline.py src/writeup2md/cli.py \
  src/writeup2md/adapters/pdf.py

python -m writeup2md convert tests/fixtures/pdf/writeup.pdf \
  --output /tmp/w2m_task22_smoke --ocr-backend mock --force

python -m writeup2md status /tmp/w2m_task22_smoke/writeup-b5126d74

python -m pytest tests/integration/test_pdf_checkpointing.py -q
# 10 passed

python -m pytest tests/unit/test_cli.py \
  tests/integration/test_pdf_pipeline.py \
  tests/integration/test_acceptance.py -q
# 37 passed
```

## Known Limitations

- Full-book performance instrumentation is not complete; that is TASK_23.
- Cross-page reconstruction is not complete; that is TASK_24.
- The current full-document completeness report covers hard page and Markdown
  integrity invariants, but richer suspicious-page analysis is TASK_25.
- OS signal handling sets an interruption flag and stops before the next page.
  A signal during a single long OCR inference waits for that inference call to
  return before the page transaction is either completed or abandoned.

## Next Step

Proceed to TASK_23: long-document runtime, bounded resources, and performance
instrumentation.
