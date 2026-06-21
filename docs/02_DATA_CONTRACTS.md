# Data Contracts

## Manifest

`manifest.json` records source identity and processing configuration.

Required fields:

```json
{
  "schema_version": "1.0",
  "document_id": "...",
  "source": "...",
  "source_type": "pdf|url|html",
  "canonical_source": "...",
  "captured_at": "...",
  "content_sha256": "...",
  "config_sha256": "...",
  "status": "accepted|review|rejected|failed"
}
```

## Block contract

Every block needs:

```json
{
  "block_id": "b_000123",
  "order": 123,
  "type": "paragraph|heading|native_code|visual|...",
  "text": null,
  "provenance": []
}
```

## Evidence reference

PDF evidence:

```json
{
  "kind": "pdf_region",
  "page": 7,
  "bbox": [100.0, 220.0, 1400.0, 930.0],
  "asset_path": "evidence/regions/b_000123.png"
}
```

Web evidence:

```json
{
  "kind": "dom_element",
  "url": "https://example.com/article",
  "selector": "article figure:nth-of-type(3)",
  "asset_path": "evidence/elements/b_000123.png"
}
```

## Enriched visual contract

```json
{
  "visual_type": "terminal",
  "raw_text": "...",
  "selected_text": "...",
  "language": "bash",
  "segments": [
    {"role": "command", "text": "python exploit.py"},
    {"role": "output", "text": "[+] success"}
  ],
  "confidence": 0.93,
  "review_required": false,
  "transformations": ["removed_editor_line_numbers"]
}
```

## Provenance ledger

`provenance.jsonl` contains one record per final Markdown block and must map the final text back to source evidence and transformations.

## Diagnostics

`diagnostics.json` must include:

- block counts by type;
- unresolved important visuals;
- low-confidence blocks;
- OCR confidence distribution;
- Markdown image-reference check;
- document status and reasons;
- processing warnings and errors.
