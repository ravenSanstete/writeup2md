# CLI Specification

## Command: convert

```bash
writeup2md convert SOURCE [OPTIONS]
```

Examples:

```bash
writeup2md convert tutorial.pdf
writeup2md convert https://example.com/writeup
writeup2md convert article.html --profile strict
```

Important options:

- `--output PATH`
- `--profile fast|default|strict|macbook`
- `--device auto|cpu|gpu`
- `--resume/--no-resume` — for PDFs, reuse verified page shards when the
  existing workspace is compatible.
- `--restart-failed` — retry failed PDF page shards during resume.
- `--general-vlm disabled|auto|openai-compatible|mock` — optional non-code
  visual analysis endpoint. Default is disabled and PDF processing must not
  require it.
- `--ocr-backend NAME` — `auto` (default), `paddleocr-vl`, `paddleocr-vl-element`, `rapid`, `mlx`, `mock`.
- `--require-exact-backend` — raise `BackendIdentityError` instead of falling back. When set with `--ocr-backend auto`, the resolved backend must be PaddleOCR-VL.
- `--force`
- `--keep-evidence/--no-keep-evidence`
- `--open-ui`

Expected completion output:

```text
Status: ACCEPTED
Markdown: outputs/<id>/document.md
Review UI: writeup2md ui outputs/<id>
```

## Command: batch

```bash
writeup2md batch INPUT [OPTIONS]
```

MacBook-safe default:

```bash
writeup2md batch INPUT --workers 1 --resume --profile macbook
```

Accepted inputs:

- directory;
- newline-delimited URL file;
- JSONL manifest;
- mixed JSONL containing local paths and URLs.

Important options:

- `--recursive`
- `--workers N` (default `1`; values above `2` must be rejected by the MacBook profile)
- `--resume`
- `--retry N`
- `--profile`
- `--include GLOB`
- `--exclude GLOB`
- `--ocr-backend NAME` — same semantics as `convert`.
- `--require-exact-backend` — same semantics as `convert`.

Batch output:

```text
outputs/
├── accepted/
├── review/
├── rejected/
├── failed/
├── batch_manifest.jsonl
└── batch_summary.json
```

## Command: inspect

```bash
writeup2md inspect outputs/<document_id>
```

Prints source, status, quality metrics, unresolved blocks and artifact paths.

## Command: status

```bash
writeup2md status outputs/<document_dir>
```

Prints page-level checkpoint progress for a full-book PDF conversion:

```text
Pages total: 212
Verified: 84
Processing: 1
Pending: 126
Failed: 1
Last completed page: 84
```

PDF conversion writes durable page shards under `pages/000001/`,
`pages/000002/`, and so on. Verified shards are skipped by `--resume`.
The final user-facing output remains one `document.md`.

## Command: ui

```bash
writeup2md ui outputs/
writeup2md ui outputs/<document_id>
```

Launches the Streamlit application.

## Command: doctor

```bash
writeup2md doctor
```

Checks Python, PaddlePaddle, PaddleOCR-VL model availability, Playwright browser, output permissions and optional GPU runtime.

TASK_15 flags:

- `--require-ocr` — exit nonzero if no real OCR backend can run.
- `--require-paddleocr-vl` — exit nonzero if PaddleOCR-VL (full or element) cannot run. Use this before batch runs that must use the production backend.
- `--ocr-backend NAME` — probe a specific backend instead of `auto`.
- `--require-exact-backend` — combined with `--ocr-backend`, require the named backend (or PaddleOCR-VL when `auto`) and raise on mismatch.
- `--smoke-ocr PATH` — load the real model and run one inference on PATH. Accepts `--ocr-backend NAME` and `--require-exact-backend` to target a specific backend. Writes raw output JSON to `reports/doctor_smoke_ocr.json`.

Example smoke test against the production backend:

```bash
writeup2md doctor --smoke-ocr evaluation/golden/images/code_py_light_01.png \
    --ocr-backend paddleocr-vl-element --require-exact-backend
```

## Exit codes

- `0`: completed and accepted;
- `2`: completed but review required;
- `3`: rejected by quality gates;
- `4`: input or configuration error;
- `5`: execution failure.

## Resource-safe semantics

`--workers` controls lightweight source orchestration and must default to `1`. OCR concurrency remains `1` regardless of worker count in v1. The implementation must not create a PaddleOCR-VL instance for each worker. Batch processing must use bounded queues and persist state after each source.

## OCR backend selection

| Backend | Mode | Apple Silicon | Notes |
| --- | --- | --- | --- |
| `auto` | probe | — | Prefers `paddleocr-vl` → `paddleocr-vl-element` → `rapid` → `mlx`. Never picks `mock`. |
| `paddleocr-vl` | full pipeline | blocked | Requires `paddleocr` + `paddlepaddle` (no arm64 wheels on macOS). |
| `paddleocr-vl-element` | HF transformers element | **working (MPS)** | Production backend on this MacBook. Identity-pinned to `baee27eebcbf26cdeab160116679d765f13a3f27`. |
| `rapid` | CPU ONNX | working | Auxiliary backend; faster (~6×) but 4.9× higher CER than PaddleOCR-VL. |
| `mlx` | mlx-vlm | experimental | Uses paligemma, not PaddleOCR-VL. |
| `mock` | built-in | — | Test-only. Never selected by `auto`. |

`--require-exact-backend` raises `BackendIdentityError` if the resolved
backend does not match the request. This is the strict contract used
for production conversion: no silent fallback to RapidOCR as a primary
backend.

## Optional general VLM

The generic VLM path is optional and disabled by default. It is only for
non-code visuals such as diagrams, flowcharts, charts, complex UI screenshots,
and unknown non-code imagery. Source code, terminal, HTTP, diff, configuration,
logs, and stack traces remain PaddleOCR-VL responsibilities.

Environment variables:

```bash
export WRITEUP2MD_VLM_BASE_URL="..."
export WRITEUP2MD_VLM_API_KEY="..."
export WRITEUP2MD_VLM_MODEL="..."
```

API keys must never be written to manifests, reports, logs, or evidence.
