# AGENTS.md

## Project mission

Build `writeup2md`, a reliable command-line tool for converting technical tutorials and cybersecurity writeups from PDF or URL into high-quality, image-free Markdown.

The defining capability is code-aware visual enrichment: code screenshots, terminal screenshots, HTTP transactions, configuration snippets, diffs, logs and stack traces must become faithful textual Markdown blocks.

## Product principles

1. Prefer native text over OCR whenever native text is available.
2. Preserve original evidence even though final Markdown contains no images.
3. Never silently invent, complete or repair code.
4. Every derived block must be traceable to a PDF page, bounding box, DOM node or captured asset.
5. PDF and URL inputs must converge into one internal document representation.
6. Single-source usage must be one command. Batch usage must support resume and deterministic outputs.
7. Low-confidence visual content must be surfaced for review, never silently discarded.
8. Optimize for technical tutorials, CTF writeups, vulnerability analyses and exploit-development articles.

## Scope boundaries

### In scope

- PDF, URL and local HTML input.
- Native text and native code extraction.
- Replaceable OCR backend (`auto` / `rapid` / `paddleocr-vl` / `paddleocr-vl-element` / `mlx` / `mock`); `paddleocr-vl-element` is the production backend on Apple Silicon (TASK_15), `rapidocr-onnxruntime` is the auxiliary CPU backend.
- PaddleOCR-VL 0.9B identity pinning — exact HuggingFace commit SHA `baee27eebcbf26cdeab160116679d765f13a3f27`, verified live on first load.
- Strict `--require-exact-backend` contract — no silent fallback to RapidOCR as a primary backend under `auto`.
- Code, terminal, HTTP, diff, configuration, logs, stack traces and simple tables.
- Pure-text Markdown output.
- JSON provenance and diagnostics (including a visual coverage ledger).
- Streamlit review UI with full-text search, filters, zoom, diff, keyboard navigation, and review export.
- Single-source and batch CLI with resume freshness (`--force-refresh`, `--max-age SECONDS`).
- Golden Set evaluation (`evaluate-ocr`).

### Out of scope for the first release

- General-purpose website crawling.
- Authentication bypass or scraping protected content.
- Automatic semantic repair of code.
- Diagram-to-Mermaid conversion.
- Distributed execution.
- A database requirement.
- Editing the source documents.

## Required commands

The completed project must expose:

```bash
writeup2md convert SOURCE
writeup2md batch INPUT
writeup2md inspect RESULT_DIR
writeup2md ui [RESULT_ROOT]
writeup2md doctor
```

## Required output layout

```text
outputs/<document_id>/
├── document.md
├── document.json
├── manifest.json
├── diagnostics.json
├── provenance.jsonl
├── raw/
└── evidence/
```

`document.md` must not contain Markdown image syntax, HTML image tags or Base64 images.

## Source priority

Use this precedence order:

1. Web DOM native code and copy-button payloads.
2. PDF native text objects.
3. Existing PDF OCR text layer.
4. Extracted embedded-image region recognition.
5. Rendered page or element OCR.

Do not OCR content already available reliably as native text.

## Coding constraints

- Python 3.11+.
- Use typed code throughout.
- Use Pydantic models for public data contracts.
- Use Typer for CLI and Rich for terminal output.
- Use pathlib, not string path concatenation.
- Keep ingestion, IR, enrichment, rendering, quality and UI modules separate.
- Avoid global mutable state.
- Write atomically: temporary file, fsync where appropriate, then rename.
- Deterministic document IDs must be derived from canonical source identity and content hash.
- Never overwrite raw evidence without an explicit force flag.
- Do not add a database until file-based execution is proven insufficient.

## Development workflow

Before editing:

1. Read the current task file.
2. Read the affected design documents.
3. Inspect existing implementation and tests.
4. State the smallest coherent implementation plan.

During implementation:

1. Make one architectural change at a time.
2. Add or update tests with the implementation.
3. Keep data contracts backward compatible unless the task explicitly authorizes a schema version change.
4. Record unresolved assumptions in the task completion report.

Before declaring completion:

