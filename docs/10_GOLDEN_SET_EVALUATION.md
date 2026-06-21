# Golden Set OCR Evaluation

## Overview

The Golden Set is a versioned corpus of visual-block samples with known
ground-truth text, used to measure real OCR backend accuracy and calibrate
confidence thresholds. It lives under `evaluation/golden/`.

## Composition

45 hand-verified samples covering 7 visual types (code, configuration, http,
terminal, diff, log, traceback) and 13 languages. See
`reports/GOLDEN_SET_SCHEMA.md` for the formal schema and
`evaluation/golden/README.md` for composition notes.

## Running the evaluation

```bash
writeup2md evaluate-ocr evaluation/golden/ --backend rapid --output reports/golden-eval/
```

Outputs:
- `reports/golden-eval/results.jsonl` — per-sample metrics
- `reports/golden-eval/summary.json` — aggregate
- `reports/golden-eval/by_visual_type.json` — per-visual-type aggregates
- `reports/GOLDEN_SET_METRICS.json` — canonical copy
- `reports/GOLDEN_SET_METRICS.md` — human-readable summary

## Metrics computed

Global and per-visual-type:
- character error rate (CER)
- normalized character accuracy
- exact full-sample match rate
- exact line match rate
- missing/extra line rates
- indentation exact-match rate
- leading-whitespace accuracy
- punctuation accuracy (quotes, brackets, slash/backslash, underscore/hyphen,
  colon/semicolon, equals, pipe, at, hash, dollar)
- digit accuracy
- URL exact-match rate
- hash exact-match rate
- critical-token recall
- visual-type classification accuracy
- language-detection accuracy
- terminal command/output segmentation F1
- editor line-number removal accuracy
- hallucinated-character rate

## Confidence calibration

The evaluator runs calibration under two threshold sets:
- **Production** (low=0.6, high=0.99): the calibrated policy in `enricher.py`.
- **Legacy** (low=0.6, high=0.85): kept for comparison.

### Findings on rapidocr-onnxruntime 1.4.4 (this Mac)

Under legacy (0.6, 0.85) thresholds:
- 44 of 45 samples auto-accepted by confidence
- accepted_precision = 0.07 (mean CER 0.17 in the accepted bucket)
- 41 false accepts

This is unacceptable. The production policy raises `high` to 0.99 and adds a
structural-quality gate (space-merge detection). Under production thresholds:
- 0 of 45 samples auto-accept
- 45 routed to review
- accepted_precision = 1.0 (vacuously — no auto-accepts, no false accepts)

This is the intended conservative behavior. Rapidocr's per-region confidence
is not a calibrated probability (mean 0.94 on samples with mean CER 0.17),
so the priority of high accepted-precision is met by routing everything to
human review until a better-calibrated confidence source or a higher-quality
backend is available.

## Error taxonomy

See `reports/OCR_ERROR_TAXONOMY.md` for the full categorization with
concrete examples. Top categories on this Golden Set:

1. Space-merge failure (23/45) — dominant error mode
2. Missing space after keyword (18/45) — subset of (1)
3. Fullwidth Chinese punctuation substitution (13/45)
4. Indentation collapse (~40% of samples)
5. Newline loss (1/45, low-res only)
6. Command/output merge (terminal samples)

## Test markers

```bash
python -m pytest -m real_ocr -v   # includes Golden Set eval tests
```

Golden Set evaluation tests verify:
- ≥40 samples present
- required visual types covered
- evaluator runs end-to-end on rapid backend
- per-sample metrics have required fields
- production calibration produces no false accepts
