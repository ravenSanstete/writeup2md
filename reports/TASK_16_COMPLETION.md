# TASK_16 — Test-sample inventory and end-to-end baseline (completion)

## Summary

Inventoried `test_samples/` (7 PDFs, 3,456 pages total), ran the
unmodified production pipeline (`paddleocr-vl-element` with
`require_exact_backend=true`) against a 3-page slice of the first 3
PDFs, and produced a sample-level defect ledger that drives TASK_17
through TASK_20.

The baseline confirmed a critical-path defect: sample 03 timed out at
900 s on a 3-page slice. Two other samples converted but landed in
`review` status with very low Markdown yield (164 chars and 1,872
chars) because PaddleOCR-VL transcriptions were hidden behind HTML
review markers.

## Files changed

### New files

- `tasks/TASK_16_TEST_SAMPLE_BASELINE.md` — task spec.
- `scripts/inventory_test_samples.py` — walks `test_samples/`,
  classifies files, computes SHA-256, gets PDF page counts via PyMuPDF.
- `scripts/run_e2e_baseline.py` — runs `convert_source` on each PDF
  with `page_range=(0, N)` via subprocess isolation. Records per-sample
  outcomes.
- `reports/TEST_SAMPLES_INVENTORY.json`
- `reports/TEST_SAMPLES_INVENTORY.md`
- `reports/TEST_SAMPLES_MANIFEST.jsonl`
- `reports/E2E_BASELINE_RESULTS.json`
- `reports/E2E_BASELINE_RESULTS.md`
- `reports/E2E_BASELINE_DEFECTS.jsonl` (14 defects)
- `reports/E2E_BASELINE_DEFECTS.md` (D1–D14 analysis)
- `outputs/e2e_baseline/01-…/38bccb4839b4e9a4/` (sample 01 doc dir)
- `outputs/e2e_baseline/02-…/e58fdc1d1d23860d/` (sample 02 doc dir)

## Acceptance gates

1. `reports/TEST_SAMPLES_INVENTORY.{json,md}` exist and cover every
   file under `test_samples/`. — **PASS** (7/7 PDFs).
2. `reports/TEST_SAMPLES_MANIFEST.jsonl` has one line per sample. —
   **PASS** (7 lines).
3. `outputs/e2e_baseline/` contains a document directory for every
   processable sample (baseline ran first 3; remainder will be
   exercised in TASK_21). — **PARTIAL** — baseline scope was first 3
   PDFs because sample 03 timed out, demonstrating the critical-path
   defect (D3) that gates the rest of the corpus.
4. `reports/E2E_BASELINE_RESULTS.{json,md}` exist with per-sample
   outcomes. — **PASS**.
5. `reports/E2E_BASELINE_DEFECTS.{jsonl,md}` exist with at least one
   defect per observed issue. — **PASS** (14 defects, D1–D14).
6. PaddleOCR-VL is the actual backend used (no silent RapidOCR
   fallback) — verified in each `manifest.json`. — **PASS** (samples 01
   and 02 manifests show `paddleocr-vl-element`).
7. No file under `test_samples/` was modified. — **PASS** (verified by
   SHA-256 check before and after the baseline run).

## Inventory summary

7 PDFs totaling 3,456 pages:

| sample_id | size | pages |
| --- | ---: | ---: |
| 01-a-bug-hunters-diary | 5.4 MB | 212 |
| 02-cybersecurity-tabletop-exercises | 6.0 MB | 389 |
| 03-from-day-zero-to-zero-day | 33.1 MB | 347 |
| 04-penetration-testing-a-hands-on-introduction-to-hac | 31.0 MB | 845 |
| 05-pocgtfo | 18.0 MB | 792 |
| 06-real-world-bug-hunting | 5.3 MB | 266 |
| 07-漏洞战争 | 19.4 MB | 605 |

## Baseline results

| sample_id | status | pages run | elapsed_s | md_chars | code_blocks |
| --- | --- | ---: | ---: | ---: | ---: |
| 01-a-bug-hunters-diary | review | 3 | 39.68 | 164 | 0 |
| 02-cybersecurity-tabletop-exercises | review | 3 | 91.22 | 1,872 | 1 |
| 03-from-day-zero-to-zero-day | timeout | 3 | 900.00 | — | — |