1. Run unit tests.
2. Run integration tests relevant to the task.
3. Run lint and type checking.
4. Run the acceptance commands listed in the task.
5. Inspect at least one generated artifact manually.
6. Produce `reports/TASK_XX_COMPLETION.md` with files changed, tests run, known limitations and next-step recommendation.

## Prohibited shortcuts

- Do not return placeholder OCR results as successful output.
- Do not discard images before classification.
- Do not inject captions or explanations not grounded in the source.
- Do not auto-fix syntax to improve parser scores.
- Do not mark a document accepted while unresolved important visuals remain.
- Do not hard-code fixture-specific behavior.
- Do not mix implementation of future phases into the active task.

## Quality vocabulary

Each document ends in exactly one state:

- `accepted`: all important content resolved and thresholds passed.
- `review`: usable output exists but one or more important blocks need inspection.
- `rejected`: output is incomplete or unreliable.
- `failed`: the pipeline did not complete.

Each visual block ends in exactly one state:

- `resolved_native`
- `resolved_ocr`
- `resolved_structured`
- `review_required`
- `ignored_decorative`
- `failed`

## Documentation discipline

When behavior changes, update the matching file in `docs/` in the same task. Do not let implementation become the only source of truth.

## Continuous execution mode

When the user starts the project with the prompt in `START_CLAUDE_CODE.md`, execute the task files sequentially from `TASK_01` through `TASK_07` without waiting for approval between tasks.

For each task:

1. Read the task and referenced design documents.
2. Inspect the current repository state.
3. Implement the smallest complete solution for the task.
4. Run the task acceptance commands and relevant tests.
5. Fix failures before proceeding.
6. Write the required completion report.
7. Update `reports/PROJECT_STATE.md` with the current status, important decisions, remaining work and exact next task.
8. Continue directly to the next task.

Do not stop after producing a plan, skeleton, audit or completion report. A task is complete only after its implementation and acceptance checks pass.

Do not ask routine implementation questions. Resolve ordinary ambiguity conservatively using the design documents, record the assumption, and continue. Ask the user only when progress is impossible without external credentials, unavailable source files, a legally or technically inaccessible dependency, or a product decision that would irreversibly contradict the written specification.

If one optional component is blocked, isolate it, document the limitation, complete all unblocked work, and continue. Never claim a blocked or untested feature is complete.

## MacBook Pro resource budget

This project is developed and run locally on a MacBook Pro. Resource safety takes precedence over throughput.

Mandatory defaults and limits:

- Batch worker default: `1`.
- Hard maximum workers in the MacBook profile: `2`.
- Tests must use `1` worker unless a test explicitly verifies worker configuration.
- Load only one PaddleOCR-VL model instance per process.
- Permit only one OCR inference at a time.
- Do not create one model instance per batch worker.
- Use one Playwright browser and at most one active page by default.
- Render PDF pages sequentially. Do not retain all rendered pages in memory.
- Use bounded queues with a default capacity no greater than `2` between heavy stages.
- Release page images, crops and browser resources immediately after persistence or use.
- Use lazy loading in Streamlit. Load only the selected document and selected evidence image.
- Do not scan or deserialize the full corpus on every Streamlit rerun.
- Do not introduce distributed execution, Ray, Celery, Kubernetes, Spark or a multi-process inference server.
- Do not require Docker for normal development or local use.
- Do not add vLLM or a persistent model server in v1.
- Avoid unbounded `asyncio.gather`, process pools and thread pools.
- Do not run large-corpus benchmarks automatically as part of tests or task acceptance.

Use adaptive quality rather than brute-force concurrency:

- Prefer native DOM/PDF text before OCR.
- Render PDF pages at a memory-conscious default resolution.
- Re-render only unresolved or low-confidence regions at higher resolution.
- Cache immutable source captures and OCR outputs by content hash.
- Resume work instead of recomputing completed documents.

Any change that increases default concurrency, creates duplicate model instances or loads a complete batch into memory requires an explicit design-document update and strong justification.

## End-to-end completion definition

The project is complete only when all task completion reports exist and `TASK_07_RELEASE_ACCEPTANCE.md` passes. At minimum:

