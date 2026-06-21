# TASK_21 — Test-samples release acceptance (completion)

## Summary

Round-3 release acceptance task. Ran the fixed pipeline (TASK_17/18/
19/20) against every PDF in `test_samples/`, verified the strict-mode
sample, verified the Streamlit UI loads, and produced the final
release report `reports/E2E_TEST_SAMPLES_RELEASE_REPORT.md`.

All 7 PDFs convert with `accepted` status and 6/6 completeness
invariants passing. The product contract `writeup2md SOURCE →
outputs/<slug>-<short_hash>/document.md` is satisfied on Apple
Silicon with no flags needed.

## Files changed

### New files

- `scripts/run_e2e_release.py` — release runner that invokes the
  library API on each of the 7 PDFs in `test_samples/` with a 5-page
  slice, `paddleocr-vl-element` backend, `require_exact_backend=true`,
  and records per-sample outcomes (status, timing, visual coverage,
  markdown stats, completeness invariants) to
  `reports/E2E_RELEASE_RESULTS.{json,md}`.

- `reports/E2E_RELEASE_RESULTS.{json,md}` — per-sample metrics for
  the 7-PDF run.

- `reports/E2E_TEST_SAMPLES_RELEASE_REPORT.md` — the final Round-3
  release report with executive summary, per-sample outcomes table,
  D1–D14 defect-resolution table, known limitations, MacBook
  performance summary, commands run, strict-mode mechanism
  documentation, output-layout reference, and next-step
  recommendations.

- `reports/TASK_21_COMPLETION.md` — this report.

- `tasks/TASK_21_TEST_SAMPLES_RELEASE_ACCEPTANCE.md` — task spec.

### Modified files

- `reports/PROJECT_STATE.md` — updated to reflect Round 3 completion.

## Acceptance gates

1. Every PDF in `test_samples/` produces a `document.md` under
   `outputs/e2e_release/`. — **PASS** (7/7 samples produced
   `document.md`).
2. Every `completeness.json` shows all 6 invariants passing. —
   **PASS** (7/7 samples show `passed: 6, failed: 0`).
3. No `<!-- writeup2md: -->` markers in any `document.md` (document
   mode). — **PASS** (`html_comment_marker_count: 0` across all 7
   samples).
4. Strict-mode sample has HTML-comment markers in `document.md`. —
   **PASS** (verified two ways):
   - Strict mode with `mock` backend against `tutorial.html`
     produces `<!-- writeup2md: [UNRESOLVED] visual=http block=b_000014 -->`
     in `document.md` and `html_comment_marker_count: 1` in
     `completeness.json` (allowed in strict mode).
   - Strict mode with `paddleocr-vl-element` against PoCGTFO produces
     no markers (all visuals resolved — the markers only appear when
     review_required blocks exist).
   - The strict-mode marker mechanism is also unit-tested in
     `tests/unit/test_render.py::test_render_strict_emits_marker_for_review_required`
     and
     `tests/unit/test_render.py::test_render_visual_review_required_with_text_surfaces_it_in_document_mode`,
     plus
     `tests/unit/test_completeness.py::test_completeness_allows_html_comment_markers_in_strict_mode`.
5. Streamlit UI launches against `outputs/e2e_release/` without
   error. — **PASS** (`streamlit run src/writeup2md/ui/app.py --
   outputs/e2e_release/` returned HTTP 200 on root, `ok` on
   `/_stcore/health`, no errors in streamlit log, app module loads
   cleanly, result-root scan discovers all 7 manifests).
6. `reports/E2E_TEST_SAMPLES_RELEASE_REPORT.md` exists. — **PASS**
   (written this task).
7. `reports/PROJECT_STATE.md` updated. — **PASS** (updated this
   task).

## Verification runs

### Full-corpus run (TASK_21.A)

```bash
python scripts/run_e2e_release.py
```

Output (per-sample summary):

| sample_id | status | pages | visuals | transcribed | review | decorative | md_chars | md_code_blocks | completeness | elapsed_s |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| 01-a-bug-hunters-diary | accepted | 5 | 4 | 4 | 0 | 0 | 345 | 4 | 6/6 | 38.43 |
| 02-cybersecurity-tabletop-exercises | accepted | 5 | 1 | 1 | 0 | 0 | 3555 | 3 | 6/6 | 19.64 |
| 03-from-day-zero-to-zero-day | accepted | 5 | 6 | 6 | 0 | 0 | 832 | 6 | 6/6 | 63.85 |
| 04-penetration-testing | accepted | 5 | 2 | 2 | 0 | 0 | 3258 | 4 | 6/6 | 20.31 |
| 05-pocgtfo | accepted | 5 | 1 | 1 | 0 | 0 | 3051 | 3 | 6/6 | 16.94 |
| 06-real-world-bug-hunting | accepted | 5 | 5 | 2 | 0 | 3 | 346 | 2 | 6/6 | 31.70 |
| 07-漏洞战争 | accepted | 5 | 2 | 2 | 0 | 0 | 2350 | 2 | 6/6 | 32.61 |

Total elapsed: 223.48 s. Mean per-sample: 31.93 s. All 7 samples
accepted. All 7 completeness reports show 6/6 invariants passing.

### Strict-mode sample (TASK_21.B)

Two runs:

1. **Strict mode + mock backend** on `tests/fixtures/html/tutorial.html`
   to force the `review_required` / `unresolved` path:
   - Status: `review` (correct — mock returns empty for the
     screenshot).
   - `document.md` contains:
     `<!-- writeup2md: [UNRESOLVED] visual=http block=b_000014 -->`
   - `completeness.json` shows `html_comment_marker_count: 1` and
     `mode: "strict"` (allowed — invariant passes in strict mode).

