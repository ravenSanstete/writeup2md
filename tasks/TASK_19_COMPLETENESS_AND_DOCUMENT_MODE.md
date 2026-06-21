# TASK_19 — Completeness gates and document/strict modes

## Goal

Emit a `completeness.json` artifact for every conversion that records
the full invariant set, and add a top-level `--strict` CLI flag (in
addition to the existing `--profile strict`) that switches the
renderer into strict mode for high-quality dataset generation.

The completeness gate is the contract that lets the user (and the
release test in TASK_21) trust that a conversion is structurally
sound:

- `visuals_missing == 0` — every visual block has a final state.
- `image_syntax_count == 0` — no `![...](` or `<img>` or
  `data:image/...;base64` in `document.md`.
- `unclosed_fence_count == 0` — every opening fence has a matching
  close.
- `html_comment_marker_count == 0` in document mode (strict mode
  allows them for the review UI).

A conversion that fails any of these invariants is marked `rejected`
or `failed` regardless of the OCR outcomes.

## TASK_16 defect findings driving this task

- **D11**: No `completeness.json` or `quality_report.json` emitted.
  `diagnostics.json` exists but lacks completeness invariants
  (`visuals_missing`, `image_syntax_count`, `unclosed_fence_count`).
- **D12** (partial): HTML comment markers leak into Markdown. Already
  fixed in TASK_18 for document mode; TASK_19 records the invariant
  in `completeness.json` so future regressions are caught.

## Implementation

### 19.A `completeness.json` schema

```json
{
  "document_id": "...",
  "checked_at": "2026-06-20T00:00:00Z",
  "mode": "document|strict",
  "invariants": {
    "visuals_missing": 0,
    "image_syntax_count": 0,
    "html_img_tag_count": 0,
    "base64_image_uri_count": 0,
    "unclosed_fence_count": 0,
    "html_comment_marker_count": 0
  },
  "summary": {
    "total_invariants": 6,
    "passed": 6,
    "failed": 0
  },
  "failed_invariants": [],
  "markdown_path": "document.md",
  "markdown_sha256": "..."
}
```

The artifact is written next to `document.md` in every conversion's
output directory.

### 19.B Invariant checks

1. **visuals_missing**: count of visual blocks whose
   `visual_state is None` OR whose `coverage_state` is missing. Must
   be 0.
2. **image_syntax_count**: count of `![...](` matches in
   `document.md`. Must be 0.
3. **html_img_tag_count**: count of `<img` matches (case-insensitive)
   in `document.md`. Must be 0.
4. **base64_image_uri_count**: count of `data:image/...;base64`
   matches in `document.md`. Must be 0.
5. **unclosed_fence_count**: count of unmatched triple-backtick
   fences in `document.md` (using the state-machine walk from
   `test_render_markdown_well_formed_fences`). Must be 0.
6. **html_comment_marker_count**: count of
   `<!-- writeup2md: -->` matches in `document.md`. Must be 0 in
   document mode; allowed in strict mode.

### 19.C `--strict` CLI flag

Add a top-level `--strict` flag to `writeup2md convert` and
`writeup2md batch` that is equivalent to `--profile strict` but
without changing the other profile settings (workers, DPI, etc).
Implementation: when `--strict` is set, override
`config.quality.mode = "strict"` after building the config from the
profile.

### 19.D Suspicious-document detection

A document is "suspicious" (routed to `rejected` even if individual
invariants pass) when:

- total visual block count > 0 AND transcribed visual count == 0 AND
  failed visual count == 0 (every visual routed to review — likely
  pipeline issue, not legitimate content).
- Markdown character count < 100 AND page count > 0 (suspiciously
  short output).
- More than 50% of native text blocks are empty (capture failure).

Suspicious documents are still written to disk (for forensic
inspection) but the manifest status is forced to `rejected`.

### 19.E `quality_report.json` (optional summary)

A human-readable summary derived from `diagnostics.json` and
`completeness.json`. Includes:

- overall status (accepted/review/rejected/failed)
- visual coverage ledger
- completeness invariant pass/fail
- top 5 warnings (if any)
- backend identity (model_repo, model_revision)

Written next to `completeness.json`.

## Acceptance gates

1. Every conversion produces `completeness.json` next to `document.md`.
2. `completeness.json` carries the 6 invariants listed in 19.B.
3. `completeness.json.summary.passed == total_invariants` for a
   clean conversion.
4. `writeup2md convert SOURCE --strict` produces a document in
   strict mode (HTML-comment markers allowed in `document.md`).
5. `writeup2md convert SOURCE` (default) produces a document in
   document mode (no HTML-comment markers in `document.md`).
6. Suspicious-document detection forces `rejected` status.
7. `quality_report.json` exists alongside `completeness.json`.

## Next task

TASK_20 (one-command CLI + performance) — the `writeup2md SOURCE`
shorthand, human-readable output names, and MacBook performance
defaults.