- single PDF conversion works;
- single URL conversion works;
- mixed batch input works with `--resume` and one worker;
- OCR enrichment is integrated through a replaceable backend (`auto` / `rapid` / `paddleocr-vl` / `paddleocr-vl-element` / `mlx` / `mock`);
- final Markdown contains no image references;
- the Streamlit UI reads results, displays successful OCR blocks beside evidence, and stores human revisions separately;
- representative tests pass on a MacBook-safe configuration;
- installation and one-command usage are documented;
- `reports/FINAL_IMPLEMENTATION_REPORT.md` records validated commands, limitations and remaining optional improvements.

### Round 2 extensions

Round 2 (TASK_08 through TASK_14) extends the project to real OCR
validation, code-aware OCR optimization, batch resume freshness, and a
full Streamlit review workflow. At minimum:

- real OCR backend (`rapidocr-onnxruntime`) is the default, with `auto` selection;
- Golden Set (`evaluation/golden/`) of 45 hand-verified samples drives `evaluate-ocr`;
- production confidence threshold (0.99) + structural-quality gate yields `accepted_precision = 1.0` on the Golden Set;
- visual coverage ledger (6 canonical states) recorded in `diagnostics.json` under `visual_coverage`;
- PDF source priority (native > OCR layer > embedded image > rendered crop > whole-page OCR) with native-vs-OCR dedup;
- URL source priority (DOM code > copy-button > raw source > hidden accessible > image OCR > screenshot OCR) with DOM-code-over-OCR enforcement;
- code-aware OCR: multi-view retry, candidate selection, code-aware postprocessing, multi-panel splitting. No semantic repair;
- batch resume freshness: file edit detection, URL default-fresh, `--force-refresh`, `--max-age SECONDS`, partial-state recovery;
- 1-worker and 2-worker runs produce identical Markdown output;
- Streamlit review workflow: full-text search, filters (status / source type / coverage state / confidence range), sort, zoom, diff (raw OCR vs corrected), keyboard navigation, in-UI export button;
- `inspect RESULT_DIR --export-reviews PATH` writes JSONL of human revisions;
- `reports/ROUND_2_RELEASE_REPORT.md` records the real-source validation corpus, per-document outcomes, performance summary, and known limitations.

### Round 2 + TASK_15 extensions

TASK_15 promotes PaddleOCR-VL 0.9B to the production OCR backend on
Apple Silicon. The `auto` probe order now prefers PaddleOCR-VL, a
strict `--require-exact-backend` contract eliminates silent fallback
to RapidOCR as a primary backend, and every inference records the
exact HuggingFace commit SHA. At minimum:

- production OCR backend is `paddleocr-vl-element` (HF transformers element mode, MPS device);
- full pipeline `paddleocr-vl` is implemented and identity-verified but unverified on Apple Silicon (requires PaddlePaddle, not arm64-clean on macOS);
- identity pin `PaddlePaddle/PaddleOCR-VL` @ `baee27eebcbf26cdeab160116679d765f13a3f27` lives in `src/writeup2md/ocr/model_identity.py` and is verified live via `huggingface_hub.model_info()` on first load;
- `auto` probe order: `paddleocr-vl` → `paddleocr-vl-element` → `rapid` → `mlx`;
- `--require-exact-backend` raises `BackendIdentityError` on any mismatch (auto resolving to non-PaddleOCR-VL, or explicit backend unavailable);
- every inference writes raw JSON to `/tmp/writeup2md_paddleocr_vl_element_raw/` (or `/tmp/writeup2md_paddleocr_vl_raw/` for the full pipeline) and records the path in `OcrBackendInfo.raw_output_path`;
- `OcrBackendInfo` extended with `model_repo`, `model_revision`, `pipeline_version`, `full_pipeline`, `mock_used`, `rapid_used_as_primary`, `fallback_used`;
- Golden Set CER drops from 0.1658 (RapidOCR) to 0.0338 (PaddleOCR-VL element mode) — 4.9× improvement;
- `doctor --require-paddleocr-vl` exits nonzero when the backend cannot run;
- MacBook resource budget upheld: 1 model instance (`_INSTANCE_LOCK`), 1 inference at a time (`_INFERENCE_LOCK`), default 1 worker, no Docker/vLLM/Ray;
- `@pytest.mark.real_paddleocr_vl` marker added (separate from `real_ocr`);
- `reports/TASK_15_COMPLETION.md` records files changed, tests run, known limitations.
