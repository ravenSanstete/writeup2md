# Batch resume freshness + failure recovery (TASK_12)

This document covers the batch resume freshness and failure-recovery
behavior added in TASK_12.

## Resume freshness

When `--resume` is on (default) and a cached result is found, the batch
runner checks whether the source is still fresh before skipping.

### Files (local PDF / HTML)

`check_source_freshness(source, cached_state, max_age=None)` re-hashes
the source file and compares to `cached_state["content_sha256"]`. If they
match, the cached result is fresh (skip). If they differ, the file was
edited → re-process.

### URLs

URL sources default to fresh (no network call). Users can force
re-processing with `--force-refresh`. The URL adapter stores `etag` and
`last_modified` from the HTTP response in:

- `manifest.extra["http_freshness"]` — `{"etag": ..., "last_modified": ...}`;
- `raw/metadata.json` — same fields at the top level;
- `batch_state.json` records `captured_at` for `--max-age` checks.

A future round may add an opt-in HEAD-request freshness check for URLs.

### `--max-age SECONDS`

Treats cached results as fresh if younger than SECONDS. Applied to both
files (via `captured_at` in `batch_state.json`) and URLs. When `max_age`
is satisfied, the content check is skipped.

### `--force-refresh`

Bypasses cache freshness checks entirely. Always re-processes. Useful
when the user knows the source has changed but the freshness heuristic
disagrees (e.g. URL with no ETag).

## Partial-state recovery

When `_process_one` finds an existing document directory but its
`manifest.json` is missing (interrupted mid-write), `_recover_partial_state`
moves the partial directory to `<document_id>.partial.<timestamp>` for
forensic inspection. We never silently delete user data.

The recovery is triggered:

- When the cached state's `document_id` directory exists but `manifest.json`
  is missing.
- Before re-processing any source whose previous run was interrupted.

## Failure cases

Each failure mode produces:

- a clear error message in `batch_failures.jsonl`;
- a `status="failed"` entry in `batch_state.json`;
- no leftover partial state (recovered via the partial-state path).

Failure modes covered:

- missing source file → `FileNotFoundError`, no retry, immediate failure;
- network timeout on URL fetch → retry per `--retry`, then fail;
- OCR backend crash → caught, surfaced as failure, no partial state;
- malformed PDF → caught, surfaced as failure, no partial state;
- disk full → caught, surfaced as failure, no partial state;
- unknown profile override → immediate failure with clear message.

The error message format is `TypeError: <message>` so the exception type
is visible in the failure log.

## Concurrency verification

Tests verify:

- 1 worker (default) and 2 workers produce identical Markdown output,
  identical block counts, and identical statuses on the same sources.
- The singleton OCR backend is shared across workers (no duplicate
  instances — verified by existing TASK_08 tests).
- The inference lock serializes OCR calls across workers (verified by
  existing TASK_08 tests).

Document IDs may differ between 1-worker and 2-worker runs because
`workers` is part of the config hash. This is intentional: changing the
worker count invalidates the cache. The "identical output" check uses
rendered Markdown, block counts, and statuses — not document IDs.

## CLI flags

```bash
writeup2md batch INPUT --force-refresh          # always re-process
writeup2md batch INPUT --max-age 3600           # skip if cache < 1 hour old
writeup2md batch INPUT --workers 2              # use 2 workers (max for macbook)
writeup2md batch INPUT --retry 2                # retry failed sources twice
```
