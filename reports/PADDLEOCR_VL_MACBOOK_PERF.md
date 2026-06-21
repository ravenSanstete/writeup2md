# PaddleOCR-VL MacBook Performance (TASK_15)

## Hardware

- Machine: Apple Silicon arm64 (MacBook Pro)
- OS: macOS 15.7.3
- CPU cores: 14
- Device used by PaddleOCR-VL: `mps` (Metal Performance Shaders)

## Software

- Python: 3.12.7
- torch: 2.12.0
- transformers: 4.55.0 (matches the model's `transformers_version` config)
- huggingface_hub: 0.36.2
- Model: `PaddlePaddle/PaddleOCR-VL` @ `baee27eebcbf26cdeab160116679d765f13a3f27`

## Cold start

- Model load (weights → MPS): 5.14 s
- First inference (includes JIT warmup): 1.25 s
- Total cold (load + first inference): 6.39 s

## Warm inference

Measured on 5 Golden Set samples after the model is warm:

| Sample | Latency |
| --- | ---: |
| code_py_dark_01.png | 0.78 s |
| code_bash_01.png | 0.48 s |
| http_request_01.png | 0.62 s |
| config_yaml_01.png | 0.60 s |
| diff_unified_01.png | 0.71 s |
| **Mean** | **0.64 s** |
| **Min** | **0.48 s** |
| **Max** | **0.78 s** |

## Golden Set total

- 45 samples, warm model, MPS device.
- Mean per-sample: ~0.64 s (warm).
- Total wall-clock for `evaluate-ocr` on 45 samples: dominated by
  the first load (6.4 s) + 45 × 0.64 s ≈ 35 s plus eval overhead.

## Resource budget verification

| Constraint (CLAUDE.md) | Status |
| --- | --- |
| One model instance per process | Verified — singleton via `_INSTANCE_LOCK` in `ocr/backend.py` |
| One inference at a time | Verified — `_INFERENCE_LOCK` serializes all `recognize` calls |
| Max 2 batch workers | Unchanged from Round 2 (default 1) |
| No Docker/vLLM/Ray | Verified — pure torch + transformers on MPS |
| Sequential PDF pages | Unchanged from Round 2 |
| Lazy Streamlit loading | Unchanged from Round 2 |
| Do not run large-corpus benchmarks as part of tests | Golden Set eval is opt-in (`-m real_paddleocr_vl`), not part of default `pytest` |

## Comparison: RapidOCR on same hardware

| Metric | PaddleOCR-VL (element, MPS) | RapidOCR (CPU) |
| --- | ---: | ---: |
| Cold start (load + first infer) | 6.39 s | ~1.0 s |
| Warm inference (mean) | 0.64 s | ~0.10 s |
| Memory footprint | ~2 GB (0.9B params, float16) | ~200 MB |
| CER on Golden Set | 0.0338 | 0.1658 |

PaddleOCR-VL is ~6× slower per inference and uses ~10× more memory
than RapidOCR, but produces 4.9× lower CER. For a single-user
MacBook workflow where accuracy matters more than throughput, this
is the right tradeoff.

## Acceptable use cases

- Single-document conversion via `convert`: ~6 s cold, <1 s warm
  per visual block. Acceptable.
- Batch with `--workers 1`: ~0.64 s per visual block. A 38-document
  corpus with ~80 visual blocks would add ~50 s of OCR latency over
  the Round 2 baseline (which used RapidOCR).
- Streamlit UI: warm inference is fast enough for interactive review.
- Tests: real_paddleocr_vl tests are opt-in and not part of the
  default `pytest` run.

## Unacceptable use cases

- Batch with `--workers 2` and `paddleocr-vl-element`: the singleton
  model + single-inference-lock means the second worker would block.
  Use `--workers 1` (the default) for PaddleOCR-VL.
- Real-time OCR of video streams: warm latency is 0.5–0.8 s per
  frame — too slow for video.
