# TASK_20 — One-command CLI and performance

## Goal

Make `writeup2md tutorial.pdf` work as a one-command conversion
(defaulting to `paddleocr-vl-element` with
`require_exact_backend=true` on Apple Silicon), produce
human-readable output directory names (`<slug>-<short_hash>` instead
of opaque 16-char hashes), raise the default render DPI to 300/450,
add progress display, and make `writeup2md batch test_samples/`
recursively discover sources.

This is the task that makes the product feel like the spec:
> Give `writeup2md` a PDF, local HTML file, or URL and receive one
> complete, readable, image-free Markdown document in a single
> command.

## TASK_16 defect findings driving this task

- **D10**: No one-command CLI. User must run `writeup2md convert
  SOURCE` and pass `--ocr-backend paddleocr-vl-element
  --require-exact-backend`.
- **D13**: No human-readable output dir. 16-char hashes are opaque.
- **D14**: Default render DPI low. 200/300 vs spec's 300/450.

## Implementation

### 20.A `writeup2md SOURCE` shorthand

Make `writeup2md SOURCE` an alias for `writeup2md convert SOURCE`.
This is the one-command UX. Use a Typer callback on the root app or
a single-command dispatch.

When no subcommand is given but a SOURCE argument is present, route
to `convert`. The existing `convert`, `batch`, `inspect`, `ui`,
`doctor` subcommands remain available.

### 20.B Default backend = paddleocr-vl-element with require_exact

On Apple Silicon (`platform.machine() == "arm64"` and
`platform.system() == "Darwin"`), the default OCR backend is
`paddleocr-vl-element` and `require_exact_backend=True` is the
default behavior (no flag needed).

On other platforms, the default remains `auto` (which probes for
whatever is installed).

Implementation:
- `cli.py` `convert`: if `--ocr-backend` is not specified AND we are
  on Apple Silicon, set `cfg.ocr.backend = "paddleocr-vl-element"`.
- `cli.py` `convert`: if `--require-exact-backend` is not specified
  AND we are on Apple Silicon AND backend is paddleocr-vl-element,
  set `require_exact_backend = True`.
- Document this in the help text.

### 20.C Human-readable output dir names

Output directories change from `<16-char-hash>` to
`<slug>-<short_hash>` where:
- `slug` is a filesystem-safe slug derived from the source filename
  (for PDFs/HTML) or the URL host + path (for URLs). Truncated to 40
  chars.
- `short_hash` is the first 8 chars of the content SHA-256.

Examples:
- `real-world-bug-hunting-a14c3f2e`
- `a-bug-hunters-diary-38bccb48`
- `example.com-article-9e8dc9dc`

The full 16-char hash is still stored in `manifest.json.document_id`
for backward compatibility; the directory name is the new
human-readable form.

Implementation:
- Add `slugify_source(source, source_type) -> str` to a new helper.
- Modify `document_dir()` resolution to use the new name. The
  `document_id` field in `manifest.json` is unchanged.
- Add a mapping file `outputs/.index.json` that maps
  `<slug>-<short_hash>` → full `<document_id>` for forensic lookup.

### 20.D 300/450 DPI default

Update `PdfConfig` defaults:
- `initial_render_dpi: int = 300` (was 200)
- `retry_render_dpi: int = 450` (was 300)

Update `_macbook_overrides()` to match.

### 20.E Progress display

Add a Rich progress display to `convert`:
- "Loading PDF..." (initial load)
- "Extracting native text (page N/M)..." (per-page)
- "Running OCR on N visuals..." (OCR phase)
- "Writing artifacts..." (finalize)

The progress display is disabled when stdout is not a TTY (so batch
mode and CI logs remain clean).

### 20.F Recursive batch discovery

`writeup2md batch test_samples/ --recursive` (or just
`writeup2md batch test_samples/` if the directory has no manifest)
walks the directory tree and discovers all `.pdf`, `.html`, `.htm`
files. URLs in a `.jsonl` manifest are also discovered.

The current `--recursive` flag exists; this task ensures it actually
walks the tree for directory inputs.

## Acceptance gates

1. `writeup2md tutorial.pdf` works (no `convert` subcommand needed).
2. On Apple Silicon, the default backend is `paddleocr-vl-element`
   with `require_exact_backend=true` (no flags needed).
3. Output directories are `<slug>-<short_hash>` (human-readable).
4. PDF default render DPI is 300 base / 450 retry.
5. Progress display shown in TTY mode.
6. `writeup2md batch test_samples/ --recursive` discovers all 7 PDFs.
7. The `outputs/.index.json` mapping file exists after a conversion.

## Next task

TASK_21 (e2e release acceptance) — run all 7 PDFs through the fixed
pipeline, verify strict-mode sample, verify UI load, produce the
final release report.
