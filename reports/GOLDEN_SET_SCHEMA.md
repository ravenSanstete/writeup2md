# Golden Set Schema

## File layout

```text
evaluation/golden/
├── manifest.jsonl      # one JSON object per line, one per sample
├── images/             # screenshot PNGs (rendered visual text)
├── expected/           # <sample_id>.txt mirroring gold_verbatim
├── documents/          # optional longer-form ground-truth documents
└── README.md           # composition notes and diversity coverage
```

## manifest.jsonl record

```json
{
  "sample_id": "code_py_light_01",
  "source_document": "golden/code_py_light_01",
  "source_type": "image",
  "visual_type": "code",
  "language": "python",
  "image_path": "images/code_py_light_01.png",
  "gold_verbatim": "import requests\nurl = 'https://example.com/api'\n...",
  "gold_segments": [],
  "line_numbers_present": false,
  "line_numbers_should_be_removed": false,
  "cropped": false,
  "dark_theme": false,
  "critical_tokens": ["import", "requests", "get", "status_code", "json"],
  "notes": "light-theme python with quotes and dots"
}
```

### Field semantics

| field | type | required | meaning |
| --- | --- | --- | --- |
| `sample_id` | string | yes | unique id; matches `images/<sample_id>.png` and `expected/<sample_id>.txt` |
| `source_document` | string | yes | provenance hint; `golden/<sample_id>` for synthetic samples |
| `source_type` | enum | yes | `pdf` \| `url` \| `html` \| `image` |
| `visual_type` | enum | yes | `code` \| `terminal` \| `http` \| `diff` \| `configuration` \| `log` \| `traceback` \| `other` |
| `language` | string | yes | programming language or `http`/`diff`/`log`/`yaml`/`json`/`ini`/`toml` |
| `image_path` | string | yes | relative path from the golden root |
| `gold_verbatim` | string | yes | exact visible text in the image, line breaks preserved |
| `gold_segments` | array | no | optional structured segmentation (command/output split, etc.) |
| `line_numbers_present` | bool | yes | whether the screenshot shows editor line numbers |
| `line_numbers_should_be_removed` | bool | yes | whether postprocessing should strip them |
| `cropped` | bool | yes | whether the image is a partial crop |
| `dark_theme` | bool | yes | dark background? |
| `critical_tokens` | array | yes | tokens that MUST appear for the sample to count as correctly recognized |
| `notes` | string | yes | freeform annotation |

## Size target

Spec target: ≥100 samples if enough real fixtures are available, otherwise ≥40
with documented shortfall. This Golden Set contains 45 samples — above the
minimum 40 but below 100. The shortfall is honest: each sample is hand-crafted
with known ground truth; inflating the count with duplicates would not improve
evaluation quality. Future work: extract real visual blocks from the
test_samples/ PDFs (TASK_14) to grow the set to 100+.

## Diversity coverage

| dimension | covered? |
| --- | --- |
| code | yes (23 samples: python, javascript, bash, go, rust) |
| terminal | yes (3) |
| command + output | yes |
| HTTP request | yes (5) |
| HTTP response | yes |
| diff (unified, git, merge) | yes (3) |
| JSON | yes |
| YAML | yes (2: light + dark) |
| INI | yes (2) |
| TOML | yes |
| stack trace (python, java) | yes (2) |
| logs (nginx, app, syslog) | yes (3) |
| light theme | yes (43) |
| dark theme | yes (2) |
| editor line numbers | yes (1) |
| cropped content | yes (2) |
| low resolution | yes (1) |
| punctuation-heavy | yes (2) |
| URLs | yes |
| hashes | yes (2) |
| IP addresses | yes |
| quoted strings | yes |
| indentation-sensitive | yes |
