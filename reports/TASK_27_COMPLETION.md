# TASK_27 Completion — Complete 212-page Book Acceptance

Round 4 — Full-Book PDF Compilation.

## Summary

Processed the complete 212-page `A Bug Hunter's Diary` PDF with page-level
checkpointing, demonstrated controlled interruption after 30 verified pages,
resumed without page slicing, and produced one complete `document.md`.

## Source

- Path: `test_samples/A Bug Hunters Diary - A Guided Tour Through the Wilds of Software Security (Tobias Klein) (z-library.sk, 1lib.sk, z-lib.sk).pdf`
- PyMuPDF page count: 212
- SHA-256 before/after: `85c1b2cc4afde5357f79d29dc0ccbd1cf3d3684f2f5935eb767c48d00854a2ed`

## Backend Identity

- Backend: `paddleocr-vl-element`
- Model repo: `PaddlePaddle/PaddleOCR-VL`
- Model revision: `baee27eebcbf26cdeab160116679d765f13a3f27`
- Runtime: PyTorch MPS
- OCR concurrency: 1
- Silent fallback count: 0

## Commands Run

Doctor:

```bash
python -m writeup2md doctor --require-paddleocr-vl
```

Controlled interruption after 30 verified pages:

```bash
python - <<'PY'
from pathlib import Path
from writeup2md.config import Profile, build_config
from writeup2md.pdf_checkpoint import convert_pdf_checkpointed
cfg = build_config(Profile.MACBOOK)
cfg.ocr.backend = "paddleocr-vl-element"
convert_pdf_checkpointed(
    source="<resolved A Bug Hunter's Diary path>",
    output_root=Path("outputs/full_book_release"),
    config=cfg,
    force=True,
    resume=True,
    stop_after_verified_pages=30,
)
PY
```

Resume complete book with no page range:

```bash
python -m writeup2md \
  "test_samples/A Bug Hunters Diary - A Guided Tour Through the Wilds of Software Security (Tobias Klein) (z-library.sk, 1lib.sk, z-lib.sk).pdf" \
  --output outputs/full_book_release \
  --resume
```

## Results

| Metric | Value |
| --- | ---: |
| pages_total | 212 |
| pages_visited | 212 |
| pages_verified | 212 |
| pages_failed | 0 |
| page_sequence_gaps | 0 |
| visuals_total | 59 |
| visuals_represented | 59 |
| visuals_uncertain | 3 |
| visuals_missing | 0 |
| Markdown chars | 381,229 |
| Markdown file bytes | 383,301 |
| Markdown image syntax | 0 |
| HTML img tags | 0 |
| Base64 images | 0 |
| Unclosed fences | 0 |
| PaddleOCR-VL fallback count | 0 |
| pages_suspicious | 14 |
| full_document_completeness.passed | true |
| final document status | review |

Output:

`outputs/full_book_release/a-bug-hunters-diary-a-guided-tour-throug-85c1b2cc/document.md`

## Interruption and Resume

- Controlled interruption happened after exactly 30 verified pages.
- Exit code: 130.
- Resume command was printed.
- Verified pages remained intact.
- Resume completed pages 31-212.
- Final compilation used all 212 verified page shards.

## Performance

- Performance logs: `reports/FULL_BOOK_PERFORMANCE.jsonl`
- Current summary: `reports/FULL_BOOK_PERFORMANCE.md`
- Peak RSS observed: 4,077,633,536 bytes.
- Memory did not show uncontrolled linear growth: RSS peaked during warm VLM
  processing and later returned to roughly 1.0-1.8 GB during the same run.

## Manual Review

Manual review report:

`reports/FULL_BOOK_212_MANUAL_REVIEW.md`

Key outcome: output is complete and usable, but final status remains `review`
because 3 important visual blocks are uncertain/unresolved.

## Files Changed During TASK_27

- `src/writeup2md/__main__.py` — fixed `python -m writeup2md SOURCE` to use
  the same `cli.main()` shorthand path as the installed `writeup2md` script.
- `reports/FULL_BOOK_212_MANUAL_REVIEW.md`
- `reports/TASK_27_COMPLETION.md`
- `reports/PROJECT_STATE.md`

## Known Limitations

- Some TOC entries are rendered as code fences because the native PDF layout is
  dot-leader-heavy and code-like.
- Some command-like lines are over-promoted to headings.
- Three visual blocks require review; they are surfaced, not missing.
- Several pages are suspicious due to repeated OCR characters or chatty visual
  descriptions. These are listed in `full_document_completeness.json`.

## Next Step

Proceed to TASK_28: process the complete `From Day Zero to Zero Day` and
`漏洞战争` books with no page ranges.
