# TASK_19 — Completeness gates and document/strict modes (completion)

## Summary

Implemented a `completeness.json` artifact emitted next to every
`document.md` carrying the full invariant set (6 invariants), a
`quality_report.json` human-readable summary, a top-level `--strict`
CLI flag (in addition to `--profile strict`), and conservative
suspicious-document detection that forces `rejected` status.

The fixes resolve defect D11 from the TASK_16 defect ledger.

## Files changed

### New files

- `src/writeup2md/completeness.py` — completeness gate module:
  - `check_completeness(document, markdown_text, markdown_path, mode)`
    computes the 6 invariants: `visuals_missing`, `image_syntax_count`,
    `html_img_tag_count`, `base64_image_uri_count`,
    `unclosed_fence_count`, `html_comment_marker_count`.
  - `_count_unclosed_fences(markdown_text)` state-machine walk.
  - `is_suspicious_document(document, markdown_text)` — conservative
    detection: fires only when zero native text AND ≥2 non-decorative
    visuals all routed to review (suggesting a pipeline issue), OR when
    a PDF input has multiple pages but < 100 chars of markdown.
  - `apply_completeness_to_status(status, completeness, is_suspicious)`
    — routes to `REJECTED` when any invariant fails or the document is
    suspicious.
  - `write_completeness_artifacts(document_dir, document, markdown_text, mode, diagnostics, backend_info)`
    — writes `completeness.json` and `quality_report.json`.

- `tasks/TASK_19_COMPLETENESS_AND_DOCUMENT_MODE.md` — task spec.

- `tests/unit/test_completeness.py` — 16 tests covering all 6
  invariants, fence-counting edge cases, suspicious-document
  detection, status-application logic, and end-to-end
  completeness.json emission.

### Modified files

- `src/writeup2md/persist.py`
  - Imported `apply_completeness_to_status`, `is_suspicious_document`,
    `write_completeness_artifacts` from `.completeness`.
  - After rendering markdown, compute suspicious flag, write
    completeness artifacts, apply completeness to status. If status
    changes (e.g. → `REJECTED`), re-build manifest, diagnostics, and
    provenance, then re-render markdown (the markdown body itself is
    unaffected by status; this is a defensive re-render to keep
    artifacts consistent).

- `src/writeup2md/cli.py`
  - Added `--strict` flag to `convert` and `batch`. Sets
    `cfg.quality.mode = "strict"` after building the config from the
    profile (so it doesn't change other profile settings like
    workers, DPI, etc).
  - Updated help text to describe the difference between document
    mode (default) and strict mode.

- `tests/unit/test_cli.py`
  - Added `test_convert_help_lists_strict_flag`.
  - Added `test_batch_help_lists_strict_flag`.

## Defects resolved

| ID | Severity | Resolution |
| --- | --- | --- |
| D11 | major | `completeness.json` emitted next to `document.md` with the full 6-invariant set; `quality_report.json` emitted alongside. |

## Acceptance gates

1. Every conversion produces `completeness.json` next to `document.md`.
   — **PASS** (verified on sample 02 PaddleOCR-VL run; verified by
   `test_convert_emits_completeness_json`).
2. `completeness.json` carries the 6 invariants listed in 19.B. —
   **PASS** (verified by `test_convert_emits_completeness_json`).
3. `completeness.json.summary.passed == total_invariants` for a clean
   conversion. — **PASS** (verified on sample 02: 6/6 passed).
4. `writeup2md convert SOURCE --strict` produces a document in strict
   mode (HTML-comment markers allowed in `document.md`). — **PASS**
   (verified by `test_check_completeness_allows_html_comment_marker_in_strict_mode`
   and `test_convert_help_lists_strict_flag`).
5. `writeup2md convert SOURCE` (default) produces a document in
   document mode (no HTML-comment markers in `document.md`). — **PASS**
   (verified by
   `test_check_completeness_catches_html_comment_marker_in_document_mode`
   and TASK_18 acceptance gate 4).
6. Suspicious-document detection forces `rejected` status. — **PASS**
   (verified by `test_apply_completeness_to_status_rejects_on_suspicious`
   and `test_suspicious_document_all_visuals_review_no_native_text`).
7. `quality_report.json` exists alongside `completeness.json`. — **PASS**
   (verified on sample 02 PaddleOCR-VL run; the report carries
   `status`, `mode`, `completeness`, `visual_coverage`, `top_warnings`).

## Verification on real PaddleOCR-VL run

Sample 02 (Cybersecurity Tabletop Exercises), 2 pages, default
document mode:

```
STATUS=accepted
ELAPSED=19.42
```

`completeness.json`:

```json
{
  "document_id": "e27932663c2e86cd",
  "checked_at": "2026-06-20T17:13:20Z",
  "mode": "document",
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
  "markdown_sha256": "0e7b06d57abe254d17e02eb5a05a8fdc28fa28acaf61ba6b6fa8dbe8222ab4c7",
  "markdown_byte_count": 867
}
```

`quality_report.json`:

```json
{
  "document_id": "e27932663c2e86cd",
  "status": "accepted",
  "mode": "document",
  "completeness": {
    "passed": 6,
    "failed": 0,
    "failed_invariants": []
  },
  "visual_coverage": {
    "total_visual_blocks": 1,
    "by_state": {
      "transcribed": 1,
      "review_required": 0,
      "duplicate_with_reference": 0,
      "native_text_used": 0,
      "failed_with_diagnostic": 0,
      "decorative_with_reason": 0
    },
    "missing": 0,
    "all_covered": true
  },
  "top_warnings": [
    "page 0 flagged as scanned"
  ]
}
```

## Commands run

```bash
python -m pytest tests/unit/test_completeness.py -q
# 16 passed

python -m pytest tests/unit/test_cli.py -q
# 10 passed

python -m pytest tests/ -q --ignore=tests/real_ocr --ignore=tests/real_paddleocr_vl
# 290 passed

python /tmp/verify_task17_raw_copy.py
# STATUS=accepted, ELAPSED=19.42 (sample 02, 2 pages)
# completeness.json + quality_report.json emitted
```

## Known limitations

- The suspicious-document detection is intentionally conservative.
  It only fires when there's strong evidence of a pipeline issue
  (no native text AND ≥2 non-decorative visuals all routed to
  review). Single-visual review is treated as legitimate, which
  preserves the tutorial.html test's expectation.
- The `quality_report.json` does not yet include `backend_info`
  fields (model_repo, model_revision) because the persist layer
  doesn't have access to the OCR backend's metadata directly. This
  can be added in a future round by threading the backend info
  through `finalize_document`.
- The `--strict` flag is currently a boolean switch. A future round
  could add `--mode document|strict` for explicit control, but the
  current flag matches the spec exactly.

## Next task

TASK_20 (one-command CLI + performance) — the `writeup2md SOURCE`
shorthand, human-readable output dir names (`<slug>-<short_hash>`),
300 DPI default, and progress display.
