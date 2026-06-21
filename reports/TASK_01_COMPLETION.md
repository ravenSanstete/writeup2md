# TASK_01 Completion Report — Foundation and Data Contracts

## Status

Complete. All acceptance commands pass.

## Files created or changed

- `pyproject.toml` — packaging, dependencies, optional extras, pytest config.
- `README.md` — quick start, commands, output layout, profiles, MacBook budget.
- `src/writeup2md/__init__.py`, `__main__.py`, `py.typed`.
- `src/writeup2md/config.py` — typed `WriteupConfig` with `fast`/`default`/`strict`/`macbook` profiles, `enforce_macbook_limits`, `config_sha256`.
- `src/writeup2md/models.py` — Pydantic IR: `Document`, `SourceRecord`, `Manifest`, `Block`, `EnrichedVisual`, `EvidenceRef`, `Provenance`, `Diagnostics`, `QualityReport`. Deterministic document IDs, source canonicalization, content hashes, zero-padded block IDs.
- `src/writeup2md/workspace.py` — document directory layout, atomic byte/text/JSON writers, JSONL append/replace.
- `src/writeup2md/render.py` — pure-text Markdown renderer, image-reference stripping (markdown / HTML img / base64), editor line-number stripping (conservative).
- `src/writeup2md/quality.py` — quality gates, status calculation, diagnostics builder.
- `src/writeup2md/provenance.py` — per-block provenance ledger builder.
- `src/writeup2md/doctor.py` — environment checks (python, packages, paddleocr_vl, playwright chromium, output dir).
- `src/writeup2md/cli.py` — Typer CLI: `convert`, `batch`, `inspect`, `ui`, `doctor`, `version`. Exit codes 0/2/3/4/5 per spec.
- `src/writeup2md/pipeline.py` — single-source orchestrator with source-type detection and adapter dispatch.
- `src/writeup2md/adapters/{__init__,url,pdf,html}.py` — adapter stubs raising `NotImplementedError` (filled in later tasks).
- `src/writeup2md/batch.py` — batch summary dataclass + stub (filled in TASK_05).
- `src/writeup2md/inspect_cmd.py` — `writeup2md inspect` reads manifest/diagnostics/document.md and prints summary.
- `src/writeup2md/ui_runner.py` and `src/writeup2md/ui/{__init__,app}.py` — Streamlit launcher + stub app (filled in TASK_06).
- `tests/conftest.py` — sys.path bootstrap.
- `tests/unit/test_models.py`, `test_workspace.py`, `test_config.py`, `test_render.py`, `test_quality.py`, `test_cli.py`.

## Design decisions

- Default profile is `macbook`, not `default`, so a bare `writeup2md convert x.pdf` is MacBook-safe out of the box.
- `Document.diagnostics` is `Optional` because diagnostics are derived at the end of the pipeline; constructing a Document mid-pipeline should not require fabricated diagnostics.
- The renderer exposes `render_markdown(document, strip_images=True)`; quality gates use `strip_images=False` to detect leaked image syntax in the raw render and reject accordingly.
- `count_image_references` counts on raw text (no internal stripping) so the quality gate catches pre-strip leakage.
- `OcrConfig.model_instances` and `max_concurrent_inference` are validated to be `1` at the model layer, preventing accidental concurrency increases.
- `enforce_macbook_limits` is called from the CLI before any work starts, so an over-limit `--workers` value fails fast with a configuration error rather than mid-pipeline.
- Deterministic document IDs mix `canonical_source + content_sha256 + config_sha256`, so a config change produces a new document slot and resume/skip stays correct.
- Block IDs are zero-padded to 6 digits (`b_000123`) for stable sort order up to one million blocks.

## Test results

```
python -m pytest
======================== 61 passed, 5 warnings in 0.97s ========================
```

Acceptance commands:

- `python -m pytest` — pass (61 tests).
- `python -m writeup2md --help` — lists all required commands.
- `python -m writeup2md doctor` — runs, reports python 3.12.7, all required packages OK, optional paddleocr_vl reported as `missing` (intended — it is lazy-loaded at runtime).

## Known limitations

- `convert`, `batch` and `ui` raise `NotImplementedError` (or stub Streamlit message) by design — they are implemented in TASK_02 through TASK_06.
- `doctor` reports `paddleocr_vl` as missing because the real PaddleOCR-VL backend is implemented and isolated in TASK_04.
- The CLI `version` command is an addition beyond the spec; it does not conflict with required commands.

## Recommended next task

TASK_02 — URL Native Extraction. Implement Playwright capture, article-container selection, DOM-order block extraction, native code extraction, image evidence capture, and Markdown generation for native content using the unified IR.
