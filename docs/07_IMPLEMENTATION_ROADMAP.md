# Implementation Roadmap

## Phase 1: Foundation

Deliver:

- repository structure;
- typed configuration;
- IR schemas;
- workspace and output layout;
- Typer CLI skeleton;
- deterministic IDs;
- serialization tests.

No OCR and no real PDF/URL processing yet.

## Phase 2: URL native extraction

Deliver:

- Playwright capture;
- article-container candidate selection;
- native text and native code extraction;
- image/evidence capture;
- Markdown generation for native content.

## Phase 3: PDF native extraction

Deliver:

- PDF preservation;
- native text and reading-order extraction;
- embedded image and rendered-page evidence;
- unified IR output.

## Phase 4: PaddleOCR-VL visual enrichment

Deliver:

- visual routing;
- PaddleOCR-VL backend abstraction;
- code, terminal, HTTP, diff and configuration handling;
- confidence and review states;
- strict no-auto-repair behavior.

## Phase 5: Quality gates and batch processing

Deliver:

- batch manifest;
- resumable task state;
- accepted/review/rejected/failed routing;
- diagnostics;
- golden-set evaluation.

## Phase 6: Streamlit UI

Deliver:

- batch dashboard;
- Markdown reader;
- OCR evidence comparison;
- human revision persistence;
- document review actions;
- artifact inspection.

## Phase 7: End-to-end release acceptance

Deliver:

- performance profiling;
- failure recovery;
- model and browser diagnostics;
- packaging;
- end-to-end documentation;
- release acceptance report;
- MacBook-safe resource validation;
- representative PDF, URL, batch-resume and Streamlit smoke tests.

## Execution order

Claude Code must implement the phases sequentially using `tasks/TASK_01_FOUNDATION.md` through `tasks/TASK_07_RELEASE_ACCEPTANCE.md`. Under continuous execution, it must not wait for approval between completed tasks. Resource behavior throughout all phases is governed by `docs/08_MACBOOK_EXECUTION.md`.
