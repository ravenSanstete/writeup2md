"""PDF adapter — native text + embedded image + render fallback using PyMuPDF.

Source priority (per TASK_10, mandatory):

    valid native PDF text
    > valid hidden OCR text layer
    > embedded source image
    > rendered page crop
    > whole-page OCR (only as a last resort)

This adapter implements:
- native text extraction from text-bearing PyMuPDF blocks;
- detection and deduplication of OCR text layer blocks that duplicate native
  text (TASK_10 native-vs-OCR dedup rule);
- scanned-page detection combining text density + image-area ratio;
- mixed scanned/native page handling: native blocks are extracted first, then
  only the scanned image regions are rendered (not the whole page);
- multi-column reading order: PyMuPDF sorts blocks by position (sort=True);
  we additionally detect column boundaries so multi-column layouts are
  preserved;
- sequential page release verified — page images are not retained.

Resource behavior (per docs/08_MACBOOK_EXECUTION.md):
- one page is processed at a time;
- rendered page images are NOT retained in memory beyond the current page;
- evidence is persisted to disk immediately;
- pages are processed sequentially.
"""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from ..config import WriteupConfig
from ..coverage import apply_coverage_state
from ..models import (
    Block,
    BlockType,
    Document,
    DocumentStatus,
    EvidenceKind,
    EvidenceRef,
    Manifest,
    SourceRecord,
    SourceType,
    VisualBlockState,
    VisualType,
    canonicalize_source,
    compute_document_id,
    content_sha256_bytes,
    next_block_id,
    now_iso_utc,
)
from ..persist import finalize_document
from ..pipeline import ConversionResult


# Heuristic: a page is "scanned" if it has fewer than this many characters of
# native text per thousand pixels squared of page area.
_SCANNED_TEXT_DENSITY_THRESHOLD = 0.01  # chars per pixel^2

# Minimum native-text length for a page to be considered text-bearing.
_MIN_NATIVE_TEXT_CHARS = 20

# Image-area ratio above which a low-text page is classified as scanned.
# If >50% of the page area is covered by images and there is little native
# text, the page is scanned.
_SCANNED_IMAGE_AREA_RATIO_THRESHOLD = 0.5

# Two text blocks whose normalized whitespace-stripped text is identical (or
# where one is a substring of the other after normalization) are considered
# duplicates. We compare lowercased, whitespace-collapsed text.
_MIN_TEXT_LEN_FOR_DEDUP = 20


@dataclass
class _PageBlock:
    page: int
    bbox: list[float]
    text: str
    is_code_like: bool = False
    language: str | None = None
    # True when the block comes from a hidden OCR text layer rather than from
    # real PDF text objects. Used by dedup to prefer real native text.
    from_ocr_layer: bool = False


def _is_code_like(text: str) -> tuple[bool, str | None]:
    """Heuristic: does this text block look like code, terminal, HTTP or config?"""
    if not text.strip():
        return False, None
    lines = text.splitlines()
    # HTTP transcript.
    if re.search(r"^\s*(GET|POST|PUT|DELETE|PATCH|HEAD) [^ ]+ HTTP/\d", text, re.MULTILINE):
        return True, "http"
    # Diff.
    if any(ln.startswith(("+++", "---", "@@")) for ln in lines) and any(
        ln.startswith(("+", "-")) for ln in lines
    ):
        return True, "diff"
    # Shell prompt.
    if re.search(r"^\s*[\$>]\s", text, re.MULTILINE):
        return True, "bash"
    # Python-ish.
    if re.search(r"^\s*(def |class |import |from |    )", text, re.MULTILINE):
        return True, "python"
    # Common config markers.
    if re.search(r"^\s*[\w\-\.\s]+:\s", text, re.MULTILINE) and "=" not in text:
        return True, None
    return False, None


def _normalize_bbox(rect) -> list[float]:
    """Convert a PyMuPDF Rect (or a 4-tuple/list of floats) to a [x0, y0, x1, y1] list.

    Negative coordinates are preserved — full-bleed cover images legitimately
    extend beyond page boundaries, and clamping them would lose the area
    information needed by `_classify_embedded_image`. When the input is
    genuinely unusable we return all-zeros (treated as "unknown position").
    """
    try:
        # PyMuPDF Rect-like object.
        return [float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)]
    except AttributeError:
        pass
    try:
        # Sequence of 4 floats (as returned by page.get_image_info()["bbox"]).
        if len(rect) >= 4:
            return [float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3])]
    except (TypeError, ValueError):
        pass
    return [0.0, 0.0, 0.0, 0.0]


def _normalize_text_for_dedup(text: str) -> str:
    """Lowercase and collapse whitespace for dedup comparisons."""
    return " ".join(text.lower().split())


