# writeup2md

Convert technical tutorials and cybersecurity writeups from PDF or URL into high-quality, image-free Markdown. Code screenshots, terminal captures, HTTP transactions, diffs, configs, logs and stack traces become faithful textual Markdown blocks. Original evidence is preserved on disk for review.

## Install

```bash
pip install -e .
# Optional: install PDF / web / UI / OCR extras
pip install -e ".[all]"
playwright install chromium
```

For real OCR (Round 2):

```bash
pip install -e ".[ocr]"      # rapidocr-onnxruntime (default real backend)
python -m writeup2md doctor --require-ocr
```

For PaddleOCR-VL (TASK_15 — production backend on Apple Silicon):

```bash
# Element mode — runs on MPS, no PaddlePaddle runtime required.
pip install -e ".[paddleocr-vl-element]"
python -m writeup2md doctor --require-paddleocr-vl

# Or use the macOS setup script (handles element mode by default).
bash scripts/setup_paddleocr_vl_macos.sh element
```

Identity pin: `PaddlePaddle/PaddleOCR-VL` @ commit
`baee27eebcbf26cdeab160116679d765f13a3f27` (resolved via
`huggingface_hub.model_info()` and verified live on first load).

## Quick start

```bash
writeup2md convert tutorial.pdf --profile macbook
writeup2md convert "https://example.com/writeup" --profile macbook
writeup2md batch sources.jsonl --profile macbook --workers 1 --resume
writeup2md ui outputs/
```

You can also invoke the package directly:

```bash
python -m writeup2md convert tutorial.pdf --profile macbook
python -m writeup2md doctor
```

## Commands

| Command | Purpose |
| --- | --- |
| `convert SOURCE` | Convert one PDF, URL or local HTML file. |
| `batch INPUT` | Process a directory, URL list, or JSONL manifest. |
| `inspect RESULT_DIR` | Print source, status, quality metrics and artifact paths. |
| `inspect RESULT_DIR --export-reviews PATH` | Export human revisions as JSONL. |
| `ui [RESULT_ROOT]` | Launch the Streamlit review UI. |
| `doctor` | Check Python, dependencies, OCR backends, Playwright, output permissions. |
| `doctor --require-ocr` | Exit nonzero if no real OCR backend can run. |
| `doctor --require-paddleocr-vl` | Exit nonzero if PaddleOCR-VL cannot run. |
| `doctor --smoke-ocr PATH` | Run one real OCR inference on the given image. |
| `doctor --smoke-ocr PATH --ocr-backend NAME --require-exact-backend` | Smoke-test a specific exact backend (no silent fallback). |
| `evaluate-ocr GOLDEN_DIR` | Evaluate an OCR backend against the Golden Set. |

## Output layout

```text
outputs/<document_id>/
├── document.md          # final image-free Markdown
├── document.json        # full IR
├── manifest.json        # source identity and processing configuration
├── diagnostics.json     # quality metrics, warnings, errors, visual_coverage
├── provenance.jsonl     # one record per final Markdown block
├── raw/                 # immutable original source artifacts
├── evidence/            # immutable evidence assets (regions, elements)
│   ├── regions/
│   └── elements/
└── review/              # human revisions (never mutates raw evidence)
    ├── revisions.jsonl
    ├── review_state.json
    ├── document.reviewed.md
    └── exported_reviews.jsonl   # written by the UI's "Export reviews" button
```

`document.md` never contains Markdown image syntax, HTML `<img>` tags or Base64 images.

## OCR backends

| Backend | Marker | Description |
| --- | --- | --- |
| `auto` (default) | — | Probes `paddleocr-vl` → `paddleocr-vl-element` → `rapid` → `mlx`. Never picks `mock`. |
| `paddleocr-vl` | `[paddleocr-vl]` | PaddleOCR-VL 0.9B full official pipeline (`paddleocr.PaddleOCRVL()`). Requires `paddleocr` + `paddlepaddle`. |
| `paddleocr-vl-element` | `[paddleocr-vl-element]` | PaddleOCR-VL 0.9B HF transformers element mode on Apple Silicon MPS. **Production backend on this MacBook.** |
| `rapid` | `[real-ocr]` | rapidocr-onnxruntime — CPU, fast, calibrated against the Golden Set. Auxiliary only under `auto`. |
| `mlx` | `[mlx-ocr]` | mlx-vlm on Apple Silicon (experimental VLM path, paligemma — not PaddleOCR-VL). |
| `mock` | (none) | Test-only — returns canned results. Never selected by `auto`. |

