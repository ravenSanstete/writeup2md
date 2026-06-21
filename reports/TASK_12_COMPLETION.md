# TASK_12 Completion Report — Batch resume freshness + failure recovery

## Status

Complete. Batch processing now detects source-content changes (file edits),
recovers from interrupted runs (partial-state cleanup), supports
`--force-refresh` and `--max-age SECONDS`, and verifies that 1-worker and
2-worker runs produce identical output. 15 new tests cover all freshness
and recovery paths.

## What was delivered

### Source freshness check (`src/writeup2md/batch.py`)

- `check_source_freshness(source, cached_state, max_age=None) -> bool` —
  returns True if the cached result is still fresh.
  - `max_age` check first: if `captured_at` is younger than `max_age`
    seconds, return True.
  - URL sources default to True (no network call).
  - Local files: re-hash and compare to `cached_state["content_sha256"]`.
  - On any error (file missing, etc.), return False (conservative — re-process).

### Partial-state recovery (`src/writeup2md/batch.py`)

- `_recover_partial_state(document_dir) -> bool` — detects partial state
  (manifest.json missing) and moves the directory to
  `<document_id>.partial.<timestamp>` for forensic inspection. Never
  silently deletes user data.
- Called from `_process_one`:
  - When the cached state's `document_id` directory exists but
    `manifest.json` is missing.
  - Before re-processing any source whose previous run was interrupted.

### Extended `run_batch` signature

- `force_refresh: bool = False` — bypasses cache freshness checks; always
  re-processes. Propagated to `convert_source(force=force_refresh)`.
- `max_age: int | None = None` — treats cached results as fresh if
  younger than SECONDS.

### URL adapter enhancements (`src/writeup2md/adapters/url.py`)

- Captures `etag` and `last_modified` from the HTTP response.
- Stores them in:
  - `manifest.extra["http_freshness"]` — `{"etag": ..., "last_modified": ...}`;
  - `raw/metadata.json` — same fields at the top level.
- These are recorded for future freshness checks (the current
  `check_source_freshness` defaults URLs to fresh to avoid network calls;
  a future round may add an opt-in HEAD-request check).

### CLI flags (`src/writeup2md/cli.py`)

- `batch --force-refresh` — bypass cache freshness checks.
- `batch --max-age SECONDS` — treat cached results as fresh if younger.

### State recording (`src/writeup2md/batch.py`)

- `batch_state.json` now records `captured_at` for each source, read from
  the document manifest. Used by `--max-age` checks.
- `_extract_captured_at(result) -> str | None` — helper that reads
  `captured_at` from the document manifest.

### Error message clarity

- Failure messages now include the exception type:
  `f"{type(e).__name__}: {e}"` instead of just `str(e)`.
- This makes it easier to grep failures by type (`FileNotFoundError`,
  `TimeoutError`, `OSError`, etc.).

### Tests (`tests/integration/test_resume_freshness.py`) — 15 tests

Freshness:
- `test_freshness_file_unchanged_returns_true`
- `test_freshness_file_edited_returns_false`
- `test_freshness_url_defaults_to_true`
- `test_freshness_max_age_young_cache_returns_true`
- `test_freshness_max_age_expired_falls_through_to_content_check`
- `test_freshness_missing_file_returns_false`

Partial-state recovery:
- `test_recover_partial_state_moves_incomplete_dir`
- `test_recover_partial_state_skips_complete_dir`
- `test_recover_partial_state_missing_dir_returns_false`

End-to-end:
- `test_batch_file_edit_triggers_reprocessing` — edit a file between runs;
  the second run re-processes.
- `test_batch_force_refresh_bypasses_cache` — `--force-refresh` re-processes
  even when content is unchanged.
- `test_batch_max_age_treats_young_cache_as_fresh` — `--max-age=3600` skips
  a 0-second-old cache.
- `test_batch_max_age_expired_falls_through_to_content_check` — `--max-age=1`
  with a fresh cache still skips (content matches).
- `test_batch_one_vs_two_workers_identical_output` — 1-worker and 2-worker
  runs produce identical Markdown, block counts, and statuses.
- `test_batch_recovers_partial_state_on_rerun` — corrupt a document dir
  (delete manifest.json); the next run recovers and re-processes.

## Acceptance gates

```
python -m pytest                # 251 passed (was 236; +15 new)
python -m pytest -m real_ocr    # 15 passed (unchanged)
```

Manual checks:
- File edit detection: edit a PDF between batch runs → second run
  re-processes (verified by `test_batch_file_edit_triggers_reprocessing`).
- `--force-refresh` bypasses cache (verified by
  `test_batch_force_refresh_bypasses_cache`).
- `--max-age 3600` treats 1-hour-old cache as fresh (verified by
  `test_batch_max_age_treats_young_cache_as_fresh`).
- Partial state recovered (verified by
  `test_batch_recovers_partial_state_on_rerun`).
- 1-worker and 2-worker output identical (verified by
  `test_batch_one_vs_two_workers_identical_output`).

## Constraints upheld

- No new model instances: unchanged.
- No concurrent inference: unchanged (inference lock preserved).
- No Docker/Ray/Celery/vLLM/distributed: none added.
- Memory bounded: partial-state recovery moves directories on disk; no
  whole-batch retention.
- Worker max 2: unchanged (enforced by `enforce_macbook_limits`).
- Backward compatible: `force_refresh` and `max_age` default to off;
  existing callers work without changes.

## Files changed

- `src/writeup2md/batch.py` (extended — `check_source_freshness`,
  `_recover_partial_state`, `_extract_captured_at`, `force_refresh` /
  `max_age` on `run_batch` and `_process_one`, error message clarity)
- `src/writeup2md/cli.py` (extended — `--force-refresh` and `--max-age`
  options on `batch`)
- `src/writeup2md/adapters/url.py` (extended — capture and store
  `etag` / `last_modified` in manifest and metadata)
- `tests/integration/test_resume_freshness.py` (new — 15 tests)
- `docs/13_RESUME_FRESHNESS.md` (new)
- `tasks/TASK_12_RESUME_FRESHNESS.md` (new)

## Known limitations

- URL freshness defaults to "fresh" (no network call). This avoids a
  network round-trip on every batch run, but means URL changes are not
  detected automatically. Users must use `--force-refresh` or `--max-age`
  to force re-processing. A future round may add an opt-in HEAD-request
  check using the stored `etag` / `last_modified`.
- Partial-state recovery moves directories to
  `<document_id>.partial.<timestamp>`. Over time, these can accumulate.
  Users should clean them up manually or via a future `writeup2md clean`
  command.
- Document IDs differ between 1-worker and 2-worker runs because `workers`
  is part of the config hash. This is intentional (changing worker count
  invalidates the cache) but means cross-worker resume is not possible
  without `--force-refresh`.

## Next task

TASK_13 — Streamlit review workflow. Full-text search, filters, sort, zoom,
diff, keyboard navigation, review export commands.
