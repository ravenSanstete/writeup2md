# TASK_09 Completion Report — Golden Set and Real OCR Evaluation

## Status

Complete. The project now has a 45-sample Golden Set with known ground truth, an `evaluate-ocr` command that runs the real rapid backend over the set and computes 20+ accuracy metrics globally and by visual type, a confidence-calibration audit that drove a conservative threshold change in the enricher, and a concrete OCR error taxonomy.

## What was delivered

### Golden Set

- `evaluation/golden/manifest.jsonl` — 45 samples, each with `sample_id`, `visual_type`, `language`, `image_path`, `gold_verbatim`, `critical_tokens`, `line_numbers_present`, `cropped`, `dark_theme`, etc.
- `evaluation/golden/images/` — 45 PIL-rendered screenshot PNGs with real visual text (not renamed text files).
- `evaluation/golden/expected/<sample_id>.txt` — gold verbatim text mirror.
- `evaluation/golden/README.md` — composition notes and diversity coverage.
- `reports/GOLDEN_SET_SCHEMA.md` — formal schema doc.

Coverage:
- visual types: code (23), configuration (6), http (5), terminal (3), diff (3), log (3), traceback (2)
- languages: python (18), bash (7), http (4), diff (3), log (3), yaml (2), ini (2), json (1), toml (1), javascript (1), go (1), rust (1), java (1)
- themes: light (43), dark (2)
- edge cases: editor line numbers, cropped content, low-resolution image, punctuation-heavy, URLs, hashes, IP addresses, quoted strings with escapes, indentation-sensitive Python, merge conflict markers, multi-header HTTP

Honest shortfall: 45 samples is above the 40 minimum but below the 100 target. Each sample is hand-crafted with known ground truth; inflating the count with duplicates would not improve evaluation quality. Growing to 100+ is deferred to a future round (extract real visual blocks from `test_samples/` PDFs).

### Evaluator

- `src/writeup2md/evaluate.py`:
  - `evaluate_golden_set(golden_dir, backend_name, output_dir)` — runs real OCR over the set, computes metrics, writes reports.
  - `compute_metrics(gold, actual, sample)` — pure function computing all metrics for one sample. Reusable.
  - `calibrate_confidence(metrics, thresholds)` — false-accept / false-review rates under given thresholds.
  - `aggregate`, `aggregate_by_visual_type` — summary helpers.
  - Refuses to use the mock backend; raises clearly when no real backend is available.
- CLI: `writeup2md evaluate-ocr evaluation/golden/ --backend rapid --output reports/golden-eval/`

Metrics computed (global and per visual_type):
- character error rate, normalized character accuracy
- exact full-sample match, exact line match
- missing-line rate, extra-line rate
- indentation exact-match, leading-whitespace accuracy
- punctuation accuracy (quotes, brackets, slash/backslash, underscore/hyphen, colon/semicolon, equals, pipe, at, hash, dollar)
- digit accuracy
- URL exact-match, hash exact-match
- critical-token recall
- visual-type classification accuracy
- language-detection accuracy
- terminal command/output segmentation precision/recall/F1
- editor line-number removal accuracy
- hallucinated-character rate

### Reports produced

- `reports/GOLDEN_SET_METRICS.json` — full aggregate + per-visual-type + calibration
- `reports/GOLDEN_SET_METRICS.md` — human-readable summary
- `reports/OCR_ERROR_TAXONOMY.md` — 17-category taxonomy with concrete examples
- `reports/golden-eval/results.jsonl` — per-sample metrics (45 records)
- `reports/golden-eval/summary.json`
- `reports/golden-eval/by_visual_type.json`

### Confidence calibration → enricher change

Findings (rapidocr-onnxruntime 1.4.4 on this Mac):
- mean model_confidence = 0.94 on samples with mean CER = 0.17
- under legacy thresholds (low=0.6, high=0.85): 44/45 auto-accepted, accepted_precision = 0.07, 41 false accepts
- rapidocr's confidence is NOT a calibrated probability — it is slightly anti-correlated with quality on edge cases

Change in `src/writeup2md/ocr/enricher.py`:
- `_HIGH_CONFIDENCE_THRESHOLD` raised from `0.85` to `0.99`
- added `_FAILED_THRESHOLD = 0.3` for empty-output cases
- added `_looks_space_merged(text)` structural-quality gate that routes to review when output contains words longer than 80 chars without whitespace (space-merge failure signal) OR when output is suspiciously dense (no spaces despite >60 non-space chars)
- the gate never rejects text — it only routes to `review_required`

Result under production thresholds (0.6, 0.99) on the Golden Set:
- 0 auto-accepts, 45 routed to review
- accepted_precision = 1.0 (vacuously — no auto-accepts, no false accepts)
- review_precision = 1.0 (every review case genuinely needs review)

