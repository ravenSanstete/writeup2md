"""Generate synthetic PDF fixtures for TASK_10 capture tests.

Run manually:
    python tests/fixtures/capture/_gen.py

The test suite also regenerates PDFs if missing (via the `ensure_*`
helpers), so manual regeneration is only needed when adding new fixtures.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_fitz():
    try:
        import fitz  # noqa: F401
        return fitz
    except ImportError as e:  # pragma: no cover
        raise SystemExit(
            "pymupdf is required to generate capture fixtures: pip install pymupdf"
        ) from e


def gen_native_pdf(path: Path) -> None:
    """A native-text PDF with code-like content."""
    fitz = _ensure_fitz()
    doc = fitz.open()
    page = doc.new_page()
    text = (
        "SQL Injection 101\n\n"
        "Reconnaissance\n\n"
        "First we enumerate the target. The following Python script sends\n"
        "a basic HTTP request to the server:\n\n"
        "import requests\n"
        "resp = requests.get('https://example.com/login')\n"
        "print(resp.status_code)\n\n"
        "Mitigation\n\n"
        "Use parameterized queries."
    )
    page.insert_text((72, 72), text, fontsize=11)
    doc.save(str(path))
    doc.close()


def gen_scanned_pdf(path: Path) -> None:
    """A scanned PDF: render text to a pixmap, then put the image on a page
    with NO native text objects.
    """
    fitz = _ensure_fitz()
    # Step 1: create a temporary PDF with text.
    src = fitz.open()
    src_page = src.new_page()
    src_page.insert_text(
        (72, 72),
        "This is scanned content.\n"
        "import os\n"
        "print('hello')\n",
        fontsize=12,
    )
    # Step 2: render to a pixmap, then create a new PDF with only the image.
    pix = src_page.get_pixmap(dpi=72)
    img_bytes = pix.tobytes("jpg")
    src.close()

    out = fitz.open()
    page = out.new_page()
    page.insert_image(page.rect, stream=img_bytes)
    out.save(str(path))
    out.close()


def gen_mixed_pdf(path: Path) -> None:
    """Mixed PDF: page 1 native text, page 2 scanned (image-only)."""
    fitz = _ensure_fitz()
    doc = fitz.open()
    # Page 1: native.
    p1 = doc.new_page()
    p1.insert_text((72, 72), "Page 1 native text.\n\nimport requests\n", fontsize=11)
    # Page 2: scanned.
    src = fitz.open()
    sp = src.new_page()
    sp.insert_text((72, 72), "Page 2 scanned.\nprint('hello')\n", fontsize=12)
    pix = sp.get_pixmap(dpi=72)
    img_bytes = pix.tobytes("jpg")
    src.close()
    p2 = doc.new_page()
    p2.insert_image(p2.rect, stream=img_bytes)
    doc.save(str(path))
    doc.close()


def gen_multicolumn_pdf(path: Path) -> None:
    """A two-column PDF: left column text blocks and right column text blocks
    at overlapping y-coordinates.
    """
    fitz = _ensure_fitz()
    doc = fitz.open()
    page = doc.new_page()
    width = page.rect.width
    mid = width / 2.0
    # Left column blocks.
    for i, t in enumerate(["Left col line 1", "Left col line 2", "Left col line 3"]):
        page.insert_text((72, 100 + i * 60), t, fontsize=11)
    # Right column blocks (same y-range).
    for i, t in enumerate(["Right col line 1", "Right col line 2", "Right col line 3"]):
        page.insert_text((mid + 30, 100 + i * 60), t, fontsize=11)
    doc.save(str(path))
    doc.close()


def main() -> int:
    here = Path(__file__).resolve().parent
    gen_native_pdf(here / "native.pdf")
    gen_scanned_pdf(here / "scanned.pdf")
    gen_mixed_pdf(here / "mixed.pdf")
    gen_multicolumn_pdf(here / "multicolumn.pdf")
    print(f"Generated PDF fixtures in {here}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