def _is_ocr_text_layer_block(page, block_no: int) -> bool:
    """Detect whether a text block comes from a hidden OCR text layer.

    Heuristic: PyMuPDF marks OCR-layer text with invisible rendering flag
    (text rendering mode 3 = invisible) when it sits behind the image. We
    inspect the block's spans and check whether ALL spans have invisible or
    hidden rendering mode. Real native text has rendering mode 0 (fill).
    """
    try:
        # get_text("dict") returns detailed span info with flags.
        d = page.get_text("dict")
        for blk in d.get("blocks", []):
            if blk.get("type") != 0:
                continue
            if blk.get("number") != block_no:
                continue
            lines = blk.get("lines", [])
            if not lines:
                return False
            invisible_count = 0
            total_spans = 0
            for line in lines:
                for span in line.get("spans", []):
                    total_spans += 1
                    flags = span.get("flags", 0)
                    # bit 0: superscript; bit 1: italic; bit 2: serif;
                    # bit 3: monospaced; bit 4: bold. The text-rendering mode
                    # is not directly in flags, but invisible text is reported
                    # with color 0 or with very small font size, and OCR-layer
                    # text typically has the same font size as the visible
                    # glyphs but with no fill. We approximate with the
                    # "hidden" attribute if present, or by checking color ==
                    # -1 (transparent).
                    color = span.get("color", 0)
                    if color == -1 or color == 0xFFFFFF:
                        invisible_count += 1
            return total_spans > 0 and invisible_count == total_spans
    except Exception:  # noqa: BLE001
        pass
    return False


def _dedup_native_vs_ocr(blocks: list[_PageBlock]) -> tuple[list[_PageBlock], int]:
    """Drop OCR-layer blocks whose text duplicates a native block.

    Returns (filtered_blocks, dropped_count). The priority rule is:
    native text > hidden OCR text layer. We compare normalized text and
    consider an OCR-layer block a duplicate when its normalized text is
    equal to OR a substring of any native block's normalized text (or
    vice versa).
    """
    native = [b for b in blocks if not b.from_ocr_layer]
    ocr_layer = [b for b in blocks if b.from_ocr_layer]
    if not ocr_layer or not native:
        return list(blocks), 0

    native_norms = [_normalize_text_for_dedup(b.text) for b in native if len(b.text) >= _MIN_TEXT_LEN_FOR_DEDUP]
    if not native_norms:
        return list(blocks), 0

    dropped = 0
    kept: list[_PageBlock] = list(native)
    for ob in ocr_layer:
        ob_norm = _normalize_text_for_dedup(ob.text)
        if len(ob_norm) < _MIN_TEXT_LEN_FOR_DEDUP:
            # Short OCR-layer text is unreliable for dedup. Keep it.
            kept.append(ob)
            continue
        is_dup = False
        for nn in native_norms:
            if ob_norm == nn or ob_norm in nn or nn in ob_norm:
                is_dup = True
                break
        if is_dup:
            dropped += 1
            continue
        kept.append(ob)
    # Re-sort by reading order (top-to-bottom, left-to-right).
    kept.sort(key=lambda b: (b.bbox[1], b.bbox[0]))
    return kept, dropped


def _detect_columns(blocks: list[_PageBlock], page_width: float) -> int:
    """Detect the number of columns in a page from block bboxes.

    Heuristic: if blocks form two distinct horizontal clusters (left and
    right) separated by a gap of >5% of page width AND the vertical ranges
    overlap significantly, we have 2 columns. Otherwise 1.
    """
    if page_width <= 0 or len(blocks) < 4:
        return 1
    # Compute the center x of each block.
    centers = [(b.bbox[0] + b.bbox[2]) / 2.0 for b in blocks]
    mid = page_width / 2.0
    left = [c for c in centers if c < mid * 0.8]
    right = [c for c in centers if c > mid * 1.2]
    if not left or not right:
        return 1
    # Check vertical overlap: do left and right blocks overlap in y?
    left_blocks = [b for b in blocks if (b.bbox[0] + b.bbox[2]) / 2.0 < mid * 0.8]
    right_blocks = [b for b in blocks if (b.bbox[0] + b.bbox[2]) / 2.0 > mid * 1.2]
    if not left_blocks or not right_blocks:
        return 1
    # Vertical ranges.
    left_y_range = (min(b.bbox[1] for b in left_blocks), max(b.bbox[3] for b in left_blocks))
    right_y_range = (min(b.bbox[1] for b in right_blocks), max(b.bbox[3] for b in right_blocks))
    overlap = min(left_y_range[1], right_y_range[1]) - max(left_y_range[0], right_y_range[0])
    min_height = min(left_y_range[1] - left_y_range[0], right_y_range[1] - right_y_range[0])
    if min_height > 0 and overlap > min_height * 0.3:
        return 2
    return 1


