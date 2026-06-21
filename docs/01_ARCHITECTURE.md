# Architecture

## Pipeline

```text
Source
  ├── PDF adapter
  ├── URL adapter
  └── HTML adapter
        ↓
Capture and native extraction
        ↓
Unified Document IR
        ↓
Visual classification and routing
        ↓
PaddleOCR-VL recognition
        ↓
Code-aware deterministic post-processing
        ↓
Quality gates
        ↓
Pure-text Markdown + provenance + diagnostics
```

## PDF adapter

Responsibilities:

- preserve the original PDF;
- extract native text and native code-like regions;
- detect existing OCR text layers;
- extract embedded images where possible;
- render pages at configurable DPI for fallback recognition;
- emit ordered blocks with page and bounding-box provenance.

Recommended initial strategy:

- use Docling for page structure and reading-order candidates;
- use PyMuPDF for direct image extraction and rendering;
- invoke PaddleOCR-VL only on unresolved visual regions.

## URL adapter

Responsibilities:

- render with Playwright;
- wait for meaningful page readiness and lazy-loaded content;
- identify the article container;
- preserve final HTML and selected metadata;
- extract native `<pre><code>` content;
- inspect copy-button payloads and accessible code text;
- download original content images;
- screenshot complex visual elements only as a fallback;
- emit DOM-order blocks with selector or XPath provenance.

## Unified IR

All inputs become a sequence of ordered blocks. The Markdown renderer must not know whether a block came from PDF or URL.

Required top-level concepts:

- `Document`
- `SourceRecord`
- `Block`
- `TextBlock`
- `NativeCodeBlock`
- `VisualBlock`
- `EnrichedVisualBlock`
- `EvidenceRef`
- `QualityReport`

## Visual router

Every visual is classified before recognition:

- code;
- terminal;
- HTTP request or response;
- diff;
- configuration;
- log;
- stack trace;
- table;
- diagram;
- UI screenshot;
- decorative;
- unknown.

Only important unresolved visuals are sent to OCR.

## Rendering

The renderer consumes the IR and produces Markdown. It must not infer missing content. It may perform only safe formatting normalization, such as line-ending normalization and explicit removal of editor line numbers when confidently identified.

## Full-book PDF checkpointing

Round 4 adds a page-shard layer for complete-book PDF conversion. Ordinary
PDF conversion now writes:

```text
outputs/<document-dir>/
├── state/
│   ├── document_state.json
│   ├── page_state.sqlite
│   └── events.jsonl
├── pages/
│   ├── 000001/
│   │   ├── page.json
│   │   ├── page.md
│   │   ├── completeness.json
│   │   ├── provenance.jsonl
│   │   └── evidence/
│   └── ...
├── document.md
├── document.json
└── full_document_completeness.json
```

SQLite is runtime state only; page JSON, page Markdown, provenance, and
evidence remain the canonical artifacts. A page is marked `verified` only after
its extraction, visual evidence, OCR enrichment, Markdown, provenance, and
completeness artifacts are durable. Final `document.md` can be rebuilt from
verified page shards without rerunning OCR.

Round 4 reconstruction removes page furniture conservatively before final
Markdown compilation. Candidates must have strong cross-page evidence, stable
edge-page coordinates, short text, and non-body context; known generator
artifacts such as `Powered by TCPDF`, page-number-only blocks, and recurring
running headers/footers are removed with a record in
`reconstruction_removed.jsonl`. Cross-page continuation is then applied to
body prose and code-like blocks only. Paragraph dehyphenation is skipped for
URLs, paths, hashes, command-line options, and code-like identifiers. Code
continuation is based on adjacent pages, matching language/type, indentation,
line-number continuity, or unbalanced syntactic context. Reconstruction emits
`reconstruction_diagnostics.json`, and full-document completeness surfaces
furniture-removal and cross-page-merge counts.

## Implementation status

- **TASK_01 (Foundation):** Pydantic IR, deterministic IDs, atomic IO, profiles, CLI skeleton, doctor — complete.
- **TASK_02 (URL):** Playwright capture, article-container selection, DOM-order block extraction (headings, paragraphs, lists, quotes, tables, native code with language hints, hr, images), image evidence capture, raw HTML preservation, single browser + single page closed in `finally`, no crawling — complete.
- **TASK_03 (PDF):** PyMuPDF native text + embedded image + render fallback, sequential page processing, scanned-page detection, page + bbox provenance — complete.
- **TASK_04 (OCR enrichment):** PaddleOCR-VL backend (lazy, one instance, one inference at a time), mock backend for tests, visual classification, conservative post-processing, confidence scoring, no-auto-repair, no-fake-success — complete.
- **TASK_05 (Batch + quality gates):** directory / URL-list / JSONL / mixed input, durable file-backed state, resume + retry, deterministic skip, status routing, batch summary and failures files, MacBook worker limit enforcement — complete.
- **TASK_06 (Streamlit UI):** pending.

The URL adapter downloads original image bytes via Playwright's `request` API rather than retaining screenshots in memory, then closes the page. Local HTML files bypass Playwright entirely and parse via BeautifulSoup + lxml.
