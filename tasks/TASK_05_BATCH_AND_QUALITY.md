# TASK_05: Batch Processing and Quality Gates

## Objective

Add reliable batch execution, resume behavior and document acceptance routing.

## Required implementation

- directory, URL-list and JSONL input;
- mixed PDF/URL manifests;
- durable task state using files or SQLite only if clearly justified;
- resume and retry;
- deterministic skip for unchanged completed inputs;
- accepted/review/rejected/failed routing;
- batch summary and failures files;
- quality gates from `docs/06_QUALITY_AND_TESTING.md`.

## MacBook constraints

- default worker count is `1`;
- enforce a hard maximum of `2` in the MacBook profile;
- OCR concurrency remains `1`;
- use bounded queues with capacity no greater than `2` for heavy stages;
- persist progress after each source;
- do not load the complete input manifest or all document artifacts into memory when streaming is practical;
- acceptance tests must use `--workers 1`.