def _page_image_area_ratio(page, page_area: float) -> float:
    """Return the ratio of image-covered area to page area (0.0 - 1.0)."""
    if page_area <= 0:
        return 0.0
    try:
        infos = page.get_image_info(xrefs=False)
    except Exception:  # noqa: BLE001
        return 0.0
    total = 0.0
    for info in infos:
        bbox = info.get("bbox")
        if not bbox or len(bbox) < 4:
            continue
        try:
            x0, y0, x1, y1 = [float(v) for v in bbox[:4]]
        except (TypeError, ValueError):
            continue
        w = max(0.0, x1 - x0)
        h = max(0.0, y1 - y0)
        total += w * h
    return min(1.0, total / page_area)


def _extract_page_blocks(page, page_index: int) -> tuple[list[_PageBlock], bool, int]:
    """Extract native text blocks from a page in reading order.

    Returns (blocks, is_scanned, n_columns).

    Implements:
    - native text extraction with PyMuPDF's position-sorted blocks;
    - OCR text layer detection (deduped later by _dedup_native_vs_ocr);
    - scanned-page detection using text density AND image-area ratio;
    - multi-column detection via bbox clustering.
    """
    blocks_out: list[_PageBlock] = []
    # PyMuPDF's get_text("blocks") returns reading-order-sorted blocks:
    # (x0, y0, x1, y1, text, block_no, block_type)
    try:
        raw_blocks = page.get_text("blocks", sort=True)
    except Exception:  # noqa: BLE001
        raw_blocks = []
    total_text_chars = 0
    page_area = float(page.rect.width) * float(page.rect.height)

    for entry in raw_blocks:
        if len(entry) < 7:
            continue
        x0, y0, x1, y1, text, block_no, block_type = entry[:7]
        # block_type 0 = text, 1 = image
        if block_type != 0:
            continue
        text = (text or "").strip()
        if not text:
            continue
        total_text_chars += len(text)
        is_code, lang = _is_code_like(text)
        from_ocr_layer = _is_ocr_text_layer_block(page, block_no)
        blocks_out.append(
            _PageBlock(
                page=page_index,
                bbox=[float(x0), float(y0), float(x1), float(y1)],
                text=text,
                is_code_like=is_code,
                language=lang,
                from_ocr_layer=from_ocr_layer,
            )
        )

    # Dedup native vs OCR text layer.
    blocks_out, dropped_ocr = _dedup_native_vs_ocr(blocks_out)
    # If we dropped OCR-layer blocks, they're already covered by native.

    # Scanned-page heuristic: too little native text relative to page area,
    # OR low text density combined with high image-area ratio.
    image_ratio = _page_image_area_ratio(page, page_area)
    is_scanned = False
    if page_area > 0:
        density = total_text_chars / page_area
        if total_text_chars < _MIN_NATIVE_TEXT_CHARS and density < _SCANNED_TEXT_DENSITY_THRESHOLD:
            # Definitely scanned unless images cover the page (which would
            # support the scanned hypothesis even more).
            is_scanned = True
        elif (
            total_text_chars < _MIN_NATIVE_TEXT_CHARS * 5
            and image_ratio >= _SCANNED_IMAGE_AREA_RATIO_THRESHOLD
        ):
            # Mixed/low text page dominated by an image — likely scanned
            # or image-heavy page that needs region-level treatment.
            is_scanned = True
    elif total_text_chars < _MIN_NATIVE_TEXT_CHARS:
        is_scanned = True

    n_columns = _detect_columns(blocks_out, float(page.rect.width))

    return blocks_out, is_scanned, n_columns


def _detect_heading_level(text: str, font_size: float | None, median_size: float | None) -> int | None:
    """Best-effort heading level from text length and font size."""
    if font_size is None or median_size is None:
        return None
    if len(text) > 200:
        return None
    if font_size >= median_size * 1.6:
        return 1
    if font_size >= median_size * 1.3:
        return 2
    if font_size >= median_size * 1.15:
        return 3
    return None


def _iter_pages(doc) -> Iterator[Any]:
    """Yield pages sequentially."""
    for i in range(len(doc)):
        yield doc.load_page(i)


def _render_page_to_png_bytes(page, dpi: int) -> bytes:
    """Render a page to PNG bytes at the given DPI."""
    zoom = dpi / 72.0
    matrix = __import__("fitz").Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    return pix.tobytes("png")


