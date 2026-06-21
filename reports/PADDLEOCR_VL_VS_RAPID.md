# PaddleOCR-VL vs RapidOCR — Golden Set head-to-head (TASK_15)

## Setup

- Golden Set: 45 hand-verified samples across 7 visual types and 13
  languages (see `evaluation/golden/manifest.jsonl`).
- PaddleOCR-VL backend: `paddleocr-vl-element` (HF transformers element
  mode, `AutoModelForCausalLM`, `do_sample=False`, MPS device).
- RapidOCR backend: `rapidocr-onnxruntime` 1.4.4 (the auxiliary
  backend).
- Same evaluation harness (`evaluate-ocr`), same metrics.
- Commands:

  ```bash
  python -m writeup2md evaluate-ocr evaluation/golden/ \
      --backend paddleocr-vl-element \
      --output reports/golden-eval-paddleocr-vl

  python -m writeup2md evaluate-ocr evaluation/golden/ \
      --backend rapid \
      --output reports/golden-eval-rapid
  ```

## Headline numbers

| Metric | PaddleOCR-VL (element) | RapidOCR | Δ (Paddle - Rapid) |
| --- | ---: | ---: | ---: |
| CER mean | **0.0338** | 0.1658 | -0.1320 (4.9× lower) |
| Char accuracy mean | **0.9662** | 0.8342 | +0.1320 |
| Exact match rate | **0.4444** | 0.0000 | +0.4444 (20/45 perfect) |
| Exact line match rate | **0.4444** | 0.0000 | +0.4444 |
| Critical-token recall mean | **0.9133** | 0.8796 | +0.0337 |
| Indentation exact match rate | **0.7556** | (n/a) | — |
| Punctuation accuracy (quotes) | **0.9926** | low | — |
| Digit accuracy mean | **0.9810** | (n/a) | — |
| Hallucination rate | 0.0016 | (n/a) | near zero |
| accepted_precision | 1.0000 | 1.0000 | 0 (both conservative) |
| accepted_count | 0 | 0 | 0 |
| review_count | 0 | 45 | -45 (PaddleOCR-VL's calibration runs differently) |

**Verdict.** PaddleOCR-VL is **dramatically more accurate** than
RapidOCR on this Golden Set. The character-error rate drops by a
factor of 4.9×. 20 of 45 samples are transcribed perfectly (vs zero
for RapidOCR). The dominant RapidOCR error mode — space-merging
(`import requests` → `importrequests`) — is essentially gone with
PaddleOCR-VL.

## Per-visual-type breakdown (PaddleOCR-VL)

| Visual type | Samples | CER mean | Char accuracy |
| --- | ---: | ---: | ---: |
| code | 23 | 0.0309 | 0.9691 |
| terminal | 3 | 0.0000 | 1.0000 |
| http | 5 | 0.0145 | 0.9855 |
| diff | 3 | 0.1336 | 0.8664 |
| configuration | 6 | 0.0328 | 0.9672 |
| log | 3 | 0.0252 | 0.9748 |
| traceback | 2 | 0.0314 | 0.9686 |

PaddleOCR-VL is perfect on terminal samples, near-perfect on http,
log, traceback, and configuration. Its worst category is `diff`
(0.1336 CER) — diff syntax with `+`/`-` line prefixes appears to be
the hardest visual pattern.

## Calibration note

PaddleOCR-VL (element mode) does not produce per-region confidence
scores — the VLM generation returns free-form text with no attached
probabilities. The `evaluate-ocr` calibration block therefore shows
`accepted_count=0, review_count=0` (the threshold check has nothing
to gate on). This is a known limitation of element-mode VLMs. The
production threshold + structural-quality gate from TASK_09 still
apply downstream (in the enricher) and continue to route low-quality
output to `review_required`.

The `accepted_precision=1.0` line shown for PaddleOCR-VL is the
"no-false-accepts" guarantee, computed as `0/0 ≡ 1.0` by convention.
It is not a meaningful calibration signal for this backend.

## Latency (MacBook Pro, Apple Silicon, MPS)

| Backend | Cold (load + first inference) | Warm inference (mean) | Warm (min/max) |
| --- | ---: | ---: | ---: |
| PaddleOCR-VL (element) | 6.39 s | 0.64 s | 0.48–0.78 s |
| RapidOCR | ~1.0 s (model load) | ~0.1 s | — |

PaddleOCR-VL is ~6× slower per inference than RapidOCR on the
MacBook. This is expected for a 0.9B VLM running on MPS. For the
writeup2md use case (conservative threshold routes most blocks to
review anyway), the latency is acceptable.

## When to use which

- **Production default (`auto`)**: PaddleOCR-VL element mode, because
  accuracy is the dominant factor and the latency is acceptable.
- **Smoke tests / unit tests that need any real OCR**: RapidOCR,
  because it is fast and its dependencies are lighter.
- **Tests that exercise PaddleOCR-VL specifically**: mark with
  `@pytest.mark.real_paddleocr_vl` and use `paddleocr-vl-element`.

## Files

- `reports/golden-eval-paddleocr-vl/summary.json` — full PaddleOCR-VL metrics.
- `reports/golden-eval-paddleocr-vl/results.jsonl` — per-sample.
- `reports/golden-eval-paddleocr-vl/by_visual_type.json` — per-type.
- `reports/golden-eval-rapid/summary.json` — RapidOCR baseline.
- `reports/golden-eval-rapid/results.jsonl` — per-sample.
