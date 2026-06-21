# TASK_23 Completion — Long-document Runtime

Round 4 — Full-Book PDF Compilation.

## Summary

Added bounded long-document runtime configuration and lightweight performance
instrumentation for full-book PDF conversion. Each completed page can emit a
runtime sample to `reports/FULL_BOOK_PERFORMANCE.jsonl`, with the latest
summary mirrored to `reports/FULL_BOOK_PERFORMANCE.md`.

## Files Changed

- `src/writeup2md/config.py`
- `src/writeup2md/performance.py`
- `src/writeup2md/pdf_checkpoint.py`
- `tests/unit/test_performance.py`
- `docs/08_MACBOOK_EXECUTION.md`
- `reports/TASK_23_COMPLETION.md`
- `reports/PROJECT_STATE.md`

## Runtime Policy

Configured Round 4 defaults:

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

Mandatory invariants are enforced by config validators:

- PaddleOCR-VL model instances: `1`
- OCR concurrency: `1`

The implementation remains conservative: one active page transaction is held
at a time, and the VLM is never invoked concurrently.

## Instrumentation

Recorded fields include:

- process RSS;
- peak RSS;
- elapsed seconds;
- pages per minute;
- estimated remaining seconds;
- OCR calls;
- OCR latency;
- active page buffers;
- temporary/page disk size;
- evidence disk size;
- model loads;
- retries;
- current page and total pages.

`psutil` is used when available. Otherwise the recorder falls back to the
standard-library `resource` module. MPS memory is not fabricated.

## Selective Rendering

The existing PDF adapter already avoids rendering every page: native text pages
with no scanned-page signal are extracted from text objects; embedded source
images are used directly; scanned pages are rendered only when native text is
insufficient. The Round 4 checkpoint runner preserves this behavior.

## Tests Run

```bash
python -m pytest tests/unit/test_config.py \
  tests/unit/test_performance.py \
  tests/integration/test_pdf_checkpointing.py -q
# 20 passed

python -m writeup2md convert tests/fixtures/pdf/writeup.pdf \
  --output /tmp/w2m_task23_smoke --ocr-backend mock --force

tail -n 5 reports/FULL_BOOK_PERFORMANCE.jsonl
cat reports/FULL_BOOK_PERFORMANCE.md
```

## Known Limitations

- TASK_23 does not yet prove long-run leak behavior at pages 25/50/100/200 on
  a real full book. That measurement will be produced during TASK_27 and
  TASK_28 full-book runs.
- CPU-stage parallelism is represented in configuration but the current page
  transaction remains sequential to keep page checkpointing simple and safe.

## Next Step

Proceed to TASK_24: cross-page document reconstruction.
