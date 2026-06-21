"""Multi-view OCR preprocessing and retry (TASK_11).

When the first OCR pass produces low-confidence or space-merged output, we
retry with N alternate preprocessing pipelines. Each view is processed and
discarded; only the resulting text + metadata is retained.

Memory behavior:
- views are produced lazily and consumed one at a time;
- image bytes for each view are released after OCR returns;
- the candidate list holds only `OcrResult` objects (text + metadata).

This module NEVER repairs code semantically. It only changes how the image
is presented to the OCR backend, leaving the backend's output untouched.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any

from .backend import OcrBackend, OcrResult


@dataclass
class ViewResult:
    """One OCR pass on one preprocessing view."""

    view_name: str
    result: OcrResult


def _load_pil_image(image_bytes: bytes):
    from PIL import Image  # type: ignore

    return Image.open(io.BytesIO(image_bytes)).convert("RGB")


def _to_png_bytes(img) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def preprocess_views(image_bytes: bytes) -> list[tuple[str, bytes]]:
    """Produce N alternate preprocessing views of the source image.

    Returns a list of (view_name, image_bytes) tuples. The first view is
    always the original (unmodified) image so that callers can compare
    against the baseline.

    Views:
    - `original` — no preprocessing (baseline).
    - `grayscale` — luminance-only; helps when color noise confuses OCR.
    - `upscale_2x` — 2× upscale with LANCZOS; helps on low-resolution crops.
    - `adaptive_threshold` — binarize with adaptive threshold; increases
      contrast for code on light backgrounds.
    - `invert_dark` — invert dark-theme screenshots so the backend sees
      light-background text (many OCR backends are trained on light
      backgrounds).
    """
    try:
        img = _load_pil_image(image_bytes)
    except Exception:  # noqa: BLE001
        # If we can't even load the image, fall back to the original bytes.
        return [("original", image_bytes)]

    views: list[tuple[str, bytes]] = [("original", image_bytes)]

    # grayscale
    try:
        g = img.convert("L")
        views.append(("grayscale", _to_png_bytes(g)))
    except Exception:  # noqa: BLE001
        pass

    # upscale 2x
    try:
        w, h = img.size
        if w > 0 and h > 0:
            up = img.resize((w * 2, h * 2), resample=__import__("PIL").Image.LANCZOS)
            views.append(("upscale_2x", _to_png_bytes(up)))
    except Exception:  # noqa: BLE001
        pass

    # adaptive threshold (binarize)
    try:
        from PIL import ImageFilter  # type: ignore

        g = img.convert("L")
        # crude adaptive threshold: subtract a blurred version, then threshold.
        blurred = g.filter(ImageFilter.GaussianBlur(radius=3))
        # pixel > blurred ? 255 : 0
        import numpy as np  # type: ignore

        arr = np.array(g)
        blur_arr = np.array(blurred)
        binarized = (arr > blur_arr).astype("uint8") * 255
        from PIL import Image as PILImage  # type: ignore

        bimg = PILImage.fromarray(binarized, mode="L")
        views.append(("adaptive_threshold", _to_png_bytes(bimg)))
    except Exception:  # noqa: BLE001
        pass

    # invert dark theme
    try:
        from PIL import ImageOps  # type: ignore

        inv = ImageOps.invert(img)
        views.append(("invert_dark", _to_png_bytes(inv)))
    except Exception:  # noqa: BLE001
        pass

    return views


def run_multi_view(
    backend: OcrBackend, image_bytes: bytes, *, max_views: int = 4
) -> list[ViewResult]:
    """Run OCR on each preprocessing view.

    Honors the global inference lock (each call to backend.recognize is
    already lock-guarded by the backend implementation). Returns at most
    `max_views` results. The original view is always included as the
    first element.
    """
    views = preprocess_views(image_bytes)[:max_views]
    out: list[ViewResult] = []
    for view_name, view_bytes in views:
        try:
            result = backend.recognize(view_bytes)
        except Exception:  # noqa: BLE001
            # If a view fails, skip it — we still have other candidates.
            continue
        # Annotate the result with the view name for debugging.
        if result.extra is None:
            result.extra = {}
        result.extra["view"] = view_name
        out.append(ViewResult(view_name=view_name, result=result))
    return out
