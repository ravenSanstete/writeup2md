# TASK_02 Completion Report — URL Native Extraction

## Status

Complete. All acceptance conditions met.

## Files created or changed

- `src/writeup2md/dom_extract.py` — BeautifulSoup + lxml DOM extraction shared by URL and HTML adapters: article-container selection, DOM-order blocks (headings, paragraphs, lists, quotes, tables, native code with language detection, hr, content images as review_required visual blocks), evidence asset writer with content-hash filenames.
- `src/writeup2md/adapters/url.py` — Playwright URL adapter: one Chromium browser per process, one page per source closed in `finally`, conservative auto-scroll + networkidle wait, raw HTML and metadata persisted before enrichment, image bytes downloaded via `page.request.get` (no large in-memory screenshots retained), supports `html_override`/`base_url_override` for offline test fixtures.
- `src/writeup2md/adapters/html.py` — local HTML adapter: parses file directly without Playwright, resolves relative image paths against the source directory, captures local image bytes to `evidence/elements/`.
- `src/writeup2md/persist.py` — shared document-directory finalizer: computes status via quality gates, writes `document.md`, `document.json`, `manifest.json`, `diagnostics.json`, `provenance.jsonl`, persists raw assets immutably.
- `src/writeup2md/pipeline.py` — `detect_source_type` now recognizes `file://` URLs.
- `pyproject.toml` — added `beautifulsoup4` and `lxml` to web/all extras.
- `tests/fixtures/html/tutorial.html` — representative tutorial fixture with headings, paragraphs, Python/Bash/HTTP code blocks, list, quote, hr, inline image, `<figure>`.
- `tests/fixtures/html/login_form.png` — 1×1 PNG referenced by the fixture.
- `tests/unit/test_dom_extract.py` — 9 unit tests for DOM extraction.
- `tests/integration/test_url_pipeline.py` — 8 integration tests covering full document layout, no-image-markdown, code block language preservation, review status, provenance per block, deterministic IDs, evidence image capture, raw HTML preservation.
- `docs/01_ARCHITECTURE.md` — added Implementation status section.

## Design decisions

- **No `Docling` for URL:** the URL adapter uses BeautifulSoup directly because Playwright already gives us a rendered DOM. Docling is recommended in `docs/01_ARCHITECTURE.md` for the *PDF* adapter; we revisit that in TASK_03.
- **Article container selection** uses a priority-ordered list of selectors (`article`, `main`, `[role=main]`, `#main`, `#content`, common class names) and falls back to `<body>`.
- **Title de-duplication:** the synthetic page-title heading is only emitted if the article root does NOT already begin with an `<h1>`, so we never duplicate the title.
- **Image handling:** every content `<img>` becomes a separate visual block of type `UNKNOWN` with state `REVIEW_REQUIRED`. Visual classification happens in TASK_04. We never insert image syntax into the Markdown; instead we emit an HTML comment marker `<!-- writeup2md: [REVIEW REQUIRED] visual=unknown block=b_xxxxxx -->` so provenance maps and the user knows there is unresolved content.
- **UNKNOWN visuals are treated as important** by the quality gate. This ensures images are surfaced for review rather than silently discarded, per spec principle 7.
- **Image bytes are downloaded by hash:** `evidence/elements/<sha16>.<ext>` — same content always lands at the same path, and we never overwrite existing files.
- **Resource behavior:** one browser per `sync_playwright()` context, one page per source, page closed in `finally` even on error. No crawling of unrelated links.
- **Offline test path:** the URL adapter supports `html_override`/`base_url_override` for injecting pre-fetched HTML, used by tests to avoid flaky internet. The local-HTML adapter does not use Playwright at all.

## Test results

```
python -m pytest
======================== 78 passed, 5 warnings in 0.73s ========================
```

End-to-end CLI smoke test:

```
python -m writeup2md convert tests/fixtures/html/tutorial.html --output /tmp/w2m_test --profile macbook
Status: REVIEW
Markdown: /tmp/w2m_test/972c35336e2c44ad/document.md
```

The generated `document.md` contains the four code blocks (Python, Bash, plain, HTTP) with correct fence languages, the list, the quote, the hr, and an HTML-comment marker where the unresolved image sits. No image syntax is present.

A second smoke test against `file://.../tutorial.html` exercises the Playwright URL path and produces the same layout (raw/page.html, raw/metadata.json, evidence/, manifest, diagnostics, provenance).

## Known limitations

- **Remote image capture for `file://` URLs:** when the URL adapter fetches a `file://` page, relative `<img src="login_form.png">` references are not resolved to local file bytes (Playwright's `page.request.get` does not fetch local file paths in our test setup). The image is still recorded as a `review_required` visual block, satisfying the spec requirement that images are surfaced rather than discarded. Local-HTML adapter captures local images correctly.
- **No copy-button payload inspection yet:** the spec mentions inspecting copy-button payloads. Most modern code blocks expose their text via `<pre><code>` directly, which we capture. Sites that hide code behind a `data-copy` attribute would need a dedicated handler; deferred to a future improvement.
- **No screenshot fallback** for elements that are not available through DOM or network. The spec allows this as a fallback; deferred until TASK_04 (when we know which visuals actually need OCR).

## Recommended next task

TASK_03 — PDF Native Extraction. Implement PDF preservation, native text extraction, reading-order candidates, page and bounding-box provenance, embedded image extraction, configurable page rendering, visual-block creation, and scanned-page detection using PyMuPDF.
