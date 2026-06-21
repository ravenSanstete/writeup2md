# TASK_26 Completion — Optional General VLM

Round 4 — Full-Book PDF Compilation.

## Summary

Added an optional, disabled-by-default generic multimodal VLM interface for
non-code visuals. It is not required for PDF processing and is not used for
code, terminal, HTTP, diff, configuration, log, or stack-trace visuals.

## Files Changed

- `src/writeup2md/config.py`
- `src/writeup2md/general_vlm.py`
- `src/writeup2md/cli.py`
- `tests/unit/test_general_vlm.py`
- `docs/04_CLI_SPEC.md`
- `reports/TASK_26_COMPLETION.md`
- `reports/PROJECT_STATE.md`

## Implemented Behavior

- `GeneralVlmBackend` protocol with `analyze_visual(...)`.
- Backends:
  - `disabled`
  - `mock`
  - `openai-compatible`
- Environment/config support:
  - `WRITEUP2MD_VLM_BASE_URL`
  - `WRITEUP2MD_VLM_API_KEY`
  - `WRITEUP2MD_VLM_MODEL`
- CLI option:
  - `--general-vlm disabled|auto|openai-compatible|mock`
- Routing policy excludes decorative visuals and all code-like visual types.
- Request metadata persistence redacts key-like fields.
- OpenAI-compatible requests use grounded JSON instructions and request
  `visual_type`, `visible_text`, `summary`, `relationships`, and
  `uncertainties`.

## Tests Run

```bash
python -m pytest tests/unit/test_general_vlm.py \
  tests/unit/test_config.py \
  tests/unit/test_cli.py -q
# 26 passed
```

## Known Limitations

- The optional VLM is not yet wired into the PDF enrichment path by default.
  This is intentional for TASK_26: the default full-book flow remains
  PaddleOCR-VL only and must not require a generic endpoint.
- Real endpoint smoke testing is skipped unless the user provides environment
  variables.

## Next Step

Proceed to TASK_27: complete 212-page book acceptance.