2. **Strict mode + PaddleOCR-VL** on PoCGTFO PDF (5-page slice):
   - Status: `accepted` (all visuals resolved, no markers needed).
   - Elapsed: 17.13 s.
   - `completeness.json` shows `html_comment_marker_count: 0` and
     `mode: "strict"`.
   - This confirms the strict-mode path runs cleanly against the
     real backend when no review_required blocks exist.

### UI load verification (TASK_21.C)

```bash
streamlit run src/writeup2md/ui/app.py -- outputs/e2e_release/ \
    --server.headless true --browser.gatherUsageStats false
```

Result:
- HTTP 200 on root (`http://localhost:8501/`).
- `ok` on `/_stcore/health`.
- No errors in streamlit log.
- App module imports cleanly.
- Result-root scan discovers all 7 manifests in
  `outputs/e2e_release/`.

(Programmatic UI-interaction verification is out of scope per the
task spec — a successful launch is sufficient.)

### Final release report (TASK_21.D)

`reports/E2E_TEST_SAMPLES_RELEASE_REPORT.md` produced with:
- Executive summary with headline numbers.
- Per-sample outcomes table.
- D1–D14 defect-resolution table.
- Known limitations (sample 03 chatty descriptions, PoCGTFO
  character-per-line rendering, carried-forward limitations).
- MacBook performance summary (per-sample timing, s/page, s/visual).
- Commands run (full-corpus, strict-mode, UI).
- Strict-mode mechanism documentation.
- Output-layout reference.
- Next-step recommendations.

### Project state update (TASK_21.E)

`reports/PROJECT_STATE.md` updated to reflect Round 3 completion
(see "Current task" and "Completed tasks" sections in that file).

## Commands run

```bash
# Full-corpus run
python scripts/run_e2e_release.py
# → reports/E2E_RELEASE_RESULTS.{json,md}

# Strict-mode sample (mock backend, tutorial.html)
PYTHONPATH=src python -c "
from writeup2md.config import Profile, build_config
from writeup2md.pipeline import convert_source
from pathlib import Path
cfg = build_config(Profile.MACBOOK)
cfg.ocr.backend = 'mock'
cfg.quality.mode = 'strict'
r = convert_source(
    source='tests/fixtures/html/tutorial.html',
    output_root=Path('/tmp/w2md_strict_mock'),
    config=cfg, force=True)
print(r.status.value)
print(r.document_dir)
"
# → review, /tmp/w2md_strict_mock/tutorial-b7aeaacb
# → document.md contains <!-- writeup2md: [UNRESOLVED] ... -->

# Strict-mode sample (real PaddleOCR-VL, PoCGTFO)
PYTHONPATH=src python -c "
from writeup2md.config import Profile, build_config
from writeup2md.pipeline import convert_source
from pathlib import Path
cfg = build_config(Profile.MACBOOK)
cfg.ocr.backend = 'paddleocr-vl-element'
cfg.quality.mode = 'strict'
r = convert_source(
    source='test_samples/PoCGTFO (Manul Laphroaig) (z-library.sk, 1lib.sk, z-lib.sk).pdf',
    output_root=Path('/tmp/w2md_strict_test'),
    config=cfg, force=True, page_range=(0, 5))
print(r.status.value)
print(r.document_dir)
"
# → accepted, /tmp/w2md_strict_test/pocgtfo-manul-laphroaig-z-library-sk-1li-f85b787f

# UI load verification
streamlit run src/writeup2md/ui/app.py -- outputs/e2e_release/ \
    --server.headless true --browser.gatherUsageStats false &
sleep 8
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8501/          # 200
curl -s http://localhost:8501/_stcore/health                              # ok
kill %1
```

## Known limitations

- Strict-mode verification required the `mock` backend to exercise
  the HTML-comment-marker path. With `paddleocr-vl-element` on the
  test_samples corpus, all visuals resolve and no markers appear —
  the marker mechanism is verified by unit tests and the mock-backend
  run instead. This is not a defect — it means PaddleOCR-VL is good
  enough to resolve every visual in this corpus — but it does mean
  the strict-mode markers don't appear naturally in the
  `outputs/e2e_release/` corpus.
- Sample 03 (From Day Zero to Zero Day) has 3 chatty descriptions
  ("The provided image is a graphic design...") in its
  `document.md`. The text is grounded in the source (it IS a graphic-
  design logo) so the document is `accepted`, but the description is
  more verbose than a pure transcription. Documented as a known
  limitation in the release report; a future round could add a
  chat-detection heuristic.
- PoCGTFO's cover page renders as one character per line in
  `document.md` due to the source PDF's extreme letter-spacing. The
  text is preserved and searchable; only the line wrapping is
  affected. Documented as a known limitation in the release report.
- Full-book conversion was not run (only 5-page slices). A 400-page
  book at ~6.4 s/page would take ~43 minutes on this MacBook. The
  5-page slice is representative because it exercises cover, TOC,
  body content, native text, scanned pages, decorative images, and
  code visuals.
- UI-interaction verification is out of scope per the task spec. A
  successful Streamlit launch is sufficient; programmatic
  interaction tests are covered by the existing test suite
  (`tests/unit/test_review_workflow.py`, 25 tests).

## Next task

None — this is the final task of Round 3. Round 3 (TASK_16 through
TASK_21) is complete. The product contract
`writeup2md SOURCE → outputs/<slug>-<short_hash>/document.md` is
satisfied on Apple Silicon with `paddleocr-vl-element` as the default
backend and `require_exact_backend=true`.
