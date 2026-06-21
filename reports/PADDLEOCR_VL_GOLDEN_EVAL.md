# PaddleOCR-VL Golden Set Evaluation (TASK_15)

## Command

```bash
python -m writeup2md evaluate-ocr evaluation/golden/ \
    --backend paddleocr-vl-element \
    --output reports/golden-eval-paddleocr-vl
```

## Backend identity

- Backend name: `paddleocr-vl-element`
- Backend version: `0.9B-element`
- Model repo: `PaddlePaddle/PaddleOCR-VL`
- Model revision (commit SHA): `baee27eebcbf26cdeab160116679d765f13a3f27`
- Pipeline version: `element` (HF transformers element-mode VLM)
- Full pipeline: `False`
- Device: `mps`
- transformers: `4.55.0`
- torch: `2.12.0`
- huggingface_hub: `0.36.2`

## Summary

| Metric | Value |
| --- | ---: |
| Sample count | 45 |
| CER mean | 0.0338 |
| CER min | 0.0000 |
| CER max | 0.2909 |
| Char accuracy mean | 0.9662 |
| Exact match rate | 0.4444 |
| Exact line match rate | 0.4444 |
| Missing line rate mean | 0.2507 |
| Extra line rate mean | 0.2251 |
| Indentation exact match rate | 0.7556 |
| Critical-token recall mean | 0.9133 |
| Visual-type classification accuracy | 0.3111 |
| Language detection accuracy | 0.6667 |
| Segmentation F1 mean | 1.0000 |
| Line-number removal accuracy | 1.0000 |
| URL exact match rate | 1.0000 |
| Hallucination rate mean | 0.0016 |
| Digit accuracy mean | 0.9810 |

### Punctuation accuracy

| Punctuation class | Accuracy |
| --- | ---: |
| quotes | 0.9926 |
| brackets | 0.9906 |
| slash/backslash | 0.9956 |
| underscore/hyphen | 0.9861 |
| colon/semicolon | 1.0000 |
| equals | 0.9778 |
| pipe | 1.0000 |
| at | 0.9944 |
| hash | 1.0000 |
| dollar | 1.0000 |

### Leading whitespace accuracy

- Mean: 0.8859

## Per-visual-type breakdown

| Visual type | Samples | CER mean | Char accuracy | Exact match |
| --- | ---: | ---: | ---: | ---: |
| code | 23 | 0.0309 | 0.9691 | — |
| terminal | 3 | 0.0000 | 1.0000 | — |
| http | 5 | 0.0145 | 0.9855 | — |
| diff | 3 | 0.1336 | 0.8664 | — |
| configuration | 6 | 0.0328 | 0.9672 | — |
| log | 3 | 0.0252 | 0.9748 | — |
| traceback | 2 | 0.0314 | 0.9686 | — |

**Observations:**

- `terminal` is perfectly transcribed (CER 0.0000).
- `http` is near-perfect (CER 0.0145).
- `log`, `traceback`, `configuration` are all < 0.04 CER.
- `code` (the largest category, 23 samples) is at 0.0309 CER — a 5.4×
  improvement over RapidOCR's 0.17 on the same set.
- `diff` is the worst category (0.1336 CER). The `+`/`-` line prefixes
  appear to confuse the model — some lines are dropped or merged.
  This is a known weakness to address in a future round (possibly by
  using the `table` or `chart` task prompt instead of `OCR:`).

## Calibration

- accepted_precision: 1.0000 (convention — see PADDLEOCR_VL_VS_RAPID.md)
- accepted_count: 0
- review_count: 0

PaddleOCR-VL element mode does not produce per-region confidence
scores. The downstream enricher's conservative threshold + structural
gate still apply and continue to route low-quality output to
`review_required`.

## Identity verification

Every inference recorded the exact model identity in
`OcrBackendInfo`:

- `model_repo = "PaddlePaddle/PaddleOCR-VL"`
- `model_revision = "baee27eebcbf26cdeab160116679d765f13a3f27"`
- `pipeline_version = "element"`
- `full_pipeline = False`
- `mock_used = False`
- `rapid_used_as_primary = False`
- `fallback_used = ""`

Verified by `tests/real_paddleocr_vl/test_smoke_inference.py::test_element_backend_smoke_inference_records_identity`.

## Files

- `reports/golden-eval-paddleocr-vl/summary.json`
- `reports/golden-eval-paddleocr-vl/results.jsonl` (45 per-sample records)
- `reports/golden-eval-paddleocr-vl/by_visual_type.json`
- `reports/GOLDEN_SET_METRICS.json` (overwritten with latest run)
- `reports/GOLDEN_SET_METRICS.md` (overwritten with latest run)

> Note: `reports/GOLDEN_SET_METRICS.{json,md}` are overwritten by
> every `evaluate-ocr` run. The PaddleOCR-VL numbers in those files
> at the time of this report match the values above. Re-running
> `evaluate-ocr --backend rapid` will overwrite them with RapidOCR
> numbers.