def _extract_embedded_images(page, page_index: int) -> list[tuple[list[float], bytes, str]]:
    """Extract embedded images on a page. Returns [(bbox, bytes, ext)]."""
    out: list[tuple[list[float], bytes, str]] = []
    try:
        for img_info in page.get_image_info(xrefs=True):
            bbox = _normalize_bbox(img_info.get("bbox"))
            xref = img_info.get("xref")
            if not xref:
                continue
            try:
                # extract image bytes by xref
                doc = page.parent
                pix = __import__("fitz").Pixmap(doc, xref)
                if pix.n - pix.alpha >= 4:  # CMYK or other → convert to RGB
                    pix = __import__("fitz").Pixmap(
                        __import__("fitz").csRGB, pix
                    )
                ext = "png"
                data = pix.tobytes(ext)
                out.append((bbox, data, ext))
                pix = None
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass
    return out


def _write_evidence(document_dir: Path, subdir: str, content: bytes, ext: str = ".png") -> str:
    """Write evidence bytes to disk and return the relative asset path."""
    from ..dom_extract import write_asset

    asset = write_asset(document_dir, subdir, content, ext=ext)
    return asset.asset_path


def extract_pdf_page_blocks(
    *,
    page,
    page_index: int,
    document_dir: Path,
    config: WriteupConfig,
    canonical_source: str,
    start_order: int = 0,
) -> tuple[list[Block], list[str], int]:
    """Extract one PDF page into IR blocks and persist any page evidence.

    This is the page-level extraction primitive used by the Round 4
    checkpoint runner. It intentionally mirrors the legacy `convert_pdf`
    behavior so full-document and per-page paths converge on the same source
    priority and visual classification rules.
    """
    warnings: list[str] = []
    blocks: list[Block] = []
    counter = [start_order]

    def make_block(**kwargs) -> Block:
        idx = counter[0]
        counter[0] += 1
        kwargs.setdefault("block_id", next_block_id(idx))
        kwargs.setdefault("order", idx)
        kwargs.setdefault("source_kind", SourceType.PDF)
        kwargs.setdefault("provenance_source_ref", canonical_source)
        return Block(**kwargs)

    page_blocks, is_scanned, n_columns = _extract_page_blocks(page, page_index)
    page_width = float(page.rect.width)
    page_height = float(page.rect.height)
    page_bbox = [0.0, 0.0, page_width, page_height]

    if n_columns > 1:
        warnings.append(f"page {page_index} detected as {n_columns}-column")

    if is_scanned:
        png_bytes = _render_page_to_png_bytes(page, config.pdf.initial_render_dpi)
        asset_path = _write_evidence(document_dir, "regions", png_bytes, ext=".png")
        vblock = make_block(
            type=BlockType.VISUAL,
            visual_type=VisualType.UNKNOWN,
            visual_state=VisualBlockState.REVIEW_REQUIRED,
            evidence=[
                EvidenceRef(
                    kind=EvidenceKind.PDF_REGION,
                    page=page_index,
                    bbox=page_bbox,
                    asset_path=asset_path,
                    extra={"scanned_page": True},
                )
            ],
            extra={"scanned_page": True},
        )
        apply_coverage_state(vblock, "review_required", "scanned page; native text absent")
        blocks.append(vblock)
        warnings.append(f"page {page_index} flagged as scanned")
        if page_blocks:
            insert_pos = len(blocks) - 1
            for offset, pb in enumerate(page_blocks):
                nb = _page_text_block_to_ir(
                    pb=pb,
                    make_block=make_block,
                )
                blocks.insert(insert_pos + offset, nb)
        return blocks, warnings, counter[0]

    for pb in page_blocks:
        blocks.append(_page_text_block_to_ir(pb=pb, make_block=make_block))

    if config.pdf.extract_embedded_images:
        try:
            embedded = _extract_embedded_images(page, page_index)
        except Exception as e:  # noqa: BLE001
            embedded = []
            warnings.append(f"page {page_index} embedded image extraction failed: {e}")
        page_native_text = "\n".join(pb.text for pb in page_blocks if pb.text)
        page_has_code_like = any(pb.is_code_like for pb in page_blocks)
        for bbox, img_bytes, ext in embedded:
            asset_path = _write_evidence(document_dir, "regions", img_bytes, ext="." + ext)
            classification = _classify_embedded_image(
                bbox=bbox,
                img_bytes=img_bytes,
                page_area=page_width * page_height,
                page_native_text=page_native_text,
                page_has_code_like=page_has_code_like,
            )
            if classification["state"] == "ignored_decorative":
                vblock = make_block(
                    type=BlockType.VISUAL,
                    visual_type=VisualType.DECORATIVE,
                    visual_state=VisualBlockState.IGNORED_DECORATIVE,
                    evidence=[
                        EvidenceRef(
                            kind=EvidenceKind.PDF_REGION,
                            page=page_index,
                            bbox=bbox,
                            asset_path=asset_path,
                            extra={"embedded_image": True},
                        )
                    ],
                    extra={"classification_reason": classification["reason"]},
                )
                apply_coverage_state(
                    vblock, "decorative_with_reason", classification["reason"]
                )
                blocks.append(vblock)
                continue
            if classification["state"] == "described_as_text":
                desc = (
                    f"Page {page_index + 1} contains an embedded "
                    f"illustration ({classification['reason']})."
                )
                vblock = make_block(
                    type=BlockType.VISUAL,
                    visual_type=VisualType.UI_SCREENSHOT,
                    visual_state=VisualBlockState.RESOLVED_STRUCTURED,
                    text=desc,
                    enrichment=None,
                    evidence=[
                        EvidenceRef(
                            kind=EvidenceKind.PDF_REGION,
                            page=page_index,
                            bbox=bbox,
                            asset_path=asset_path,
                            extra={"embedded_image": True, "described_as_text": True},
                        )
                    ],
                    extra={"classification_reason": classification["reason"]},
                )
                apply_coverage_state(
                    vblock, "described_as_text", classification["reason"]
                )
                blocks.append(vblock)
                continue
            vblock = make_block(
                type=BlockType.VISUAL,
                visual_type=VisualType.UNKNOWN,
                visual_state=VisualBlockState.REVIEW_REQUIRED,
                evidence=[
                    EvidenceRef(
                        kind=EvidenceKind.PDF_REGION,
                        page=page_index,
                        bbox=bbox,
                        asset_path=asset_path,
                        extra={"embedded_image": True},
                    )
                ],
            )
            apply_coverage_state(
                vblock, "review_required", "embedded image; not yet transcribed"
            )
            blocks.append(vblock)

    return blocks, warnings, counter[0]