`auto` prefers PaddleOCR-VL. On this MacBook `available_backends()`
returns `[paddleocr-vl-element, rapid, mlx]` — element mode first
because the full `paddleocr-vl` pipeline requires PaddlePaddle which is
not arm64-clean on macOS.

Identity contract: every PaddleOCR-VL inference records
`model_repo`, `model_revision` (pinned commit SHA), `pipeline_version`
(`"full"` or `"element"`), `full_pipeline`, `mock_used`,
`rapid_used_as_primary`, and `fallback_used` in `OcrBackendInfo`. The
production pin lives in `src/writeup2md/ocr/model_identity.py` and is
verified live via `huggingface_hub.model_info()` on first load.

Strict backend contract: `--require-exact-backend` raises
`BackendIdentityError` if `auto` resolves to a non-PaddleOCR-VL backend
or if an explicitly named backend is unavailable. No silent fallback
to RapidOCR as a primary backend.

Golden Set CER (TASK_15):

| Backend | CER | Exact matches |
| --- | ---: | ---: |
| `paddleocr-vl-element` (MPS) | **0.0338** | 20/45 |
| `rapid` (CPU) | 0.1658 | 0/45 |

PaddleOCR-VL is 4.9× more accurate than RapidOCR on the Golden Set.
RapidOCR remains the right choice when throughput matters more than
accuracy (select it explicitly with `--ocr-backend rapid`).

Production thresholds (set in TASK_09): high-confidence = 0.99, plus a
structural-quality gate that detects space-merging. Together these
achieve `accepted_precision = 1.0` on the Golden Set (no false accepts).

## Source priority

The pipeline prefers native text over OCR whenever native text is available.

**PDF**: native text > hidden OCR text layer > embedded image > rendered crop > whole-page OCR.

**URL/HTML**: DOM `<pre>/<code>` > copy-button / clipboard payload > raw source > hidden accessible text (`aria-hidden`, `sr-only`, `<textarea readonly>`) > image OCR > screenshot OCR.

Native-vs-OCR duplicates are detected via normalized-text comparison
and dropped, so a code block is never transcribed twice.

## Visual coverage ledger

Every visual block ends in exactly one explicit state, recorded in
`diagnostics.json` under `visual_coverage`:

| State | Meaning |
| --- | --- |
| `transcribed` | OCR produced text, accepted or routed to review. |
| `native_text_used` | Native PDF text or DOM code used instead of OCR. |
| `decorative_with_reason` | Image classified as decorative (class/alt/dimension hints). |
| `duplicate_with_reference` | Image duplicates native text/DOM, reference recorded. |
| `review_required` | Could not be resolved; needs human review. |
| `failed_with_diagnostic` | Pipeline error; diagnostic recorded. |

## Code-aware OCR (Round 2)

When OCR runs on a code/terminal/HTTP/diff/config/log/stack-trace
image, the pipeline applies:

- **Multi-view retry** (5 preprocessing pipelines: original, grayscale,
  upscale_2x, adaptive_threshold, invert_dark).
- **Candidate selection** by structural score (bracket balance, keyword
  density, line length, space ratio, visual-type tokens).
- **Code-aware postprocessing** — keyword-boundary splitting (~80
  conservative rules), fullwidth punctuation normalization (code context
  only), indentation recovery.
- **Multi-panel splitting** — terminal command/output, HTTP
  request/response, diff file/hunk/content.

No semantic repair: characters are never invented, completed, or
rearranged. Verified by a real-OCR test that checks the output is a
subsequence of the input.

## Batch resume + freshness (Round 2)

