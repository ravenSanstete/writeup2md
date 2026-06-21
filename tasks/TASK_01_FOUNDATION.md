# TASK_01: Foundation and Data Contracts

## Objective

Create the initial Python project, CLI skeleton, configuration model, unified IR schemas, workspace layout and serialization layer.

## Read first

- `CLAUDE.md`
- `docs/00_PRODUCT_SPEC.md`
- `docs/01_ARCHITECTURE.md`
- `docs/02_DATA_CONTRACTS.md`
- `docs/04_CLI_SPEC.md`

## Required implementation

1. Create a Python 3.11+ package named `writeup2md`.
2. Add Typer CLI commands: `convert`, `batch`, `inspect`, `ui`, `doctor`.
3. Commands may return explicit “not implemented” errors except `doctor`, but their arguments and help text must match the CLI spec.
4. Define typed Pydantic models for the Document IR, evidence, manifest and diagnostics.
5. Implement deterministic document ID generation.
6. Implement workspace creation and atomic JSON/JSONL writing.
7. Add default, fast and strict configuration profiles.
8. Add unit tests for schemas, serialization, IDs and workspace behavior.
9. Add a minimal README with installation and command examples.

## Constraints

- Do not implement real PDF, URL or OCR behavior.
- Do not add a database.
- Do not add Streamlit implementation yet.
- Do not invent fields that conflict with `docs/02_DATA_CONTRACTS.md` without updating the document and explaining why.

## Acceptance commands

```bash
python -m pytest
python -m writeup2md --help
python -m writeup2md doctor
```

## Completion report

Create `reports/TASK_01_COMPLETION.md` containing:

- files created or changed;
- design decisions;
- test results;
- known limitations;
- recommended next task.