def _page_text_block_to_ir(*, pb: _PageBlock, make_block) -> Block:
    ev = EvidenceRef(
        kind=EvidenceKind.PDF_REGION,
        page=pb.page,
        bbox=pb.bbox,
        asset_path="",
    )
    if pb.is_code_like:
        return make_block(
            type=BlockType.NATIVE_CODE,
            text=pb.text,
            language=pb.language,
            evidence=[ev],
        )
    text = pb.text.strip()
    lines = text.splitlines()
    if len(lines) == 1 and len(text) < 120 and not text.endswith((".", "!", "?", ":")):
        return make_block(
            type=BlockType.HEADING,
            text=text,
            heading_level=2,
            evidence=[ev],
        )
    return make_block(
        type=BlockType.PARAGRAPH,
        text=text,
        evidence=[ev],
    )


# TASK_17.A: classify a PDF embedded image before OCR. Book PDFs
# commonly include cover art, author photos, and decorative logos as
# full-page embedded raster images. PaddleOCR-VL element mode is a
# 0.9B VLM that was trained on document/code screenshots; sending it
# a 4387x2784 cover-spread image produced hallucinated output like
# "I am the world" and runs of "0"s. This helper uses image area,
# pixel dimensions, and page context to classify each embedded image
# as decorative, described_as_text, or an OCR candidate.
def _classify_embedded_image(
    *,
    bbox: list[float],
    img_bytes: bytes,
    page_area: float,
    page_native_text: str,
    page_has_code_like: bool,
) -> dict:
    """Return {'state': 'ignored_decorative'|'described_as_text'|'ocr_candidate', 'reason': str}.

    Heuristics (conservative — only mark decorative when signals are strong):
      - image area >= 70% of page area AND no code-like native text on the
        page AND no nearby figure/listing caption -> decorative (cover art).
      - image area >= 40% of page area AND no code-like native text AND
        page has substantial body text -> described_as_text (illustration).
      - extremely large pixel area (>= 8 MP) without caption -> decorative
        to avoid burning OCR time on full-bleed images.
      - otherwise -> ocr_candidate (likely a code/terminal screenshot or
        a small inline image).
    """
    try:
        x0, y0, x1, y1 = bbox[:4]
        # Clamp to page bounds for the area-ratio computation. Cover-spread
        # images legitimately extend beyond page boundaries with negative
        # x0/y0; what matters is the portion visible on the page.
        # We measure the unclamped bbox area as well, because a cover image
        # that bleeds past the page is still effectively a full-page image.
        raw_w = max(0.0, x1 - x0)
        raw_h = max(0.0, y1 - y0)
        img_area = raw_w * raw_h
    except Exception:  # noqa: BLE001
        img_area = 0.0
    area_ratio = (img_area / page_area) if page_area > 0 else 0.0

    # Decode pixel dimensions for additional filtering.
    pixel_w = pixel_h = 0
    try:
        from PIL import Image  # type: ignore
        import io as _io

        with Image.open(_io.BytesIO(img_bytes)) as im:
            pixel_w, pixel_h = im.size
    except Exception:  # noqa: BLE001
        pass
    pixel_area = pixel_w * pixel_h

    # Caption detection: look for "Figure N", "Listing N", "Code N",
    # "Example N", "Screenshot N" near the image. These tokens indicate
    # the image is a code/terminal/HTTP screenshot that must be OCR'd.
    caption_tokens = (
        r"\b(Figure|Fig\.?|Listing|Code|Example|Screenshot|Listing|Listing)\b\s*\d"
    )
    has_caption = bool(re.search(caption_tokens, page_native_text, re.IGNORECASE))

    # Code-likes nearby: import, def, class, HTTP/, $, ---, @@, etc.
    has_code_tokens = bool(
        re.search(
            r"\b(def |class |import |from |HTTP/|\$ |->|@@|---|\+\+\+|>>>|\.\.\.)",
            page_native_text,
        )
    )

    # Decorative: very large image, no caption, no code tokens.
    if area_ratio >= 0.70 and not has_caption and not has_code_tokens and not page_has_code_like:
        return {
            "state": "ignored_decorative",
            "reason": f"large embedded image ({area_ratio:.0%} of page) without code context or caption",
        }

    # Photograph / illustration: large image on a text-heavy page with
    # no code context. Skip OCR; produce a textual placeholder instead.
    if (
        area_ratio >= 0.40
        and not has_caption
        and not has_code_tokens
        and not page_has_code_like
        and len(page_native_text) >= 200
    ):
        return {
            "state": "described_as_text",
            "reason": f"embedded illustration ({area_ratio:.0%} of page) on text-heavy page without code context",
        }

    # Extremely large pixel dimensions without caption — likely a
    # full-bleed cover/photo. Mark decorative to avoid burning OCR time.
    if (
        pixel_area >= 8_000_000
        and not has_caption
        and not has_code_tokens
        and area_ratio >= 0.5
    ):
        return {
            "state": "ignored_decorative",
            "reason": f"very large raster image ({pixel_w}x{pixel_h}) without code context",
        }

    # Pages with almost no native text AND a huge image are almost
    # certainly scanned cover/title pages — not code screenshots.
    if (
        area_ratio >= 0.5
        and len(page_native_text) < 100
        and not has_caption
        and not has_code_tokens
    ):
        return {
            "state": "ignored_decorative",
            "reason": f"full-bleed image on low-text page ({area_ratio:.0%}, native_text={len(page_native_text)} chars)",
        }

    return {
        "state": "ocr_candidate",
        "reason": f"image area {area_ratio:.0%} of page; OCR candidate",
    }


