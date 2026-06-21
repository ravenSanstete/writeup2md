# TASK_22 — Page checkpointing and resume

Round 4 — Full-Book PDF Compilation.

## Goal

Introduce durable page-level PDF checkpointing so a complete book can be
processed page by page, interrupted safely, resumed without rerunning verified
pages, and compiled into one user-facing `document.md`.

## Acceptance

- Existing document-level resume behavior is audited in
  `reports/TASK_22_COMPLETION.md`.
- PDF conversions create `state/`, `pages/`, per-page artifacts, final
  `document.md`, and full-document artifacts.
- Page states include `pending`, `extracting`, `native_extracted`,
  `visuals_detected`, `ocr_processing`, `rendered`, `verified`, and `failed`.
- Verified page shards are skipped on resume.
- Failed pages can be retried with `--restart-failed`.
- Source hash, extraction schema, and PaddleOCR-VL model revision
  invalidation are handled.
- Worker-count changes do not invalidate verified page shards.
- `writeup2md status outputs/<document-dir>` reports page progress.
- Interruption preserves verified pages and prints a resume command.
- Tests cover checkpointing, resume, restart failed, invalidation,
  final compilation, atomicity, and corrupt shard detection.
