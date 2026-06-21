# TASK_02: URL Native Extraction

## Objective

Implement URL capture and native-content extraction into the unified IR without OCR.

## Required implementation

- Playwright rendering and lazy-content loading;
- canonical URL and metadata capture;
- final HTML preservation;
- article-container candidate selection;
- DOM-order headings, paragraphs, lists, links and native code;
- original content-image capture and visual-block creation;
- provenance for every block;
- pure-text Markdown from native blocks;
- integration fixtures using saved local HTML to avoid flaky internet tests.

## Acceptance condition

A representative tutorial containing native text, native code and images produces ordered Markdown, retains image evidence internally and leaves images as unresolved visual blocks rather than inserting them into Markdown.
