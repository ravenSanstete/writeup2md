# Claude Code Continuous Build Prompt

Copy the prompt below into Claude Code from the repository root.

```text
Implement the complete writeup2md project described in this repository.

First read, in this order:
1. CLAUDE.md
2. README.md
3. docs/00_PRODUCT_SPEC.md through docs/08_MACBOOK_EXECUTION.md
4. tasks/TASK_01_FOUNDATION.md through tasks/TASK_07_RELEASE_ACCEPTANCE.md

Then execute all tasks sequentially, beginning with TASK_01 and continuing through TASK_07. Do not stop after planning, auditing, scaffolding, or writing a completion report. Implement each task, run its acceptance checks, fix failures, write its completion report, update reports/PROJECT_STATE.md, and immediately continue to the next task without asking me for approval.

Use the written specifications as the source of truth. Resolve routine ambiguity conservatively, record the assumption, and continue. Ask me only when work is genuinely impossible because a required credential, source file, inaccessible external service, or irreversible product decision is missing. If an optional component is blocked, document it and complete all unblocked work.

This must run safely on my MacBook Pro:
- default to one worker;
- never use more than two workers;
- only one PaddleOCR-VL model instance;
- only one OCR inference at a time;
- one Playwright browser with one active page by default;
- process PDF pages sequentially;
- keep heavy-stage queue sizes at two or less;
- lazy-load Streamlit data and evidence;
- do not add Docker, distributed systems, vLLM, Ray, Celery, Kubernetes, or a multi-process inference server;
- do not run large batch stress tests;
- prefer native text, caching, resume, and selective high-resolution retries over concurrency.

Maintain implementation quality throughout:
- typed Python 3.11+;
- tests added with behavior;
- raw evidence and raw OCR outputs are immutable;
- no silent code repair or hallucinated content;
- final Markdown has no images;
- human Streamlit corrections are stored separately;
- update design docs whenever behavior changes.

Continue until the end-to-end release acceptance task passes. At the end, create reports/FINAL_IMPLEMENTATION_REPORT.md containing:
- implemented features;
- exact installation and run commands;
- all tests and acceptance commands executed;
- MacBook resource behavior;
- known limitations;
- any optional future improvements.

Begin now with TASK_01. Do not merely describe what you plan to do; perform the work.
```

## Suggested shell start

From the repository root:

```bash
claude
```

Then paste the prompt above. Keep Claude Code in the repository root so it can continuously read task reports and recover project state after context compaction.