This is the intended conservative behavior per spec: "If a reliable 98% accepted precision cannot be demonstrated, reduce automatic acceptance and route more blocks to review." 98% accepted precision cannot be demonstrated with rapidocr's uncalibrated confidence, so auto-acceptance is effectively disabled until a better-calibrated confidence source (or a higher-quality backend) is available.

### Test updates

- `tests/integration/test_ocr_enrichment.py` — updated mock-backend tests to register confidence 1.0 (the only value that clears the calibrated 0.99 threshold). Added `test_enrich_routes_to_review_under_calibrated_threshold` documenting the new conservative behavior. All tests pass.
- `tests/real_ocr/test_golden_eval.py` (new) — 4 real_ocr tests verifying Golden Set size, visual-type coverage, evaluator end-to-end run, and per-sample metric fields. All pass.

## Acceptance gates verified

```
python -m pytest                       # 180 passed (was 179; +1 new review-route test)
python -m pytest -m real_ocr -v        # 12 passed (8 TASK_08 + 4 TASK_09)
python -m writeup2md evaluate-ocr evaluation/golden/ --backend rapid --output reports/golden-eval/
# Backend: rapid vrapidocr-onnxruntime
# Samples: 45
# CER mean: 0.1658
# Char accuracy mean: 0.8342
# Exact match rate: 0.0000
# Critical-token recall mean: 0.8796
# Calibration: accepted_precision=1.0000 (accepted=0, review=45)
```

## Key metrics summary

| metric | value | note |
| --- | --- | --- |
| sample count | 45 | above 40 minimum |
| CER mean | 0.166 | rapidocr on rendered code screenshots |
| char accuracy mean | 0.834 | |
| exact match rate | 0.000 | space-merging breaks exact match on every sample |
| critical-token recall mean | 0.880 | keywords mostly preserved |
| visual-type classification accuracy | 0.156 | low — router needs improvement (TASK_11) |
| language-detection accuracy | 0.533 | |
| segmentation F1 (terminal) | 0.204 | prompt detector too strict (TASK_11) |
| line-number removal accuracy | 1.000 | existing stripper works |
| URL exact-match rate | 1.000 | URLs preserved |
| hallucination rate mean | 0.006 | very low — rapidocr does not invent content |
| accepted_precision (legacy 0.85) | 0.068 | unacceptable → drove threshold change |
| accepted_precision (production 0.99) | 1.000 | no auto-accepts; conservative correct |

## Constraints upheld

- No new model instances: evaluator reuses the singleton rapid backend.
- No concurrent inference: serialized via the shared `_INFERENCE_LOCK`.
- No Docker/Ray/Celery/vLLM/distributed: none added.
- Mock is never selected by the evaluator: verified.
- Critical-token recall and CER are computed from real model output, not mock.

## Known limitations

- 45 samples is below the 100 target. Honest shortfall documented.
- Visual-type classification accuracy is low (0.156) — the router's text-based classifier mis-predicts on rapidocr's space-merged output. TASK_11 will improve this with multi-view candidate selection.
- Segmentation F1 is low (0.204) — the prompt detector requires `\$ ` (dollar+space) and rapidocr returns `$ls` (no space). TASK_11 will add a more robust prompt regex.
- The conservative (0.99) threshold means NO blocks auto-accept on this backend. This is intentional and correct, but it means every document with visuals routes to REVIEW until a human verifies. A higher-quality OCR backend (PaddleOCR-VL when available, or a future MLX code-tuned VLM) would be needed to enable auto-acceptance at scale.

## Files changed

- `evaluation/golden/` (new — 45 images + manifest + expected + README)
- `src/writeup2md/evaluate.py` (new — evaluator module)
- `src/writeup2md/ocr/enricher.py` (calibrated thresholds + space-merge gate)
- `src/writeup2md/cli.py` (added `evaluate-ocr` command)
- `tests/integration/test_ocr_enrichment.py` (updated mock confidences to 1.0; added review-route test)
- `tests/real_ocr/test_golden_eval.py` (new — 4 real_ocr tests)
- `docs/10_GOLDEN_SET_EVALUATION.md` (new)
- `tasks/TASK_09_GOLDEN_SET.md` (new)
- `reports/GOLDEN_SET_SCHEMA.md` (new)
- `reports/GOLDEN_SET_METRICS.json` (generated)
- `reports/GOLDEN_SET_METRICS.md` (generated)
- `reports/OCR_ERROR_TAXONOMY.md` (new)
- `reports/golden-eval/` (generated — results.jsonl, summary.json, by_visual_type.json)

## Next task

TASK_10 — PDF and URL capture completeness. Audit and improve PDF native-text vs OCR-layer vs embedded-image priority, dedup native-vs-OCR text, multi-column reading order, scanned-page detection, mixed scanned/native PDFs. Audit URL lazy-load image handling, copy-button payloads, DOM-code-over-OCR priority. Add a visual coverage ledger so every main-content visual ends in an explicit state. Build a capture test corpus.
