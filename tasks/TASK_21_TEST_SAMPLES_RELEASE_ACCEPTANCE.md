# TASK_21 — Test-samples release acceptance

## Goal

Run the fixed pipeline (TASK_17/18/19/20) against every PDF in
`test_samples/`, verify strict-mode sample, verify the Streamlit UI
loads, and produce the final release report
`reports/E2E_TEST_SAMPLES_RELEASE_REPORT.md`.

This is the round-3 release acceptance task. The pipeline is complete;
this task measures it.

## Non-goals

- Do not modify any file under `test_samples/`.
- Do not introduce new fixes during TASK_21 — this is a measurement
  task. If new defects surface, document them as known limitations.

## Implementation

### 21.A Full-corpus run

For each PDF in `test_samples/`:
- Run `writeup2md <pdf>` (default settings: PaddleOCR-VL element,
  `require_exact_backend=true`, document mode, 300 DPI).
- Use a 5-page slice per book to keep total runtime tractable on a
  MacBook. (Full books would take many hours; the slice is
  representative because the first 5 pages typically include cover,
  TOC, and the start of body content — exercising native text, scanned
  pages, decorative images, and code visuals.)
- Record per-sample outcomes: status, timing, block counts, markdown
  stats, visual coverage, completeness invariants.

Output: `outputs/e2e_release/` and `reports/E2E_RELEASE_RESULTS.{json,md}`.

### 21.B Strict-mode sample

Run one PDF through `writeup2md <pdf> --strict` to verify the strict
mode emits HTML-comment markers in `document.md` for review_required
visuals.

Output: `outputs/e2e_release_strict/` and a section in the release
report.

### 21.C UI load verification

Launch the Streamlit UI against `outputs/e2e_release/` and verify it
loads without error. (We won't programmatically verify UI
interactions; a successful launch is sufficient.)

### 21.D Final release report

Produce `reports/E2E_TEST_SAMPLES_RELEASE_REPORT.md` with:
- Executive summary.
- Per-sample outcomes table.
- Defects fixed (D1–D14 from TASK_16).
- Known limitations carried forward.
- MacBook performance summary.
- Commands run.
- Next-step recommendations.

### 21.E Project state update

Update `reports/PROJECT_STATE.md` to reflect Round 3 completion.

## Acceptance gates

1. Every PDF in `test_samples/` produces a `document.md` under
   `outputs/e2e_release/`.
2. Every `completeness.json` shows all 6 invariants passing.
3. No `<!-- writeup2md: -->` markers in any `document.md` (document
   mode).
4. Strict-mode sample has HTML-comment markers in `document.md`.
5. Streamlit UI launches against `outputs/e2e_release/` without
   error.
6. `reports/E2E_TEST_SAMPLES_RELEASE_REPORT.md` exists.
7. `reports/PROJECT_STATE.md` updated.

## Next task

None — this is the final task of Round 3.
