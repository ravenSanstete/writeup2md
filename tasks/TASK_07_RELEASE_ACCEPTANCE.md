# TASK_07: End-to-End Release Acceptance

## Objective

Harden and validate the complete local-first product after Tasks 01 through 06. This task defines the point at which Claude Code may declare the project complete.

## Read first

- `CLAUDE.md`
- all files in `docs/`
- all prior task completion reports
- `reports/PROJECT_STATE.md`

## Required work

1. Resolve integration gaps across PDF, URL, OCR, rendering, batch processing and Streamlit.
2. Ensure installation and first-run documentation is accurate.
3. Add or update small stable end-to-end fixtures.
4. Verify MacBook-safe resource defaults.
5. Run lint, type checking, unit tests and relevant integration tests.
6. Run one representative PDF conversion.
7. Run one representative URL or stable local HTML conversion.
8. Run a mixed sequential batch with interruption and resume.
9. Launch the Streamlit UI and verify the reader and OCR review workflow.
10. Confirm that raw evidence and raw OCR output remain unchanged after a human revision.
11. Confirm final Markdown contains no image syntax or HTML image tags.
12. Update all design documents to match delivered behavior.

## MacBook resource acceptance

- default `--workers` is `1`;
- no acceptance command uses more than one worker;
- no more than one PaddleOCR-VL model instance exists in a process;
- OCR inference is serialized;
- PDF pages are processed sequentially;
- Playwright uses one browser and closes each source page;
- Streamlit does not preload all evidence images;
- no Docker, vLLM, Ray, Celery or distributed execution is required.

## Required final commands

Use the actual project commands established during implementation. At minimum validate equivalents of:

```bash
python -m pytest
python -m writeup2md doctor
python -m writeup2md convert tests/fixtures/pdf/<representative>.pdf --profile macbook
python -m writeup2md convert tests/fixtures/html/<representative>.html --profile macbook
python -m writeup2md batch tests/fixtures/batch/sources.jsonl --workers 1 --resume --profile macbook
python -m writeup2md inspect <representative-result-dir>
```

The Streamlit UI must also be launched and manually smoke-tested with:

```bash
python -m writeup2md ui <result-root>
```

Do not leave the server running after validation.

## Completion artifacts

Create:

- `reports/TASK_07_COMPLETION.md`
- `reports/FINAL_IMPLEMENTATION_REPORT.md`

The final report must include:

- implemented features;
- exact installation and usage commands;
- tests and acceptance checks executed;
- representative output locations;
- MacBook resource behavior;
- known limitations;
- optional future improvements clearly separated from required functionality.

Do not declare completion if required behavior is unimplemented, untested or represented by placeholders.
