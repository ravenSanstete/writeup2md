# OCR Error Taxonomy

Empirical categorization of OCR errors observed when running the `rapid`
(rapidocr-onnxruntime 1.4.4) backend over the 45-sample Golden Set. Each
category includes a definition, observed frequency, and a concrete example.
Categories are not mutually exclusive — one sample can exhibit several.

## Method

For each Golden Set sample, the evaluator records `gold_verbatim`,
`raw_ocr_text`, CER, critical-token recall, and per-character differences.
Errors were categorized by inspecting the per-sample results in
`reports/golden-eval/results.jsonl`.

## Top error categories (by observed frequency on the 45-sample Golden Set)

### 1. Space-merge failure (23 / 45 samples)

Definition: rapidocr returns two adjacent tokens as a single concatenated
token, dropping the whitespace between them.

Example (`code_py_light_01`):
- gold: `url = 'https://example.com/api'`
- actual: `url='https://example.com/api`

Example (`code_py_indent_01`):
- gold: `if x > 0:`
- actual: `ifx>0:`

Impact: high. This is the dominant error mode and the reason exact-match
rate is 0%. It breaks Python syntax (keyword-identifier merges like
`importrequests`) and reduces readability of every code sample.

Postprocessing mitigation: TASK_11 will add a code-aware splicer that
re-introduces spaces between known keywords and identifiers (e.g. `import` +
`[a-z]` → `import ` + match). This is a *presentation normalization* — it
must not invent unseen characters, only re-insert whitespace that the model
dropped between visible tokens.

### 2. Missing space after keyword (18 / 45 samples)

Definition: a Python/Bash keyword immediately followed by an identifier with
no space (`importrequests`, `defmain`, `ifx`, `fori`). Subset of category 1
but called out because it is the most syntactically damaging form and is
detectable with a fixed keyword list.

Example (`code_py_light_01`):
- gold: `import requests`
- actual: `importrequests`

Postprocessing mitigation: deterministic keyword-boundary splitter that runs
only when the merged token contains a recognized keyword prefix and the
remainder is a valid identifier. Conservative — only fires on known keywords.

### 3. Fullwidth / Chinese punctuation substitution (13 / 45 samples)

Definition: rapidocr occasionally substitutes ASCII punctuation with its
fullwidth Chinese equivalent — `,` → `，`, `(` → `（`, `)` → `）`, `;` → `；`.

Example (`code_py_light_01`):
- gold: `r = requests.get(url, timeout=10)`
- actual: `r= requests.get(url，timeout=10)`

Example (`code_py_indent_01`):
- gold: `def f(x):`
- actual: `def f（x):`

Impact: medium. Breaks JSON parsing, Python syntax, and shell syntax.

Postprocessing mitigation: deterministic fullwidth→ASCII punctuation map.
Reversible and unambiguous; safe to apply globally to code/config/HTTP
samples.

### 4. Newline loss / line merging (1 / 45 samples)

Definition: rapidocr returns fewer lines than the gold, merging two lines
into one.

Example (`code_py_lowres_01`):
- gold lines: 3
- actual lines: 2

Impact: medium. Affects indentation-sensitive code. Most common on
low-resolution images where line boundaries are unclear.

Mitigation: TASK_11 selective multi-view retry — upscale low-res images
before inferring.

### 5. Editor line-number leakage (potential, not observed on this set)

Definition: when editor line numbers are present, the postprocessor must
strip them. Currently observed accuracy is 1.0 on the one Golden Set sample
with line numbers (`code_py_lineno_01`) — the existing
`_strip_editor_line_numbers` works correctly.

Residual risk: partial line-number cases (some lines numbered, some not)
are NOT stripped by the conservative rule. TASK_11 will handle these.

### 6. Quote substitution (low frequency on this set)

Definition: `'` vs `"`, or curly quotes `'` `'` `"` `"` substituted for
straight quotes.

Observed: rare on this Golden Set (the rapid backend handles ASCII quotes
correctly on rendered Menlo-font images).

### 7. Zero vs O / one vs l vs I (low frequency on this set)

Definition: classic OCR confusion between digit/letter lookalikes.

Observed: rare on this Golden Set because the fixtures use a monospace
font that distinguishes these well. May appear on real-world screenshots
with proportional fonts.

### 8. Underscore vs hyphen (low frequency on this set)

Definition: `_` substituted for `-` or vice versa.

