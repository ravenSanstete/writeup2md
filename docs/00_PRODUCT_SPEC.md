# Product Specification

## Goal

`writeup2md` converts one PDF, URL or local HTML file into a readable, high-quality Markdown document suitable for search, training and human reading.

The target corpus consists primarily of:

- technical tutorials;
- CTF and penetration-testing writeups;
- vulnerability analyses;
- exploit-development notes;
- setup and debugging guides;
- code-heavy research or engineering reports.

## User experience

### Single source

```bash
writeup2md convert tutorial.pdf
writeup2md convert https://example.com/writeup
```

### Batch

```bash
writeup2md batch sources.jsonl --workers 1 --resume
writeup2md batch ./raw_data --recursive --workers 1 --resume
```

### Review

```bash
writeup2md ui outputs/
```

## Final Markdown requirements

The final Markdown must:

- preserve heading hierarchy and reading order;
- retain paragraphs, lists, quotations, native code and tables;
- convert important visual code into fenced code blocks;
- separate terminal commands from output when reliable;
- represent HTTP screenshots as `http` blocks when reliable;
- represent patches as `diff` blocks;
- contain no images;
- contain no hallucinated explanation;
- clearly mark unresolved content when strict acceptance is disabled.

## Non-functional requirements

- resumable batch processing;
- deterministic outputs for unchanged inputs and configuration;
- inspectable provenance;
- local-first execution;
- no mandatory database;
- MacBook-safe local orchestration with one worker by default and optional acceleration when available;
- meaningful diagnostics rather than opaque success/failure.

## Success criteria for v1

A user can process representative PDF and URL tutorials with one command, inspect the result in Streamlit, and determine exactly which source region produced every OCR-enriched code block.

## Local resource requirement

Version 1 must run safely on a MacBook Pro. The default batch worker count is one. OCR is serialized through one PaddleOCR-VL model instance, PDF pages are processed sequentially, browser resources are reused and closed promptly, and the Streamlit UI lazy-loads the selected document and evidence. See `docs/08_MACBOOK_EXECUTION.md`.
