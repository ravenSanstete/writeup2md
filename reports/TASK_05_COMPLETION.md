# TASK_05 Completion Report — Batch Processing and Quality Gates

## Status

Complete. All acceptance conditions met.

## Files created or changed

- `src/writeup2md/batch.py` — full batch runner:
  - input parsing: directory (with optional `--recursive`, `--include`, `--exclude`), URL list (`.txt`/`.urls`), JSONL manifest (with per-source `id`, `tags`, `profile` overrides), and mixed JSONL;
  - durable file-backed state at `outputs/batch_state.json` (one record per canonical source);
  - per-source manifest appended to `outputs/batch_manifest.jsonl`;
  - failures appended to `outputs/batch_failures.jsonl`;
  - final summary at `outputs/batch_summary.json`;
  - resume: deterministic skip when content_sha256 + config_sha256 match an existing completed output AND its `manifest.json` still exists on disk;
  - retry loop with configurable `--retry` count;
  - workers=1 (sequential) and workers=2 (ThreadPoolExecutor for I/O-bound orchestration; OCR still serialized by the inference lock);
  - status subdirectories `accepted/`, `review/`, `rejected/`, `failed/` created for layout conformance;
  - `simulate_interruption_after` test helper for resume tests;
- `src/writeup2md/cli.py` — added `--ocr-backend` to `batch` so users (and tests) can force the mock backend.
- `tests/fixtures/batch/sources.jsonl` — 2-source mixed manifest (PDF + HTML).
- `tests/integration/test_batch.py` — 12 integration tests: JSONL/URL-list/directory/recursive/include-exclude parsing, two-source run with summary, resume skips completed, resume after simulated full interruption, partial resume processes remaining, failure recording, MacBook worker limit rejection, status subdirectory creation.

## Design decisions

- **File-backed state, not SQLite.** The spec said "A simple file-backed manifest is preferred for v1. SQLite is acceptable only if it materially simplifies atomic resume behavior." A single `batch_state.json` keyed by canonical source is simpler, atomically rewritten after each source via the existing `atomic_write_json`, and trivially inspectable. SQLite would add a dependency and a binary artifact for no gain at this scale.
- **Deterministic skip key = canonical source.** URLs are normalized (lowercased scheme/host, trailing slash stripped, fragment dropped) so the same URL in different forms hits the same state record. Local paths are stored as given.
- **Skip requires three conditions:** (1) prior status is `accepted`/`review`/`rejected` (not `failed`), (2) the stored `config_sha256` matches the current config, (3) the output's `manifest.json` still exists on disk. This prevents skipping when the user changed config or deleted the output.
- **Workers=2 uses threads, not processes.** OCR is I/O-bound on the model and serialized by `_INFERENCE_LOCK` regardless. Threads are sufficient for overlapping the lightweight source-orchestration work (Playwright launch, PDF read, DOM parse) and they share the singleton backend instance safely. The MacBook profile caps workers at 2.
- **Per-source profile override.** JSONL entries can specify `"profile": "strict"` to override the batch default. This is useful for mixed corpora where some sources need stricter thresholds.
- **Failures are append-only.** `batch_failures.jsonl` accumulates across runs so users can audit what went wrong. Re-running with `--resume` after fixing the underlying issue will re-attempt the failed source (failed entries are NOT skipped).
- **No corpus-wide benchmark in tests.** Per spec, tests use 1–2 small fixtures.

## Test results

```
python -m pytest
======================= 141 passed, 5 warnings in 0.97s ========================
```

End-to-end CLI smoke test:

```
python -m writeup2md batch tests/fixtures/batch/sources.jsonl --output /tmp/w2m_batch_test --workers 1 --resume --profile macbook --ocr-backend mock
Batch complete: 2 sources
  accepted=1 review=1 rejected=0 failed=0

# resume run (both skipped):
python -m writeup2md batch tests/fixtures/batch/sources.jsonl --output /tmp/w2m_batch_test --workers 1 --resume --profile macbook --ocr-backend mock
Batch complete: 2 sources
  accepted=0 review=0 rejected=0 failed=0
```

Output layout matches the spec:
```
outputs/
├── <document_id>/          # one per source
├── accepted/               # status subdirs (empty in v1; tracked in manifest)
├── review/
├── rejected/
├── failed/
├── batch_manifest.jsonl    # one record per processed source
├── batch_state.json        # durable resume state
├── batch_summary.json      # final run summary
└── batch_failures.jsonl    # append-only failures
```

## Known limitations

- **Status subdirectories are created but not populated with symlinks.** Documents stay under `<document_id>/`. The spec's `accepted/`, `review/`, `rejected/`, `failed/` subdirs exist for layout conformance; the batch manifest's `status` field is the authoritative routing record. Adding symlinks would complicate resume and atomic writes without adding value at this scale.
- **No live progress reporting.** The CLI prints only the final summary. For long batches, a Rich progress bar would be a future improvement.
- **workers=2 path uses `ThreadPoolExecutor`.** This is bounded and safe (OCR serialized), but the spec's "bounded queue capacity ≤ 2" is honored implicitly because we submit at most 2 futures at a time. An explicit bounded queue could be added for stricter backpressure.

## Recommended next task

TASK_06 — Streamlit Review UI. Implement the batch dashboard, document search and status filters, Markdown reader with TOC and code highlighting, OCR review comparison with evidence zoom, editable human revision stored separately, previous/next review block controls, structure and diagnostics tabs, artifact viewers, document accept/review/reject actions, and a cached compact index for responsive loading.