Observed: rare on this Golden Set.

### 9. Missing backslash (low frequency on this set)

Definition: backslash dropped from escape sequences (`\n` → `n`).

Observed: rare on this Golden Set.

### 10. Duplicated line (not observed on this set)

Definition: a line is repeated in the OCR output.

Observed: 0 / 45 on this set.

### 11. Omitted line (not observed on this set as a distinct category)

Definition: a line present in gold is entirely missing from actual.

Observed: subsumed into newline-loss (category 4) for the low-res sample.

### 12. Indentation collapse (observed on indentation-sensitive samples)

Definition: leading whitespace is reduced or lost.

Observed: indentation exact-match rate is 0.60 across the Golden Set (i.e.
40% of samples have at least one line where the leading whitespace count
differs between gold and actual). The `_looks_space_merged` heuristic in
`enricher.py` does not currently catch this — it only catches word-merging.
Indentation collapse is partly a space-merge symptom (leading spaces lost
along with inter-token spaces).

Mitigation: TASK_11 will add a leading-whitespace reconstruction step that
uses the model's bbox information to infer indentation when available.

### 13. Prompt confusion (not observed on this set)

Definition: terminal `$` prompt is misread as `S`, `5`, or merged with the
command.

Observed: 0 / 45 on this set (the fixtures render `$` cleanly).

### 14. HTTP header/body merge (not observed on this set)

Definition: the blank line separating HTTP headers from body is lost,
causing the body to be parsed as a header.

Observed: 0 / 45 on this set (the `http_request_01` fixture's blank line
was preserved by rapidocr).

### 15. Command/output merge (observed on terminal samples)

Definition: terminal command and its output are not separated into distinct
segments.

Observed: segmentation F1 is 0.20 on the terminal samples — most commands
and outputs are not correctly split. This is partly because rapidocr merges
the `$` prompt into the command text (`$ls` instead of `$ ls`), so the
prompt regex does not match.

Mitigation: TASK_11 will add a more robust prompt detector that recognizes
`$<text>` and `><text>` as well as `\$ <text>`.

### 16. Hallucinated completion (low frequency on this set)

Definition: the model invents characters not present in the image.

Observed: hallucination rate mean is 0.006 (0.6% of output characters) —
very low. The few hallucinated characters are mostly fullwidth punctuation
substitutions (already counted in category 3) rather than invented content.

### 17. Syntax-based unauthorized repair (NOT observed — verified)

Definition: the postprocessor "fixes" broken code by adding missing
brackets, completing cropped lines, or rewriting syntax to compile.

Observed: 0 / 45. The existing `test_enrich_does_not_auto_repair_code`
test guards against this and passes. The `_strip_editor_line_numbers` and
`split_terminal_commands` functions only perform reversible transformations.

## Summary table

| # | Category | Frequency | Severity | Mitigation |
| --- | --- | --- | --- | --- |
| 1 | Space-merge | 23/45 | high | TASK_11 keyword-boundary splitter |
| 2 | Missing space after keyword | 18/45 | high | TASK_11 keyword-boundary splitter (subset of 1) |
| 3 | Fullwidth punct substitution | 13/45 | medium | TASK_11 fullwidth→ASCII map |
| 4 | Newline loss | 1/45 | medium | TASK_11 multi-view retry on low-res |
| 12 | Indentation collapse | ~40% of samples | medium | TASK_11 bbox-based reconstruction |
| 15 | Command/output merge | terminal samples | medium | TASK_11 robust prompt detector |
| 5 | Line-number leakage | 0/45 (verified) | low | already handled |
| 6-11 | Quote/zero-O/underscore/backslash/dup/omit | rare | low | TASK_11 candidate selection |
| 14 | HTTP header/body merge | 0/45 | low | already preserved |
| 16 | Hallucinated completion | 0.6% chars | low | already low |
| 17 | Syntax-based unauthorized repair | 0/45 | n/a | prohibited and verified |

## Recommended priority for TASK_11

1. Fullwidth→ASCII punctuation map (easy, broad impact).
2. Keyword-boundary splitter (high impact on code samples).
3. Robust terminal prompt detector.
4. Selective multi-view retry for low-res and cropped samples.
5. Bbox-based indentation reconstruction (requires backend support).

None of these may invent unseen characters. All transformations must be
deterministic and reversible, or must only choose between already-observed
OCR candidates.
