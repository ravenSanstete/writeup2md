# TASK_16 — Test-sample inventory and end-to-end baseline

## Goal

Inventory `test_samples/`, run the unmodified production pipeline
against every processable sample with the PaddleOCR-VL backend and
`require_exact_backend=true`, inspect the resulting Markdown, and
produce a sample-level defect ledger that drives TASK_17–TASK_20.

## Non-goals

- Do not modify any file under `test_samples/` — it is immutable source data.
- Do not use RapidOCR as the primary backend.
- Do not introduce fixes during TASK_16 — this is a measurement task.

## Inputs

`test_samples/` is a directory of 7 PDF books (no HTML, URLs, or
manifests at the time of writing). The books range from 212 to 845
pages and total 3,456 pages.

Because the corpus is large and PaddleOCR-VL inference is ~0.64 s per
visual on MPS, a full end-to-end run of every page of every book would
take hours. To keep iteration tractable:

1. The inventory records every file in `test_samples/` and the full
   page count for each PDF.
2. The baseline converts a **page-range sample** of each book (the
   first N pages that carry native text and at least one visual block,
   plus a scanned-page sample where the book has any). The page range
   is chosen so that each book contributes a representative slice
   without consuming the full corpus.
3. The final release pass (TASK_21) runs the complete books.

## Deliverables

### Inventory

- `reports/TEST_SAMPLES_INVENTORY.json` — one record per sample, plus
  summary counts.
- `reports/TEST_SAMPLES_INVENTORY.md` — human-readable summary.
- `reports/TEST_SAMPLES_MANIFEST.jsonl` — one JSON line per sample.

Every sample record carries:

```json
{
  "sample_id": "...",
  "source": "...",
  "source_type": "pdf|html|url|manifest|unsupported",
  "path": "...",
  "sha256": "...",
  "size_bytes": 0,
  "page_count": null,
  "asset_directory": null,
  "expected_processing": true,
  "notes": ""
}
```

### Baseline outputs

Outputs are written under `outputs/e2e_baseline/` and never under
`test_samples/`.

For each converted sample, record:

- command;
- exit code;
- processing time;
- output path;
- document status;
- page count processed;
- native text block count;
- native code block count;
- visual block count;
- transcribed visual count;
- unresolved visual count;
- failed visual count;
- Markdown character count;
- Markdown code-block count;
- warnings and errors.

Reports:

- `reports/E2E_BASELINE_RESULTS.json`
- `reports/E2E_BASELINE_RESULTS.md`

### Markdown defect ledger

Open and inspect every generated `document.md`. Detect and report:

- missing sections, missing pages, broken reading order;
- duplicated text, duplicated code;
- OCR content placed at the document end;
- missing screenshots, malformed code fences, incorrect code language;
- code and terminal output merged incorrectly;
- navigation/sidebar/footer contamination (PDF: running headers/footers);
- empty or suspiciously short documents;
- incorrect headings;
- tables lost or flattened badly;
- image placeholders remaining;
- raw OCR metadata leaking into Markdown.

Reports:

- `reports/E2E_BASELINE_DEFECTS.jsonl`
- `reports/E2E_BASELINE_DEFECTS.md`

Each defect carries:

```json
{
  "sample_id": "...",
  "severity": "critical|major|minor",
  "category": "...",
  "block_id": null,
  "page": null,
  "description": "...",
  "expected": "...",
  "actual": "...",
  "status": "open"
}
```

## Acceptance gates

1. `reports/TEST_SAMPLES_INVENTORY.{json,md}` exist and cover every
   file under `test_samples/`.
2. `reports/TEST_SAMPLES_MANIFEST.jsonl` has one line per sample.
3. `outputs/e2e_baseline/` contains a document directory for every
   processable sample.
4. `reports/E2E_BASELINE_RESULTS.{json,md}` exist with per-sample
   outcomes.
5. `reports/E2E_BASELINE_DEFECTS.{jsonl,md}` exist with at least one
   defect per observed issue.
6. PaddleOCR-VL is the actual backend used (no silent RapidOCR
   fallback) — verified in each `manifest.json`.
7. No file under `test_samples/` was modified.

## Next task

TASK_17 (visual asset recovery) uses the defect ledger to drive the
recovery-ladder implementation.
