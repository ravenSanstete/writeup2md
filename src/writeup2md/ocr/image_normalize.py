"""Image normalization for OCR input.

TASK_17.B: inspect magic bytes, decode via PIL, downscale to a
sane maximum dimension, and produce a PNG that is safe to send to
PaddleOCR-VL element mode.

The original asset is never overwritten — the normalized output is
written alongside it under evidence/visuals/<block_id>/normalized/.
"""
from __future__ import annotations

import io
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# PaddleOCR-VL is a 0.9B VLM trained on roughly document-sized inputs.
# Sending 4387×2784 cover-spread images caused runaway generation
# (>1000 tokens of "0"s, hallucinated English). 1568 px on the long
# side is a safe upper bound that preserves code-legibility while
# keeping inference tractable.
DEFAULT_MAX_LONG_SIDE = 1568


@dataclass
class NormalizedImage:
    """Result of normalizing an image for OCR input."""

    original_bytes: bytes
    original_format: str  # "png", "jpeg", "webp", "svg", "unknown"
    original_width: int
    original_height: int
    normalized_bytes: bytes
    normalized_width: int
    normalized_height: int
    normalization_steps: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.normalized_bytes)


def _detect_format(data: bytes) -> str:
    """Identify image format from magic bytes."""
    if len(data) >= 8 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if len(data) >= 3 and data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if len(data) >= 4 and data[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    if len(data) >= 12 and data[:4] == b"\x00\x00\x00\x0c":
        # Heuristic for AVIF — ftyp box with avif/avis brand
        if data[8:12] in (b"avif", b"avis", b"mif1"):
            return "avif"
    if len(data) >= 5 and data[:5] in (b"<?xml", b"<svg>") or (
        b"<svg" in data[:1024]
    ):
        return "svg"
    if data.startswith(b"data:image/"):
        return "data-uri"
    return "unknown"


def _decode_data_uri(data: bytes) -> bytes:
    """Decode a `data:image/...;base64,<...>` URI into raw image bytes."""
    try:
        s = data.decode("ascii", errors="ignore")
        # Format: data:image/png;base64,<base64>
        if "," not in s:
            return b""
        head, _, payload = s.partition(",")
        import base64

        return base64.b64decode(payload)
    except Exception:  # noqa: BLE001
        return b""


def normalize_image_for_ocr(
    image_bytes: bytes,
    *,
    max_long_side: int = DEFAULT_MAX_LONG_SIDE,
) -> NormalizedImage:
    """Normalize image bytes to a PNG no larger than max_long_side on the long side.

    The original is preserved. SVG inputs are rasterized via cairosvg when
    available; otherwise an error is returned and the caller should skip
    OCR rather than sending the SVG directly.
    """
    fmt = _detect_format(image_bytes)
    steps: list[str] = [f"detected_format:{fmt}"]

    if fmt == "data-uri":
        image_bytes = _decode_data_uri(image_bytes)
        if not image_bytes:
            return NormalizedImage(
                original_bytes=image_bytes,
                original_format=fmt,
                original_width=0,
                original_height=0,
                normalized_bytes=b"",
                normalized_width=0,
                normalized_height=0,
                error="could not decode data URI",
            )
        fmt = _detect_format(image_bytes)
        steps.append(f"decoded_data_uri_to:{fmt}")

    if fmt == "svg":
        try:
            import cairosvg  # type: ignore

            png_bytes = cairosvg.svg2png(
                bytestring=image_bytes,
                output_width=None,
                output_height=None,
            )
            image_bytes = png_bytes
            fmt = "png"
            steps.append("rasterized_svg")
        except ImportError:
            return NormalizedImage(
                original_bytes=image_bytes,
                original_format="svg",
                original_width=0,
                original_height=0,
                normalized_bytes=b"",
                normalized_width=0,
                normalized_height=0,
                error="cairosvg not installed; cannot rasterize SVG",
            )
        except Exception as e:  # noqa: BLE001
            return NormalizedImage(
                original_bytes=image_bytes,
                original_format="svg",
                original_width=0,
                original_height=0,
                normalized_bytes=b"",
                normalized_width=0,
                normalized_height=0,
                error=f"svg rasterization failed: {e}",
            )

    try:
        from PIL import Image  # type: ignore
    except ImportError as e:
        return NormalizedImage(
            original_bytes=image_bytes,
            original_format=fmt,
            original_width=0,
            original_height=0,
            normalized_bytes=b"",
            normalized_width=0,
            normalized_height=0,
            error=f"Pillow not installed: {e}",
        )

    try:
        img = Image.open(io.BytesIO(image_bytes))
        img = img.convert("RGB")
    except Exception as e:  # noqa: BLE001
        return NormalizedImage(
            original_bytes=image_bytes,
            original_format=fmt,
            original_width=0,
            original_height=0,
            normalized_bytes=b"",
            normalized_width=0,
            normalized_height=0,
            error=f"could not decode image: {e}",
        )

    orig_w, orig_h = img.size
    needs_downscale = max(orig_w, orig_h) > max_long_side
    if needs_downscale:
        scale = float(max_long_side) / float(max(orig_w, orig_h))
        new_w = max(1, int(round(orig_w * scale)))
        new_h = max(1, int(round(orig_h * scale)))
        try:
            img = img.resize((new_w, new_h), Image.LANCZOS)
            steps.append(f"downscaled:{orig_w}x{orig_h}->{new_w}x{new_h}")
        except Exception as e:  # noqa: BLE001
            return NormalizedImage(
                original_bytes=image_bytes,
                original_format=fmt,
                original_width=orig_w,
                original_height=orig_h,
                normalized_bytes=b"",
                normalized_width=0,
                normalized_height=0,
                error=f"downscale failed: {e}",
            )

    out_buf = io.BytesIO()
    img.save(out_buf, format="PNG")
    norm_bytes = out_buf.getvalue()
    steps.append("encoded_png")
    return NormalizedImage(
        original_bytes=image_bytes,
        original_format=fmt,
        original_width=orig_w,
        original_height=orig_h,
        normalized_bytes=norm_bytes,
        normalized_width=img.size[0],
        normalized_height=img.size[1],
        normalization_steps=steps,
    )


def save_normalized_evidence(
    *,
    document_dir: Path,
    block_id: str,
    original_bytes: bytes,
    original_ext: str,
    normalized: NormalizedImage,
    provenance: dict[str, Any] | None = None,
) -> Path:
    """Persist original + normalized evidence under evidence/visuals/<block_id>/.

    Returns the path to the normalized PNG.
    """
    base = document_dir / "evidence" / "visuals" / block_id
    (base / "original").mkdir(parents=True, exist_ok=True)
    (base / "normalized").mkdir(parents=True, exist_ok=True)
    (base / "candidates").mkdir(parents=True, exist_ok=True)
    (base / "original" / f"asset.{original_ext.lstrip('.')}").write_bytes(original_bytes)
    norm_path = base / "normalized" / "input.png"
    norm_path.write_bytes(normalized.normalized_bytes)
    if provenance:
        import json

        (base / "provenance.json").write_text(
            json.dumps(provenance, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    return norm_path


__all__ = [
    "DEFAULT_MAX_LONG_SIDE",
    "NormalizedImage",
    "normalize_image_for_ocr",
    "save_normalized_evidence",
]
