# TASK_14 — Real-source end-to-end release

## Goal

Validate the Round 2 feature set end-to-end against real sources:
8+ PDFs, 12+ URLs, 100+ visual blocks. Produce
`reports/ROUND_2_RELEASE_REPORT.md` documenting corpus composition,
per-document status, per-visual-type counts, performance timings,
memory observations, known limitations. Update `README.md` and
`CLAUDE.md` to reflect the Round 2 feature set.

## Constraints

- MacBook resource budget preserved: 1 worker, 1 OCR instance, 1
  inference at a time, sequential PDF pages.
- No automated large-corpus benchmark as part of tests or task
  acceptance — this is a manual release gate.
- Use only sources we already have rights/permission to process:
  `test_samples/` PDFs, `tests/fixtures/`, `evaluation/golden/`,
  public kanxue thread + adjacent technical-blog URLs (if reachable
  without auth).
- If a URL source is unreachable (paywall, auth, network), record it
  as "unreachable — skipped" in the release report and move on.

## Deliverables

- `reports/ROUND_2_RELEASE_REPORT.md` — corpus composition,
  per-document outcomes, visual-block breakdown, performance summary,
  known limitations, validated commands.
- `reports/ROUND_2_CORPUS/` — JSONL manifest of the corpus used
  (source, document_id, status, block_count, visual_count, captured_at,
  duration_s).
- `README.md` — updated to reflect Round 2 features.
- `CLAUDE.md` — updated "End-to-end completion definition" to reference
  Round 2 capabilities.

## Acceptance gates

- All 8+ PDFs convert without `failed` status (accepted or review).
- At least 10 of 12+ URLs convert without `failed` status (the rest
  may be unreachable).
- Total visual blocks across the corpus ≥ 100.
- `evaluate-ocr evaluation/golden/ --backend rapid` still passes and
  metrics match the TASK_09 baseline (within ±0.02 CER).
- `reports/ROUND_2_RELEASE_REPORT.md` exists with the required sections.
- `reports/PROJECT_STATE.md` updated to mark Round 2 complete.
