# TASK_26 — Optional general VLM endpoint

Round 4 — Full-Book PDF Compilation.

## Goal

Add an optional, disabled-by-default generic multimodal VLM interface for
non-code visuals without making it a required dependency.

## Acceptance

- Backends: `disabled`, `openai-compatible`, and `mock`.
- Environment variables and config fields support base URL, API key, and model.
- API keys are never persisted.
- Routing excludes code, terminal, HTTP, diff, config, logs, and stack traces.
- Missing endpoint never fails PDF processing.
- Deterministic mock endpoint tests cover routing and disabled behavior.
