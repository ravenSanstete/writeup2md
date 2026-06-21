# TASK_24 Completion — Cross-page Reconstruction

Round 4 — Full-Book PDF Compilation.

## Summary

Added a conservative cross-page reconstruction pass during final compilation
from page shards. The final `document.md` is no longer only a raw page-shard
concatenation: repeated page furniture can be removed, prose can continue
across page boundaries, and code blocks can merge across adjacent pages when
the evidence is strong.

## Files Changed

- `src/writeup2md/reconstruction.py`
- `src/writeup2md/pdf_checkpoint.py`
- `tests/unit/test_reconstruction.py`
- `reports/TASK_24_COMPLETION.md`
- `reports/PROJECT_STATE.md`

## Implemented Behavior

- Repeated header/footer/page-number candidates are detected by normalized text,
  similar page-edge position, and recurrence across many pages.
- Removed repeated elements are persisted in
  `reconstruction_removed.jsonl` with page, block, text, reason, and evidence
  count.
- Repeated code is not removed solely because it repeats.
- Cross-page prose paragraphs merge only when adjacent pages and prose
  continuation signals agree.
- Prose-only cross-page dehyphenation converts cases like `send-` + `ing` to
  `sending`.
- Dehyphenation is skipped for code-like text, URLs, command-line flags, paths,
  and identifiers.
- Native code blocks merge across adjacent pages when language matches and
  syntactic/indentation continuation is likely.
- The pass does not invent missing content or complete code.

## Tests Run

```bash
python -m pytest tests/unit/test_reconstruction.py \
  tests/integration/test_pdf_checkpointing.py -q
# 15 passed

python -m writeup2md convert tests/fixtures/pdf/writeup.pdf \
  --output /tmp/w2m_task24_smoke --ocr-backend mock --force
# Status: ACCEPTED
```

## Known Limitations

- Heading hierarchy is still heuristic and will be improved by real full-book
  inspection during TASK_27/TASK_28.
- TOC-specific duplicate suppression is not yet deeply modeled.
- Cross-page table/list/session merging remains conservative; unreliable
  structures are preserved rather than rewritten.

## Next Step

Proceed to TASK_25: full-document completeness and anomaly detection.