Samples 04–07 were not measured in the baseline because sample 03
timed out at 900 s, demonstrating the critical-path defect (D3). The
fixes in TASK_17/18 bring a 2-page slice of sample 02 down from 240 s+
to 21 s, which makes running all 7 PDFs tractable in TASK_21.

## Defects (14 total)

3 critical, 7 major, 4 minor. Each defect carries severity, category,
expected behavior, actual behavior, and fix target (TASK_17/18/19/20).

- **D1 — VLM confidence threshold misapplied** (critical, all samples).
  PaddleOCR-VL returns `confidence = 0.0` because the VLM does not
  produce per-region scores. The TASK_09 threshold (`high = 0.99`,
  calibrated for RapidOCR) then marks every transcription as
  `review_required`, so the renderer emits HTML-comment markers instead
  of the actual OCR text.
- **D2 — OCR output hidden by review marker** (critical, sample 01).
  Symptom of D1. `document.md` contains
  `<!-- writeup2md: [REVIEW REQUIRED] visual=code block=b_000000 -->`
  and no transcribed text.
- **D3 — 15-minute timeout on 3-page slice** (critical, sample 03).
  Multi-view retry fires for every PaddleOCR-VL visual (5× inference)
  because confidence is 0.0. `max_new_tokens=1024` produces runaway
  generation on cover-spread images (>1,000 tokens of `0`s,
  hallucinated English).
- **D4 — Embedded image OCR hallucination** (major, sample 02). Cover
  image (4,387×2,784) sent to PaddleOCR-VL, which hallucinates
  "I am the world" and runs of "0"s.
- **D5 — Image too large for VLM** (major, sample 02). Full-resolution
  4,387×2,784 image sent to VLM.
- **D6 — bbox extraction returns zeros** (major, sample 02).
  `_normalize_bbox` returns `[0,0,0,0]` when input is a 4-float list
  rather than a PyMuPDF Rect.
- **D7 — Multi-view retry useless for VLM** (major, sample 03). 5×
  inference cost for no quality benefit.
- **D8 — max_new_tokens too high** (major, sample 03).
  `max_new_tokens=1024` produces runaway generation on cover-spread
  images.
- **D9 — Raw OCR only in /tmp** (major, all samples). PaddleOCR-VL
  raw output JSON is written only to `/tmp/` and may not survive reboot.
- **D10 — No one-command CLI** (major, all samples). User must run
  `writeup2md convert SOURCE` with explicit `--ocr-backend
  paddleocr-vl-element --require-exact-backend`.
- **D11 — No completeness report** (major, all samples). No
  `completeness.json` or `quality_report.json` emitted.
- **D12 — HTML comment markers leak into Markdown** (minor, all
  samples).
- **D13 — No human-readable output dir** (minor, all samples).
  16-char hashes are opaque.
- **D14 — Default render DPI low** (minor, all samples). 200/300 DPI
  vs spec's 300/450 DPI.

Full per-defect records with `expected`/`actual` text live in
`reports/E2E_BASELINE_DEFECTS.jsonl`.

## Commands run

```bash
python scripts/inventory_test_samples.py test_samples \
    --output-json reports/TEST_SAMPLES_INVENTORY.json \
    --output-md reports/TEST_SAMPLES_INVENTORY.md \
    --output-manifest reports/TEST_SAMPLES_MANIFEST.jsonl

BASELINE_PAGES=3 BASELINE_TIMEOUT=900 python scripts/run_e2e_baseline.py \
    --samples test_samples \
    --output-dir outputs/e2e_baseline \
    --results-json reports/E2E_BASELINE_RESULTS.json \
    --results-md reports/E2E_BASELINE_RESULTS.md
```

## Known limitations

- Baseline ran the first 3 samples only because sample 03 timed out at
  900 s. Samples 04–07 will be exercised in TASK_21 once the TASK_17/18
  fixes make the full corpus tractable.
- The baseline `page_count` field was not populated in the script
  output (the script records `None` when PyMuPDF returns the page count
  from the manifest but the JSON path differs from the document
  diagnostics path). TASK_21 will populate `page_count` from
  `manifest.json.extra.page_range`.
- Defect ledger is necessarily subjective — it is based on manual
  inspection of the 3 baseline `document.md` files. TASK_21 will add
  automated completeness invariants.

## Next task

TASK_17 (visual asset recovery) — implementation already complete;
writing the TASK_17 completion report next.