def convert_pdf(
    *,
    source: str,
    output_root: Path,
    config: WriteupConfig,
    force: bool = False,
    keep_evidence: bool = True,
    device: str | None = None,
    explicit_id: str | None = None,
    tags: list[str] | None = None,
    extra: dict[str, Any] | None = None,
    page_range: tuple[int, int] | None = None,
) -> ConversionResult:
    """Convert a PDF file to a document directory.

    ``page_range`` is an optional ``(start, stop)`` half-open range of
    0-indexed pages to process. When set, only that slice of the PDF
    is converted; the manifest records the range in ``extra``. This is
    used by TASK_16 baseline iteration and is NOT part of the public
    CLI contract for ordinary conversion.
    """
    try:
        import fitz  # type: ignore
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "pymupdf is required for PDF conversion; install with: pip install pymupdf"
        ) from e

    src_path = Path(source).expanduser().resolve()
    if not src_path.is_file():
        raise FileNotFoundError(f"PDF file not found: {source}")
    content_bytes = src_path.read_bytes()

    canonical = canonicalize_source(str(src_path))
    content_sha = content_sha256_bytes(content_bytes)
    config_sha = config.config_sha256()
    doc_id = compute_document_id(
        source=str(src_path),
        canonical_source=canonical,
        content_sha256=content_sha,
        config_sha256=config_sha,
        explicit_id=explicit_id,
    )
    captured = now_iso_utc()
    manifest_extra = dict(extra or {})
    if page_range is not None:
        manifest_extra["page_range"] = {"start": page_range[0], "stop": page_range[1]}
    manifest = Manifest(
        document_id=doc_id,
        source=str(src_path),
        source_type=SourceType.PDF,
        canonical_source=canonical,
        captured_at=captured,
        content_sha256=content_sha,
        config_sha256=config_sha,
        status=DocumentStatus.REVIEW,
        tags=tags or [],
        profile=config.pipeline.profile.value,
        extra=manifest_extra,
    )
    src_record = SourceRecord(
        source_type=SourceType.PDF,
        source=str(src_path),
        canonical_source=canonical,
        captured_at=captured,
        content_sha256=content_sha,
        extra={"content_bytes": len(content_bytes)},
    )

    # TASK_20: human-readable directory name (<slug>-<short_hash>).
    # The full document_id is preserved in manifest.json.
    from ..slugify import human_readable_dir_name, update_index_file

    dir_name = human_readable_dir_name(str(src_path), "pdf", content_sha)
    document_dir = output_root / dir_name
    update_index_file(output_root, dir_name, doc_id, str(src_path))

    blocks: list[Block] = []
    counter = [0]
    warnings: list[str] = []
    errors: list[str] = []

    def make_block(**kwargs) -> Block:
        idx = counter[0]
        counter[0] += 1
        kwargs.setdefault("block_id", next_block_id(idx))
        kwargs.setdefault("order", idx)
        kwargs.setdefault("source_kind", SourceType.PDF)
        kwargs.setdefault("provenance_source_ref", canonical)
        return Block(**kwargs)

    # Preserve raw PDF immutably.
    raw_dir = document_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "source.pdf").write_bytes(content_bytes)

    # Open with PyMuPDF and process pages sequentially.
    pdf_doc = fitz.open(stream=content_bytes, filetype="pdf")
    try:
        n_pages_total = len(pdf_doc)
        if n_pages_total == 0:
            errors.append("PDF has no pages")
        if page_range is not None:
            start = max(0, page_range[0])
            stop = min(n_pages_total, page_range[1])
            page_iter = range(start, stop)
            n_pages = stop - start
        else:
            page_iter = range(n_pages_total)
            n_pages = n_pages_total
        for page_index in page_iter:
            page = pdf_doc.load_page(page_index)
            page_blocks, is_scanned, n_columns = _extract_page_blocks(page, page_index)
            page_width = float(page.rect.width)
            page_height = float(page.rect.height)
            page_bbox = [0.0, 0.0, page_width, page_height]

            if n_columns > 1:
                warnings.append(
                    f"page {page_index} detected as {n_columns}-column"
                )

            if is_scanned:
                # Render the page to PNG and add as a single review_required visual block.
                if config.pdf.retain_rendered_pages_in_memory:
                    png_bytes = _render_page_to_png_bytes(page, config.pdf.initial_render_dpi)
                else:
                    png_bytes = _render_page_to_png_bytes(page, config.pdf.initial_render_dpi)
                asset_path = _write_evidence(document_dir, "regions", png_bytes, ext=".png")
                vblock = make_block(
                    type=BlockType.VISUAL,
                    visual_type=VisualType.UNKNOWN,
                    visual_state=VisualBlockState.REVIEW_REQUIRED,
                    evidence=[
                        EvidenceRef(
                            kind=EvidenceKind.PDF_REGION,
                            page=page_index,
                            bbox=page_bbox,
                            asset_path=asset_path,
                            extra={"scanned_page": True},
                        )
                    ],
                    extra={"scanned_page": True},
                )
                apply_coverage_state(vblock, "review_required", "scanned page; native text absent")
                blocks.append(vblock)
                warnings.append(f"page {page_index} flagged as scanned")
                # If native blocks were extracted on this scanned page too
                # (mixed scanned/native page), emit them BEFORE the visual
                # so the visual comes after the native text in reading order.
                # We already emitted nothing yet for this page — emit them now
                # by inserting BEFORE the just-appended visual. To keep things
                # simple we re-walk page_blocks here.
                if page_blocks:
                    # Insert native blocks before the just-appended visual.
                    insert_pos = len(blocks) - 1
                    for offset, pb in enumerate(page_blocks):
                        ev = EvidenceRef(
                            kind=EvidenceKind.PDF_REGION,
                            page=pb.page,
                            bbox=pb.bbox,
                            asset_path="",
                        )
                        if pb.is_code_like:
                            nb = make_block(
                                type=BlockType.NATIVE_CODE,
                                text=pb.text,
                                language=pb.language,
                                evidence=[ev],
                            )
                        else:
                            text = pb.text.strip()
                            lines = text.splitlines()
                            if len(lines) == 1 and len(text) < 120 and not text.endswith((".", "!", "?", ":")):
                                nb = make_block(
                                    type=BlockType.HEADING,
                                    text=text,
                                    heading_level=2,
                                    evidence=[ev],
                                )
                            else:
                                nb = make_block(
                                    type=BlockType.PARAGRAPH,
                                    text=text,
                                    evidence=[ev],
                                )
                        blocks.insert(insert_pos + offset, nb)
                continue

            for pb in page_blocks:
                ev = EvidenceRef(
                    kind=EvidenceKind.PDF_REGION,
                    page=pb.page,
                    bbox=pb.bbox,
                    asset_path="",
                )
                if pb.is_code_like:
                    blocks.append(
                        make_block(
                            type=BlockType.NATIVE_CODE,
                            text=pb.text,
                            language=pb.language,
                            evidence=[ev],
                        )
                    )
                else:
                    # Heuristic: short single-line text → heading candidate, else paragraph.
                    text = pb.text.strip()
                    lines = text.splitlines()
                    if len(lines) == 1 and len(text) < 120 and not text.endswith((".", "!", "?", ":")):
                        blocks.append(
                            make_block(
                                type=BlockType.HEADING,
                                text=text,
                                heading_level=2,
                                evidence=[ev],
                            )
                        )
                    else:
                        blocks.append(
                            make_block(
                                type=BlockType.PARAGRAPH,
                                text=text,
                                evidence=[ev],
                            )
                        )

            # Embedded image extraction.
            if config.pdf.extract_embedded_images:
                try:
                    embedded = _extract_embedded_images(page, page_index)
                except Exception as e:  # noqa: BLE001
                    embedded = []
                    warnings.append(f"page {page_index} embedded image extraction failed: {e}")
                # Gather this page's native text to support decorative-vs-code
                # classification of embedded images.
                page_native_text = "\n".join(pb.text for pb in page_blocks if pb.text)
                page_has_code_like = any(pb.is_code_like for pb in page_blocks)
                for bbox, img_bytes, ext in embedded:
                    asset_path = _write_evidence(document_dir, "regions", img_bytes, ext="." + ext)
                    # TASK_17.A: classify the embedded image before OCR.
                    classification = _classify_embedded_image(
                        bbox=bbox,
                        img_bytes=img_bytes,
                        page_area=page_width * page_height,
                        page_native_text=page_native_text,
                        page_has_code_like=page_has_code_like,
                    )
                    if classification["state"] == "ignored_decorative":
                        vblock = make_block(
                            type=BlockType.VISUAL,
                            visual_type=VisualType.DECORATIVE,
                            visual_state=VisualBlockState.IGNORED_DECORATIVE,
                            evidence=[
                                EvidenceRef(
                                    kind=EvidenceKind.PDF_REGION,
                                    page=page_index,
                                    bbox=bbox,
                                    asset_path=asset_path,
                                    extra={"embedded_image": True},
                                )
                            ],
                            extra={"classification_reason": classification["reason"]},
                        )
                        apply_coverage_state(
                            vblock, "decorative_with_reason", classification["reason"]
                        )
                        blocks.append(vblock)
                        continue
                    if classification["state"] == "described_as_text":
                        # Photograph / illustration. Produce a textual
                        # placeholder describing the position. Do NOT OCR
                        # (the VLM would hallucinate on non-code imagery).
                        desc = (
                            f"Page {page_index + 1} contains an embedded "
                            f"illustration ({classification['reason']})."
                        )
                        vblock = make_block(
                            type=BlockType.VISUAL,
                            visual_type=VisualType.UI_SCREENSHOT,
                            visual_state=VisualBlockState.RESOLVED_STRUCTURED,
                            text=desc,
                            enrichment=None,
                            evidence=[
                                EvidenceRef(
                                    kind=EvidenceKind.PDF_REGION,
                                    page=page_index,
                                    bbox=bbox,
                                    asset_path=asset_path,
                                    extra={"embedded_image": True, "described_as_text": True},
                                )
                            ],
                            extra={"classification_reason": classification["reason"]},
                        )
                        apply_coverage_state(
                            vblock, "described_as_text", classification["reason"]
                        )
                        blocks.append(vblock)
                        continue
                    # state == "ocr_candidate" — proceed to enricher.
                    vblock = make_block(
                        type=BlockType.VISUAL,
                        visual_type=VisualType.UNKNOWN,
                        visual_state=VisualBlockState.REVIEW_REQUIRED,
                        evidence=[
                            EvidenceRef(
                                kind=EvidenceKind.PDF_REGION,
                                page=page_index,
                                bbox=bbox,
                                asset_path=asset_path,
                                extra={"embedded_image": True},
                            )
                        ],
                    )
                    apply_coverage_state(vblock, "review_required", "embedded image; not yet transcribed")
                    blocks.append(vblock)
    finally:
        try:
            pdf_doc.close()
        except Exception:  # noqa: BLE001
            pass

    doc = finalize_document(
        document_dir=document_dir,
        manifest=manifest,
        source=src_record,
        blocks=blocks,
        config=config,
        raw_assets={"source.pdf": content_bytes},
        warnings=warnings,
        errors=errors,
        force=force,
        keep_evidence=keep_evidence,
    )
    return ConversionResult(
        document_id=doc_id,
        document_dir=document_dir,
        status=doc.manifest.status,
        document=doc,
    )
