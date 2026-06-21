# TASK_07 Completion Report — End-to-End Release Acceptance

## Status

Complete. All MacBook resource contracts hold end-to-end. All seven tasks (TASK_01 through TASK_07) are delivered. The project converts PDF, URL and local HTML into image-free Markdown with provenance, raw evidence preservation, separate human revisions, and a Streamlit review UI that never loads the OCR model.

## Acceptance gates verified

### Automated tests

```
python -m pytest
======================= 171 passed, 5 warnings in 0.93s ========================
```

Acceptance suite (TASK_07):

```
python -m pytest tests/integration/test_acceptance.py -v
======================== 16 passed, 5 warnings in 0.55s ========================
```

The 16 acceptance tests verify every MacBook resource contract:

- Default worker count is 1 under the macbook profile.
- macbook profile rejects `workers > 2` and accepts `workers == 2`.
- OCR `model_instances == 1` and `max_concurrent_inference == 1`.
- `heavy_queue_capacity <= 2`.
- One backend instance reused across calls (`get_backend` returns same object).
- The inference lock is serialized across threads (cannot be acquired twice).
- PDF pages are processed sequentially (`max_concurrent == 1`).
- Final Markdown contains no `![`, no `<img`, no `data:image/`.
- Raw evidence and raw OCR output unchanged after human revision (SHA-256 snapshot).
- Batch resume does not duplicate outputs (`skipped == prior total`, directory set unchanged).
- CLI help lists `convert`, `batch`, `inspect`, `ui`, `doctor`.
- Config JSON contains no `docker`, `ray`, `celery`, `kubernetes`, `vllm` strings.
- Importing `writeup2md.ui.app` does NOT load `writeup2md.ocr.backend` or `paddleocr_vl`.
- Every output directory contains the full required layout (`document.md`, `document.json`, `manifest.json`, `diagnostics.json`, `provenance.jsonl`, `raw/`, `evidence/`, `review/`).
- Every Markdown block maps to exactly one provenance record.

### Doctor

```
python -m writeup2md doctor
```

All required checks OK. `paddleocr_vl` reported as missing/optional (not installed locally; the backend gracefully falls back to `review_required` with a recorded warning, never faking success).

### End-to-end single-source

```
python -m writeup2md convert tests/fixtures/pdf/writeup.pdf --ocr-backend mock --profile macbook
# Status: ACCEPTED  (outputs/43497b47bdc69dbe/document.md)

python -m writeup2md convert tests/fixtures/html/tutorial.html --ocr-backend mock --profile macbook
# Status: REVIEW    (outputs/20af767e33bcaf27/document.md)
```

The HTML case lands in REVIEW because the mock backend has no registered OCR for its visual blocks. Under the real PaddleOCR-VL backend, those blocks would be enriched and the status would advance. The behavior is correct per the no-fake-success rule: low-confidence or unavailable visual blocks surface as `review_required`.

### End-to-end batch + resume

```
python -m writeup2md batch sources.jsonl --output /tmp/w2m_final/batch \
  --ocr-backend mock --profile macbook
# Batch complete: 2 sources
#   accepted=1 review=1 rejected=0 failed=0

python -m writeup2md batch sources.jsonl --output /tmp/w2m_final/batch \
  --ocr-backend mock --profile macbook
# Batch complete: 2 sources
#   accepted=0 review=0 rejected=0 failed=0   (both skipped)
```

Resume is deterministic: when content hash + config hash + manifest.json all match the prior run, the source is skipped and no new output directory is created.

### Image-free guarantee

Across all generated `document.md` files (single-source PDF, single-source HTML, both batch outputs):

- Markdown image syntax (`![`): 0
- HTML `<img>` tags: 0
- Base64 `data:image/` strings: 0

### Raw evidence immutability

Verified by `test_raw_evidence_unchanged_after_human_revision`: SHA-256 hashes of every file under `evidence/` plus `document.json` and `document.md` are snapshotted before a human revision is applied, and asserted identical after. Revisions land only in `review/review_state.json` and `review/revisions.jsonl`. The original `document.md` is never mutated.

### Streamlit UI isolation

Verified by `test_streamlit_launch_does_not_load_ocr_model`: importing `writeup2md.ui.app` does not import `writeup2md.ocr.backend` or `writeup2md.ocr.paddleocr_vl`. The UI is read/review only.

## Files created or changed in TASK_07

- `tests/integration/test_acceptance.py` — 16 end-to-end acceptance tests covering every MacBook resource contract.
- `reports/TASK_07_COMPLETION.md` — this file.
- `reports/FINAL_IMPLEMENTATION_REPORT.md` — final consolidated report.
- `reports/PROJECT_STATE.md` — updated to reflect project completion.

## Known limitations

Carried over from earlier tasks (see `reports/TASK_06_COMPLETION.md` and `FINAL_IMPLEMENTATION_REPORT.md`):

- No cross-document full-text search in the Streamlit UI.
- No keyboard shortcuts for prev/next review blocks (buttons work).
- No evidence image zoom control.
- Dashboard table not column-sortable.
- Human review status is not bubbled back into `manifest.json` (separation preserved per spec).
- PaddleOCR-VL is not bundled with the package; when absent, visual blocks correctly surface as `review_required` rather than being faked.

## Recommended next step

The project is release-complete. Optional future improvements (clearly separate from required functionality):

- Bundle a `paddleocr_vl` install extra with pinned versions.
- Add cross-document full-text search to the UI.
- Add a zoom component for evidence images.
- Surface human review status into a separate review summary (without mutating the original manifest).
