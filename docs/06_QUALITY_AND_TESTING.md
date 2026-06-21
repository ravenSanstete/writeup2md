# Quality and Testing

## Test layers

### Unit tests

- source-type detection;
- deterministic document IDs;
- IR serialization;
- Markdown renderer;
- image-reference rejection;
- terminal command/output splitting;
- editor line-number removal;
- HTTP and diff formatting;
- status calculation.

### Integration tests

- native-text PDF;
- scanned PDF with code screenshot;
- article URL with native code;
- article URL with code image;
- terminal screenshot;
- Burp/HTTP screenshot;
- batch resume after interruption;
- Streamlit result loading and review persistence.

### Golden set

Maintain a small manually verified corpus containing:

- at least three PDFs;
- at least three URLs captured as stable fixtures;
- light and dark code screenshots;
- Python, shell, C/C++, JavaScript and configuration examples;
- terminal, HTTP and diff examples;
- deliberately low-quality screenshots.

Each fixture includes expected Markdown and expected provenance assertions.

## Required quality checks

- final Markdown contains no image links;
- all important visual blocks have a terminal state;
- accepted documents contain no `review_required` important visuals;
- raw evidence exists for every OCR-derived block;
- every Markdown block maps to provenance;
- rerunning unchanged input produces equivalent output;
- interrupted batch processing resumes without duplication.

## Metrics

Document metrics:

- native text coverage;
- important visual resolution rate;
- OCR-enriched block count;
- unresolved visual count;
- reading-order violations;
- final Markdown image count;
- overall quality score.

Code-block metrics:

- line count;
- uncertain token count;
- indentation consistency;
- parser error-byte ratio;
- crop completeness;
- review status.

## Acceptance policy

A document is accepted only when:

- processing completed;
- Markdown is non-empty;
- no images remain in Markdown;
- all important visuals are resolved;
- every OCR-derived block has evidence;
- no hard quality gate failed.
