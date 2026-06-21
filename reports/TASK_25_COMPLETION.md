# TASK_25 Completion — Full-document Completeness

Round 4 — Full-Book PDF Compilation.

## Summary

Extended full-document completeness reporting for page-checkpointed PDF
conversion. Every compiled PDF now writes `full_document_completeness.json`
and `full_document_completeness.md` with page-level records, hard invariants,
visual coverage totals, Markdown integrity checks, fallback counts, and
suspicious-page warnings.

## Files Changed

- `src/writeup2md/pdf_checkpoint.py`
- `tests/unit/test_full_document_completeness.py`
- `reports/TASK_25_COMPLETION.md`
- `reports/PROJECT_STATE.md`

## Implemented Behavior

Each page record includes:

- page state;
- native text chars;
- final page Markdown chars;
- visuals detected/represented/uncertain/missing;
- heading count;
- code block count;
- warnings.

The full-document report includes:

- `pages_total`, `pages_visited`, `pages_verified`, `pages_failed`;
- `pages_suspicious`;
- `page_sequence_gaps`;
- visual totals and missing counts;
- native text and final Markdown char counts;
- image syntax, HTML img, Base64 image, and unclosed fence counts;
- PaddleOCR-VL fallback count;
- `passed` hard-invariant result.

Suspicious-page detection now flags:

- substantial native text with very short Markdown;
- non-empty source with no extracted blocks;
- visuals detected with no representation;
- one-character-per-line patterns;
- extreme duplicated content;
- header/footer/page-number-only pages;
- chatty visual descriptions such as "The provided image...";
- repeated hallucinated character runs;
- abnormally high page processing time;
- page order mismatch.

## Tests Run

```bash
python -m pytest tests/unit/test_full_document_completeness.py \
  tests/integration/test_pdf_checkpointing.py -q
# 14 passed

python -m writeup2md convert tests/fixtures/pdf/writeup.pdf \
  --output /tmp/w2m_task25_smoke --ocr-backend mock --force
# full_document_completeness.json: passed=true, pages_suspicious=0
```

## Known Limitations

- Suspicious-page detection is intentionally conservative and advisory. It
  does not necessarily fail document-mode output.
- Real suspicious-page rates must be measured during TASK_27 and TASK_28
  complete-book runs.

## Next Step

Proceed to TASK_26: optional general VLM endpoint.
