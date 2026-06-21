# TASK_04: PaddleOCR-VL Enrichment

## Objective

Resolve important visual blocks using PaddleOCR-VL 0.9B and deterministic code-aware post-processing.

## Required implementation

- OCR backend interface;
- PaddleOCR-VL implementation;
- visual classification and routing;
- code, terminal, HTTP, diff and configuration outputs;
- line-number handling;
- command/output separation;
- confidence scoring;
- evidence and transformation records;
- strict prohibition on semantic code repair;
- unit and golden-fixture tests.

## Acceptance condition

Representative code and terminal screenshots become faithful fenced Markdown blocks with evidence links and review states.

## MacBook constraints

- one lazily initialized model instance;
- one OCR inference at a time;
- no model-per-worker pattern;
- no vLLM or separate inference server;
- optional real-model smoke test, with ordinary tests using a mock backend;
- release intermediate images after each visual block.