- `--resume` (default): skip documents whose cached result is still fresh.
- File edit detection: re-hashes the source and compares to the cached `content_sha256`.
- URL sources default to fresh (no network call). Stored `etag` /
  `last_modified` are available for future opt-in HEAD checks.
- `--force-refresh`: bypass cache freshness checks; always re-process.
- `--max-age SECONDS`: treat cached results as fresh if younger than SECONDS.
- Partial-state recovery: an interrupted run leaves `<doc_id>.partial.<timestamp>`
  directories for forensic inspection — never silently deletes user data.
- 1-worker and 2-worker runs produce identical Markdown output
  (document IDs differ because `workers` is part of the config hash).

## Review workflow (Round 2)

The Streamlit UI supports:

- **Full-text search** across all documents (token TF ranking + quoted-phrase substring match + CJK chunk preservation).
- **Filters**: status, source type, coverage state, confidence range.
- **Sort**: by document_id, status, captured_at, visual_count.
- **Within-document filters** (OCR Review tab): visual type, coverage state, confidence range.
- **Zoom**: full-resolution evidence image + download button.
- **Diff**: unified diff between raw OCR output and the corrected text.
- **Keyboard navigation**: `j/k` next/prev document, `n/p` next/prev visual block, `/` focus search, `Enter` accept block. (Progressive enhancement — on-screen buttons remain primary.)
- **Export**: in-UI button writes `outputs/<doc_id>/review/exported_reviews.jsonl`; `inspect RESULT_DIR --export-reviews PATH` writes JSONL from the CLI.

Export payload: one `review_state` record (status, verified_blocks,
corrections, notes) plus one `revision` record per human edit. The
original `document.md`, raw OCR output, and evidence assets are never
modified by the UI.

## Profiles

- `macbook` (default): one worker, one OCR model instance, one OCR inference at a time, sequential PDF pages, lazy Streamlit loading.
- `strict`: macbook limits plus max workers forced to 1.
- `default`: macbook limits with the default profile label.
- `fast`: skip evidence retention (still no images in output).

## MacBook resource budget

- Default batch workers: `1`. Hard maximum: `2`.
- One OCR model instance per process.
- One OCR inference at a time.
- One Playwright browser, one active page per source.
- PDF pages rendered sequentially.
- Bounded queues (capacity ≤ 2) between heavy stages.
- Streamlit lazy-loads the selected document and selected evidence image.

See `docs/08_MACBOOK_EXECUTION.md` for the full resource contract.

## Documentation

- `docs/01_INPUT_FORMATS.md` — PDF / URL / HTML input handling.
- `docs/02_OUTPUT_LAYOUT.md` — output directory structure.
- `docs/03_IR_DESIGN.md` — unified intermediate representation.
- `docs/04_CLI_SPEC.md` — command reference.
- `docs/05_QUALITY_MODEL.md` — quality metrics and thresholds.
- `docs/06_PROVENANCE.md` — provenance and traceability.
- `docs/07_REVIEW_WORKFLOW.md` — review-store contract.
- `docs/08_MACBOOK_EXECUTION.md` — resource contract.
- `docs/09_REAL_OCR_SETUP.md` — real OCR backend setup.
- `docs/10_GOLDEN_SET_EVALUATION.md` — Golden Set and `evaluate-ocr`.
- `docs/11_CAPTURE_COMPLETENESS.md` — PDF/URL source priority and coverage ledger.
- `docs/12_CODE_AWARE_OCR.md` — multi-view, candidate selection, postprocessing, panel splitting.
- `docs/13_RESUME_FRESHNESS.md` — batch resume freshness and failure recovery.
- `docs/14_REVIEW_WORKFLOW.md` — Streamlit review workflow (search, filters, zoom, diff, keyboard nav, export).

## Development

```bash
pip install -e ".[dev]"
python -m pytest                                  # 244 fast tests
python -m pytest -m real_ocr                      # 15 real-OCR tests (requires [real-ocr])
python -m pytest -m real_paddleocr_vl --timeout=600  # 14 PaddleOCR-VL tests (requires [paddleocr-vl-element])
python -m writeup2md doctor
```
