# E2E Baseline Defects (TASK_16)

Source: `reports/E2E_BASELINE_DEFECTS.jsonl`. Defects observed while
running the unmodified production pipeline against `test_samples/`
with `paddleocr-vl-element` and `require_exact_backend=true`.

## Summary

- 14 defects across 4 sample buckets (3 PDFs + "all")
- 3 critical, 7 major, 4 minor
- All defects have an `open` status; fixes are scheduled in TASK_17
  through TASK_20.

## Critical defects

### D1 — VLM confidence threshold misapplied (all samples)

PaddleOCR-VL element mode returns `confidence = 0.0` because the VLM
does not produce per-region scores. The TASK_09 threshold model
(`high = 0.99`, calibrated for RapidOCR) then marks every
transcription as `review_required`, so the renderer emits HTML-comment
markers instead of the actual OCR text.

**Fix (TASK_18):** When PaddleOCR-VL returns non-empty text AND the
structural-quality gate does NOT fire, mark the block `resolved_ocr`.

### D2 — OCR output hidden by review marker (sample 01)

Symptom of D1. `document.md` contains
`<!-- writeup2md: [REVIEW REQUIRED] visual=code block=b_000000 -->`
and no transcribed text.

**Fix (TASK_18):** In document mode, surface the transcription with a
textual notice. In strict mode, keep the marker for the review UI.

### D3 — 15-minute timeout on 3-page slice (sample 03)

Sample 03 (`From Day Zero to Zero Day`) timed out after 900s on a
3-page slice. Root causes:
- Multi-view retry fires for every PaddleOCR-VL visual (5x inference)
  because confidence is 0.0.
- `max_new_tokens=1024` produces runaway generation on cover-spread
  images (>1000 tokens of `0`s, hallucinated English).

**Fix (TASK_17/18):** Skip multi-view retry for PaddleOCR-VL element
backend. Lower `max_new_tokens` to 512. Downscale images to <= 1568 px
long side before OCR. Filter out decorative cover-spread images before
OCR.

## Major defects

### D4 — Embedded image OCR hallucination (sample 02)

Cover-spread image (4387x2784) sent to PaddleOCR-VL, which hallucinates
"I am the world" and runs of "0"s.

**Fix (TASK_17):** Classify embedded PDF images before OCR. Cover art
on text-light pages is `ignored_decorative`. Illustrations on
text-heavy pages are `described_as_text` (textual placeholder, no OCR).

### D5 — Image too large for VLM (sample 02)

Full-resolution 4387x2784 image sent to VLM.

**Fix (TASK_17):** Normalize before OCR — decode via PIL, downscale to
<= 1568 px long side, save as PNG. Original preserved separately.

### D6 — bbox extraction returns zeros (sample 02)

`_normalize_bbox` returns `[0,0,0,0]` when input is a 4-float list
rather than a PyMuPDF Rect. This breaks the image-area
classification because `img_area = 0`.

**Fix (TASK_17):** Handle both PyMuPDF Rect objects and 4-float lists.
Preserve negative coordinates (cover-spread images legitimately
extend past page bounds).

### D7 — Multi-view retry useless for VLM (sample 03)

5x inference cost for no quality benefit. Already fixed during TASK_17
implementation.

### D8 — max_new_tokens too high (sample 03)

`max_new_tokens=1024` is way too high for typical code blocks. Lowered
to 512.

### D9 — Raw OCR only in /tmp (all samples)

PaddleOCR-VL raw output JSON is written only to
`/tmp/writeup2md_paddleocr_vl_element_raw/`. Survives /tmp removal is
not guaranteed.

**Fix (TASK_17):** Copy raw output JSON atomically into the document
workspace at `evidence/visuals/<block_id>/candidates/`.

### D10 — No one-command CLI (all samples)

User must run `writeup2md convert SOURCE` and pass
`--ocr-backend paddleocr-vl-element --require-exact-backend`.

**Fix (TASK_20):** `writeup2md SOURCE` should work and default to
`paddleocr-vl-element` with `require_exact_backend=true` on Apple
Silicon.

### D11 — No completeness report (all samples)

No `completeness.json` or `quality_report.json` emitted.

**Fix (TASK_19):** Emit `completeness.json` with the full invariant
set (`visuals_missing`, `image_syntax_count`, `unclosed_fence_count`).

## Minor defects

### D12 — HTML comment markers leak into Markdown (all samples)

`<!-- writeup2md: [REVIEW REQUIRED] ... -->` HTML comments appear in
user-facing `document.md`.

**Fix (TASK_18):** Document mode emits textual notices instead of
HTML comments.

### D13 — No human-readable output dir (all samples)

Output directories are opaque 16-char hashes (e.g.
`432306e39ddb89ab`).

**Fix (TASK_20):** Output dirs should be
`<slug>-<short_hash>` (e.g. `real-world-bug-hunting-a14c3f2e`).

### D14 — Default render DPI low (all samples)

`initial_render_dpi=200`, `retry_render_dpi=300`. Spec asks for
300 base / 450 retry.

**Fix (TASK_20):** Base 300 DPI, retry 450 DPI.

## Notes on the baseline run

The baseline ran on the first 3 pages of the first 3 PDFs only. The
remaining 4 PDFs were not measured because sample 03 timed out at
900s, demonstrating the critical-path defect (D3). The fixes in
TASK_17/18 bring a 3-page slice from 240s+ down to 21s, which makes
running all 7 PDFs tractable in TASK_21.
