# MacBook Pro Local Execution Design

## Objective

The default implementation must remain responsive and stable on a developer MacBook Pro. The system should trade throughput for bounded memory use, predictable thermals and reliable resume behavior.

## Default execution model

Use a sequential pipeline with bounded handoff:

```text
one source
  -> one fetch/parser operation
  -> one page or visual region
  -> one OCR inference
  -> deterministic post-processing
  -> atomic persistence
  -> release memory
  -> next item
```

Batch execution means iterating through multiple sources with durable state. It does not imply parallel model inference.

## Concurrency policy

| Component | Default | Hard design guidance |
|---|---:|---:|
| Batch source workers | 1 | Hard maximum 2 in the MacBook profile |
| PaddleOCR-VL instances | 1 | Never duplicate per worker |
| Concurrent OCR requests | 1 | Serialize with a semaphore/queue |
| Playwright browsers | 1 | Reuse one browser |
| Active Playwright pages | 1 | A second page is optional only with explicit configuration |
| PDF page rendering | up to 2 lightweight render tasks | Never several VLM generations concurrently |
| Heavy-stage queue capacity | 4 | Bounded backpressure |
| Streamlit selected documents | 1 | Lazy load |

The CLI may expose `--workers`, but its default must be `1`. Values above `2` must be rejected when the MacBook profile is active. The implementation may cap heavy OCR concurrency at `1` even when lightweight preprocessing uses two workers.

## Model lifecycle

- Initialize PaddleOCR-VL lazily on the first unresolved visual.
- Reuse the same model instance for the current process (module-level singleton guarded by `_INSTANCE_LOCK` in `src/writeup2md/ocr/backend.py`).
- Serialize all inferences with `_INFERENCE_LOCK` — one OCR inference at a time, regardless of worker count.
- Never reload the model for each page or document.
- Never fork after loading the model.
- Release intermediate tensors and image objects after each region.
- Keep the backend replaceable so a remote service can be added later without changing the IR.

## PaddleOCR-VL resource profile (TASK_15)

On this MacBook (Apple Silicon, 14 cores, macOS 15.7.3):

| Metric | PaddleOCR-VL element (MPS) | RapidOCR (CPU) |
| --- | ---: | ---: |
| Cold start (load + first inference) | 6.39 s | ~1.0 s |
| Warm inference (mean per image) | 0.64 s | ~0.10 s |
| Memory footprint | ~2 GB (0.9B params, float16) | ~200 MB |
| Golden Set CER | 0.0338 | 0.1658 |
| Device | `mps` | `cpu` |
| Per-region confidences | none (VLM free-form text) | yes |

Software versions verified end-to-end:

- torch 2.12.0
- transformers 4.55.0 (matches the model's `transformers_version` config)
- huggingface_hub 0.36.2
- Model `PaddlePaddle/PaddleOCR-VL` @ `baee27eebcbf26cdeab160116679d765f13a3f27`

A compatibility shim (`_apply_causal_mask_compatibility_shim`) translates
the legacy `inputs_embeds` kwarg used by the model's custom_code to the
`input_embeds` (singular) signature required by transformers 4.53+.
The shim is idempotent and is recorded in
`engine_version["causal_mask_shim_applied"]`.

### Acceptable use

- Single-document conversion: ~6 s cold, <1 s warm per visual block.
- Batch with `--workers 1` (the default): ~0.64 s per visual block.
- Streamlit UI review: warm inference is fast enough for interactive use.
- Tests: `real_paddleocr_vl` tests are opt-in (`-m real_paddleocr_vl`) and never part of the default `pytest` run.

### Unacceptable use

- Batch with `--workers 2` and `paddleocr-vl-element`: the singleton model + single-inference lock means the second worker would block. Use `--workers 1` (the default).
- Real-time OCR of video streams: warm latency 0.5–0.8 s per frame is too slow.
- Concurrent model instances: never create a second `PaddleOCRVL` instance in the same process.

## PDF memory strategy

- Inspect native text before rendering.
- Render one page at a time.
- Use a default of approximately 300 DPI for initial unresolved-page work.
- Re-render only low-confidence or small visual regions at up to approximately 450 DPI.
- Persist evidence to disk before advancing.
- Do not maintain a list of full-resolution page images in memory.
- For large PDFs, support page checkpoints so an interrupted run resumes from the first incomplete page.
- Emit long-document performance samples to
  `reports/FULL_BOOK_PERFORMANCE.jsonl` and a current summary to
  `reports/FULL_BOOK_PERFORMANCE.md`.

Round 4 exposes a measured runtime profile in configuration:

```yaml
runtime:
  page_prefetch: 2
  native_text_workers: 4
  image_decode_workers: 2
  normalization_workers: 2
  pdf_render_concurrency: 2
  ocr_model_instances: 1
  ocr_concurrency: 1
  page_write_concurrency: 1
  heavy_queue_capacity: 4
```

The current implementation remains conservative internally: one active PDF
page transaction is held at a time, but the configuration records the intended
bounded-resource envelope for long-document work. The invariant is strict:
PaddleOCR-VL model instances stay at `1` and OCR concurrency stays at `1`.

## URL memory strategy

- Reuse one Chromium browser.
- Create and close one page per source.
- Download original image bytes when possible instead of retaining large screenshots in memory.
- Capture element screenshots only for resources unavailable through DOM or network responses.
- Apply timeouts and close the page in `finally` blocks.
- Store rendered HTML and metadata before visual enrichment so OCR can resume without reopening the page.

## Batch state

The batch runner must persist state after each source. A simple file-backed manifest is preferred for v1. SQLite is acceptable only if it materially simplifies atomic resume behavior.

A batch interruption must not require reprocessing completed sources. Content and configuration hashes determine whether an output is reusable.

## Streamlit performance

The UI must not index all evidence images or parse every `document.json` on each rerun.

Use:

- a compact cached document index;
- pagination for document tables;
- lazy loading of the selected document;
- lazy loading of the selected OCR evidence image;
- bounded image display sizes with optional zoom;
- cached Markdown and diagnostics reads keyed by modification time;
- explicit cache refresh rather than repeated corpus scans.

Do not generate all thumbnails at application startup.

## Testing policy

- Unit and integration tests run with one worker.
- Use small local fixtures.
- Mock the OCR backend for most tests.
- Keep a very small optional real-model smoke test.
- Do not download the model automatically during ordinary unit tests.
- Do not run a corpus-wide benchmark as part of `pytest`.
- Mark expensive tests explicitly and document how to run them manually.
- `real_paddleocr_vl` tests are opt-in (`-m real_paddleocr_vl --timeout=600`), never part of the default `pytest` run. They reuse a single model instance across the test session.

## CLI defaults

Recommended default behavior:

```bash
writeup2md convert SOURCE --profile default
writeup2md batch INPUT --workers 1 --resume
writeup2md ui outputs/
```

A MacBook profile should be available:

```bash
writeup2md batch sources.jsonl \
  --profile macbook \
  --workers 1 \
  --resume
```

The profile should prioritize native extraction, sequential OCR, adaptive rendering and disk-backed checkpoints.

## Resource-related acceptance checks

The release acceptance must verify:

- default batch worker count is one;
- one model instance is reused across multiple visual regions;
- OCR calls are serialized;
- PDF rendering does not accumulate page images;
- Playwright pages are closed after each source;
- Streamlit opens a corpus index without loading all evidence images;
- interrupted sequential batch processing resumes without duplicate outputs.
