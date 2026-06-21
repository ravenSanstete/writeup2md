# TASK_12 — Batch resume freshness + failure recovery

## Goal

Make batch processing robust against:

- source content that changed since the cached conversion (file edit, URL update);
- interrupted batch runs that leave a partial document directory;
- failure cases that surface a clear error and leave the document in a defined state;
- concurrency hazards when workers > 1.

## Resume freshness rules

### Files (local PDF / HTML)

When `--resume` is on and an existing cached result is found:

1. Re-compute the source's `content_sha256` from disk.
2. Compare to the cached `content_sha256` in `batch_state.json`.
3. If they match → skip (deterministic).
4. If they differ → re-process (the file was edited).

### URLs

URLs cannot be reliably checksummed without re-downloading. Use the
following approach:

1. At capture time, store `etag`, `last_modified`, and `captured_at` in
   the document manifest's `source.extra`.
2. On resume, send a HEAD request and compare `ETag` / `Last-Modified`
   to the cached values.
3. If `--max-age SECONDS` is set, skip if `captured_at` is younger than
   SECONDS regardless of ETag.
4. If `--force-refresh` is set, always re-process.
5. If the HEAD request fails or the server doesn't return ETag /
   Last-Modified, fall back to re-processing (conservative).

### Partial state recovery

When `_process_one` finds an existing document directory but its
`manifest.json` or `document.json` is missing (interrupted mid-write):

1. Detect the partial state.
2. Move the partial directory to `<document_id>.partial.<timestamp>` for
   forensic inspection (don't silently delete user data).
3. Re-process from scratch.

## Failure cases

Each failure mode must produce:

- a clear error message in `batch_failures.jsonl`;
- a defined `status="failed"` entry in `batch_state.json`;
- no leftover partial state in the output directory (cleaned up via the
  partial-state recovery path above).

Failure modes covered:

- missing source file → `FileNotFoundError`, no retry;
- network timeout on URL fetch → retry per `--retry`, then fail;
- OCR backend crash → caught, surfaced as failure, no partial state;
- malformed PDF → caught, surfaced as failure, no partial state;
- disk full → caught, surfaced as failure, no partial state.

## Concurrency verification

Tests must verify:

- 1 worker (default) and 2 workers produce identical output (same document IDs,
  same status, same block counts).
- The singleton OCR backend is shared across workers (no duplicate instances).
- The inference lock serializes OCR calls across workers.

## CLI flags

- `--force-refresh` — bypass cache freshness checks; always re-process.
- `--max-age SECONDS` — treat cached results as fresh if younger than SECONDS.
  Applies to both files (mtime) and URLs (captured_at).

## Deliverables

1. `src/writeup2md/batch.py`:
   - `check_source_freshness(source, cached_state, *, force_refresh, max_age) -> bool`
     — returns True if the cached result is still fresh.
   - `_recover_partial_state(document_dir) -> bool` — detects and recovers
     partial state. Returns True if recovery happened.
   - `run_batch(..., force_refresh: bool = False, max_age: int | None = None)`
     — extended signature.
2. `src/writeup2md/cli.py`:
   - `batch --force-refresh` and `batch --max-age SECONDS` options.
3. `src/writeup2md/adapters/url.py`:
   - Store `etag`, `last_modified` from the HTTP response in manifest.extra.
   - `_check_url_freshness(url, cached_etag, cached_last_modified) -> bool`
     — HEAD request to compare.
4. Tests in `tests/integration/`:
   - file edited → re-processed;
   - URL with ETag unchanged → skipped;
   - URL with ETag changed → re-processed;
   - partial state recovery;
   - `--force-refresh` bypasses cache;
   - `--max-age` treats young cache as fresh;
   - 1 worker vs 2 workers produce identical output.

## Acceptance gates

- `python -m pytest` passes (≥245 tests, plus new ones added).
- File edit detection works (test fixture: edit file, re-run batch, source is re-processed).
- URL freshness detection works (test fixture: mock HEAD response).
- Partial state is recovered (test fixture: corrupt a document dir, re-run).
- 1-worker and 2-worker runs produce identical output on the same sources.
- `--force-refresh` always re-processes.
- `--max-age 3600` treats 1-hour-old cache as fresh.
- No leftover partial state in output directory.
- Memory remains bounded; no whole-batch retention.
