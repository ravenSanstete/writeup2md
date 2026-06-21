# TASK_24 — Cross-page document reconstruction

Round 4 — Full-Book PDF Compilation.

## Goal

Compile verified page shards into a readable book rather than a raw page dump.

## Acceptance

- Repeated headers, footers, and page numbers are detected conservatively and
  removed with provenance.
- Prose paragraphs can merge across page boundaries when evidence supports it.
- Safe dehyphenation is applied to prose only, never to code-like content.
- Heading hierarchy is improved at the document level.
- Cross-page code, tables, lists, and terminal sessions are merged when
  reliable.
- TOC content is preserved without duplicating chapter body text.
