# Golden Set OCR Metrics

- Backend: `paddleocr-vl-element` v0.9B-element
- Is mock: `False`
- Sample count: `45`

## Aggregate metrics

- CER mean: `0.0338` (min `0.0000`, max `0.2909`)
- Character accuracy mean: `0.9662`
- Exact full-sample match rate: `0.4444`
- Exact line match rate: `0.4444`
- Missing-line rate mean: `0.2507`
- Extra-line rate mean: `0.2251`
- Indentation exact-match rate: `0.7556`
- Leading-whitespace accuracy mean: `0.8859`
- Digit accuracy mean: `0.9810`
- Critical-token recall mean: `0.9133`
- Visual-type classification accuracy: `0.3111`
- Language-detection accuracy: `0.6667`
- Segmentation F1 (terminal): `1.0000`
- Line-number removal accuracy: `1.0000`
- URL exact-match rate: `1.0000`
- Hash exact-match rate: n/a
- Hallucination rate mean: `0.0016`

## Punctuation accuracy (mean)

- `quotes`: `0.9926`
- `brackets`: `0.9906`
- `slash_backslash`: `0.9956`
- `underscore_hyphen`: `0.9861`
- `colon_semicolon`: `1.0000`
- `equals`: `0.9778`
- `pipe`: `1.0000`
- `at`: `0.9944`
- `hash`: `1.0000`
- `dollar`: `1.0000`

## Metrics by visual type

| visual_type | n | CER mean | char_acc | exact_match | crit_recall | vtype_acc |
| --- | --- | --- | --- | --- | --- | --- |
| code | 23 | 0.0309 | 0.9691 | 0.6087 | 0.9167 | 0.0000 |
| configuration | 6 | 0.0328 | 0.9672 | 0.3333 | 0.9444 | 0.8333 |
| diff | 3 | 0.1336 | 0.8664 | 0.0000 | 0.5333 | 0.6667 |
| http | 5 | 0.0145 | 0.9855 | 0.2000 | 1.0000 | 0.6000 |
| log | 3 | 0.0252 | 0.9748 | 0.0000 | 0.9167 | 0.3333 |
| terminal | 3 | 0.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| traceback | 2 | 0.0314 | 0.9686 | 0.0000 | 1.0000 | 0.0000 |

## Confidence calibration (current production thresholds low=0.6, high=0.99)

- accepted_count: `0`
- review_count: `0`
- rejected_count: `45`
- accepted_precision: `1.0000`
- review_precision: `1.0000`
- false_accept_count: `0`
- false_review_count: `0`
- accepted_mean_cer: n/a
- review_mean_cer: n/a

## Legacy thresholds (low=0.6, high=0.85) — kept for comparison

- accepted_count: `0`
- accepted_precision: `1.0000`
- false_accept_count: `0`

The legacy 0.85 threshold admitted blocks with mean CER ~0.17 (accepted_precision 0.07), which is why the production threshold was raised to 0.99.

## Recommendation

Under the calibrated (0.6, 0.99) thresholds, no blocks auto-accept on this Golden Set. This is the intended conservative behavior: rapidocr's confidence is uncalibrated (mean 0.94 on samples with mean CER 0.17), so the priority of high accepted-precision is met by routing everything to human review until a better-calibrated confidence source (or a higher-quality backend) is available.
