# TASK_09 — Golden Set and Real OCR Evaluation

## Goal

Build a versioned Golden Set of visual-block samples with known ground-truth
text, implement an `evaluate-ocr` command that runs a real OCR backend over
the set and computes accuracy metrics by visual type, calibrate confidence
thresholds against real accuracy, and produce an error taxonomy.

## Deliverables

1. `evaluation/golden/manifest.jsonl` — one JSON line per sample:
   ```json
   {
     "sample_id": "...",
     "source_document": "...",
     "source_type": "pdf|url|html|image",
     "visual_type": "code|terminal|http|diff|configuration|log|traceback|other",
     "language": "python",
     "image_path": "images/example.png",
     "gold_verbatim": "exact visible text",
     "gold_segments": [],
     "line_numbers_present": false,
     "line_numbers_should_be_removed": false,
     "cropped": false,
     "dark_theme": false,
     "critical_tokens": ["..."],
     "notes": ""
   }
   ```
2. `evaluation/golden/images/` — screenshot fixtures (the 10 from TASK_08
   plus additional samples generated to reach ≥40 high-quality manually
   verified samples).
3. `evaluation/golden/expected/` — one `<sample_id>.txt` per sample with the
   exact gold verbatim text (mirror of `gold_verbatim` for tooling).
4. `evaluation/golden/documents/` — optional longer-form ground-truth
   documents used as additional samples.
5. `evaluation/golden/README.md` — composition notes, diversity coverage,
   honest shortfall statement if <100 samples.
6. `reports/GOLDEN_SET_SCHEMA.md` — formal schema doc.
7. `src/writeup2md/evaluate.py` — evaluator module:
   - loads manifest
   - runs the named backend over each image
   - computes metrics globally and by visual_type
   - writes JSON + Markdown reports
8. CLI: `writeup2md evaluate-ocr evaluation/golden/ --backend rapid --output reports/golden-eval/`
9. `reports/GOLDEN_SET_METRICS.json` and `reports/GOLDEN_SET_METRICS.md`.
10. `reports/OCR_ERROR_TAXONOMY.md` — concrete error categories with examples.
11. Confidence calibration audit with threshold recommendations; conservative
    tuning if 98% accepted precision is not demonstrable.

## Metrics

Global and per-visual-type:
- character error rate (CER)
- normalized character accuracy
- exact full-sample match
- exact line match
- missing-line rate
- extra-line rate
- indentation exact match
- leading-whitespace accuracy
- punctuation accuracy (quotes, brackets, slash/backslash, underscore/hyphen)
- digit accuracy
- URL exact match
- hash exact match
- critical-token recall
- visual-type classification accuracy
- language-detection accuracy
- command/output segmentation precision, recall, F1
- editor line-number removal accuracy
- hallucinated-character rate (chars in output not in gold or plausible alternates)

## Calibration

Audit current confidence scoring. Use the Golden Set to evaluate:
- accuracy for blocks marked accepted
- accuracy for blocks marked review
- accuracy for blocks marked rejected
- false-accept rate
- false-review rate
- confidence vs actual character accuracy
- confidence vs critical-token accuracy

Tune thresholds conservatively. Priority: high precision for automatically
accepted code. If 98% accepted precision cannot be demonstrated, reduce
automatic acceptance and route more blocks to review.

## Acceptance gates

- ≥40 high-quality manually verified samples present (or honest shortfall
  documented).
- `evaluate-ocr` runs end-to-end with the rapid backend.
- Metrics JSON and Markdown produced.
- Error taxonomy file produced with concrete categories.
- Threshold recommendations documented; if changes are made to the enricher
  thresholds, the changes are explained and the test suite still passes.
