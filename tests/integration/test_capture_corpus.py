"""TASK_10 capture-completeness tests.

Verifies:
- native PDF text is preferred over OCR text layer (no duplicate);
- DOM code blocks do not produce a duplicate visual block;
- decorative images are classified with a reason;
- every visual block has an explicit coverage_state;
- provenance includes page+bbox (PDF) or DOM selector (URL/HTML);
- lazy-loaded images (data-src, srcset, picture/source) are captured;
- copy-button payloads are preferred as the code text source;
- mixed scanned/native pages handle both correctly;
- multi-column detection works.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from writeup2md.adapters.pdf import convert_pdf
from writeup2md.config import Profile, build_config
from writeup2md.coverage import (
    COVERAGE_STATES,
    assert_all_visuals_covered,
    coverage_summary,
)
from writeup2md.dom_extract import extract_blocks_from_html
from writeup2md.models import BlockType, VisualBlockState


CAPTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "capture"


def _ensure_pdfs():
    """Regenerate capture PDFs if missing."""
    if not (CAPTURE_DIR / "native.pdf").is_file():
        import sys
        sys.path.insert(0, str(CAPTURE_DIR))
        import _gen  # type: ignore
        _gen.main()


_ensure_pdfs()


def _read_html(name: str) -> str:
    return (CAPTURE_DIR / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Coverage ledger
# ---------------------------------------------------------------------------


def test_coverage_states_canonical_set():
    """The canonical coverage state set is exactly the 6 expected states."""
    expected = {
        "transcribed",
        "native_text_used",
        "decorative_with_reason",
        "duplicate_with_reference",
        "review_required",
        "failed_with_diagnostic",
    }
    assert set(COVERAGE_STATES) == expected


def test_assert_all_visuals_covered_passes_when_explicit():
    """Blocks with explicit coverage_state pass the assertion."""
    from writeup2md.coverage import apply_coverage_state
    from writeup2md.models import Block, VisualBlockState, VisualType

    b = Block(
        block_id="b_000000",
        order=0,
        type=BlockType.VISUAL,
        visual_type=VisualType.CODE,
        visual_state=VisualBlockState.RESOLVED_OCR,
    )
    apply_coverage_state(b, "transcribed", "ocr ok")
    assert_all_visuals_covered([b])  # should not raise


def test_assert_all_visuals_covered_raises_on_missing():
    """A visual block with neither coverage_state nor a resolvable visual_state raises."""
    from writeup2md.models import Block, VisualBlockState, VisualType

    b = Block(
        block_id="b_000000",
        order=0,
        type=BlockType.VISUAL,
        visual_type=VisualType.UNKNOWN,
        visual_state=VisualBlockState.REVIEW_REQUIRED,
    )
    with pytest.raises(AssertionError, match="lack explicit coverage state"):
        assert_all_visuals_covered([b])


def test_coverage_summary_counts():
    from writeup2md.coverage import apply_coverage_state
    from writeup2md.models import Block, VisualBlockState, VisualType

    b1 = Block(
        block_id="b1",
        order=0,
        type=BlockType.VISUAL,
        visual_type=VisualType.CODE,
        visual_state=VisualBlockState.RESOLVED_OCR,
    )
    apply_coverage_state(b1, "transcribed", "ok")
    b2 = Block(
        block_id="b2",
        order=1,
        type=BlockType.VISUAL,
        visual_type=VisualType.DECORATIVE,
        visual_state=VisualBlockState.IGNORED_DECORATIVE,
    )
    apply_coverage_state(b2, "decorative_with_reason", "tiny icon")
    b3 = Block(
        block_id="b3",
        order=2,
        type=BlockType.PARAGRAPH,
        text="hello",
    )

    summary = coverage_summary([b1, b2, b3])
    assert summary["total_visual_blocks"] == 2
    assert summary["by_state"]["transcribed"] == 1
    assert summary["by_state"]["decorative_with_reason"] == 1
    assert summary["missing"] == 0
    assert summary["all_covered"] is True


# ---------------------------------------------------------------------------
# PDF adapter
# ---------------------------------------------------------------------------


def test_pdf_native_text_extracted_no_duplicate(tmp_path: Path):
    """Native PDF text is extracted once; no duplicate emission."""
    cfg = build_config(Profile.MACBOOK)
    result = convert_pdf(
        source=str(CAPTURE_DIR / "native.pdf"),
        output_root=tmp_path,
        config=cfg,
        keep_evidence=True,
    )
    doc = json.loads((result.document_dir / "document.json").read_text(encoding="utf-8"))
    # Count occurrences of "import requests" — should appear exactly once.
    text_blob = "\n".join(b.get("text", "") for b in doc["blocks"])
    assert text_blob.count("import requests") == 1


def test_pdf_native_text_appears_in_markdown(tmp_path: Path):
    cfg = build_config(Profile.MACBOOK)
    result = convert_pdf(
        source=str(CAPTURE_DIR / "native.pdf"),
        output_root=tmp_path,
        config=cfg,
        keep_evidence=True,
    )
    md = (result.document_dir / "document.md").read_text(encoding="utf-8")
    assert "import requests" in md
    assert "![" not in md
    assert "<img" not in md


def test_pdf_native_provenance_has_page_and_bbox(tmp_path: Path):
    """Every native text block evidence record has page + bbox."""
    cfg = build_config(Profile.MACBOOK)
    result = convert_pdf(
        source=str(CAPTURE_DIR / "native.pdf"),
        output_root=tmp_path,
        config=cfg,
        keep_evidence=True,
    )
    doc = json.loads((result.document_dir / "document.json").read_text(encoding="utf-8"))
    for b in doc["blocks"]:
        if b["type"] == "horizontal_rule":
            continue
        for ev in b.get("evidence", []):
            if ev.get("kind") == "pdf_region":
                assert isinstance(ev.get("page"), int)
                bbox = ev.get("bbox")
                assert isinstance(bbox, list)
                assert len(bbox) == 4


def test_pdf_scanned_page_emits_visual_block_with_coverage(tmp_path: Path):
    """Scanned PDF: page is rendered as image; visual block has review_required coverage state."""
    cfg = build_config(Profile.MACBOOK)
    # TASK_15: pin rapid for capture-mechanics tests so they don't
    # depend on which OCR backend is installed. PaddleOCR-VL element
    # mode is exercised separately under tests/real_paddleocr_vl/.
    cfg.ocr.backend = "rapid"
    result = convert_pdf(
        source=str(CAPTURE_DIR / "scanned.pdf"),
        output_root=tmp_path,
        config=cfg,
        keep_evidence=True,
    )
    doc = json.loads((result.document_dir / "document.json").read_text(encoding="utf-8"))
    visuals = [b for b in doc["blocks"] if b["type"] == "visual"]
    assert len(visuals) >= 1
    assert all(v.get("coverage_state") == "review_required" for v in visuals)


def test_pdf_mixed_page_emits_native_then_visual(tmp_path: Path):
    """Mixed PDF: page 1 emits native text; page 2 emits a scanned visual block."""
    cfg = build_config(Profile.MACBOOK)
    # TASK_15: pin rapid for capture-mechanics tests.
    cfg.ocr.backend = "rapid"
    result = convert_pdf(
        source=str(CAPTURE_DIR / "mixed.pdf"),
        output_root=tmp_path,
        config=cfg,
        keep_evidence=True,
    )
    doc = json.loads((result.document_dir / "document.json").read_text(encoding="utf-8"))
    md = (result.document_dir / "document.md").read_text(encoding="utf-8")
    # Native text from page 1 must be present.
    assert "Page 1 native text" in md
    # A visual block for the scanned page 2 must be present.
    visuals = [b for b in doc["blocks"] if b["type"] == "visual"]
    assert len(visuals) >= 1


def test_pdf_multicolumn_detected(tmp_path: Path):
    """Multi-column PDF triggers a column-detection warning."""
    cfg = build_config(Profile.MACBOOK)
    result = convert_pdf(
        source=str(CAPTURE_DIR / "multicolumn.pdf"),
        output_root=tmp_path,
        config=cfg,
        keep_evidence=True,
    )
    diag = json.loads((result.document_dir / "diagnostics.json").read_text(encoding="utf-8"))
    warnings = " ".join(diag.get("processing_warnings", []))
    assert "column" in warnings.lower()


def test_pdf_visual_coverage_ledger_in_diagnostics(tmp_path: Path):
    """diagnostics.json contains a visual_coverage summary."""
    cfg = build_config(Profile.MACBOOK)
    # TASK_15: pin rapid for capture-mechanics tests.
    cfg.ocr.backend = "rapid"
    result = convert_pdf(
        source=str(CAPTURE_DIR / "scanned.pdf"),
        output_root=tmp_path,
        config=cfg,
        keep_evidence=True,
    )
    diag = json.loads((result.document_dir / "diagnostics.json").read_text(encoding="utf-8"))
    vc = diag.get("visual_coverage")
    assert vc is not None
    assert "by_state" in vc
    assert "missing" in vc
    assert vc.get("total_visual_blocks", 0) >= 1


# ---------------------------------------------------------------------------
# DOM extraction
# ---------------------------------------------------------------------------


def test_dom_copy_button_payload_preferred():
    """The copy-button payload is used as the native code text source."""
    html = _read_html("copy_button.html")
    blocks, _ = extract_blocks_from_html(
        html=html, source_kind="url", source_ref="x", canonical_source="x"
    )
    code_blocks = [b for b in blocks if b.type == BlockType.NATIVE_CODE]
    assert len(code_blocks) == 1
    # The copy-button payload includes the 'json=' line — make sure it came
    # from the button rather than the <pre>.
    assert "json={'user': 'admin'}" in (code_blocks[0].text or "")
    assert code_blocks[0].extra.get("text_source") == "copy_button"


def test_dom_lazy_load_data_src_captured():
    """data-src attribute is captured in DomImage."""
    html = _read_html("lazy_load.html")
    blocks, images = extract_blocks_from_html(
        html=html, source_kind="url", source_ref="x", canonical_source="x"
    )
    assert any(img.data_src for img in images), "expected at least one image with data-src"
    # The lazy-loaded image's best_url should be the data-src.
    lazy = [img for img in images if img.data_src]
    assert lazy
    assert "lazy/screenshot.png" in (lazy[0].best_url() or "")


def test_dom_srcset_captured():
    """srcset attribute is captured in DomImage."""
    html = _read_html("lazy_load.html")
    _blocks, images = extract_blocks_from_html(
        html=html, source_kind="url", source_ref="x", canonical_source="x"
    )
    srcset_imgs = [img for img in images if img.srcset]
    assert srcset_imgs, "expected at least one image with srcset"


def test_dom_native_code_plus_screenshot_no_duplicate_visual():
    """When a <pre><code> block exists AND an adjacent image is its screenshot,
    no separate visual block is created for the screenshot (DOM priority)."""
    html = _read_html("native_plus_screenshot.html")
    blocks, images = extract_blocks_from_html(
        html=html, source_kind="url", source_ref="x", canonical_source="x"
    )
    code_blocks = [b for b in blocks if b.type == BlockType.NATIVE_CODE]
    assert len(code_blocks) == 1
    # The image is still recorded in the images list (for provenance) but
    # NO visual block is emitted for it.
    visuals = [b for b in blocks if b.type == BlockType.VISUAL]
    assert len(visuals) == 0, f"expected 0 visual blocks, got {len(visuals)}"
    # Image should still be recorded.
    assert len(images) >= 1


def test_dom_decorative_classification():
    """Decorative images (emoji, avatar, logo, tiny) are classified decorative
    with a reason; content images remain unresolved visuals.
    """
    html = _read_html("decorative_mixed.html")
    blocks, _images = extract_blocks_from_html(
        html=html, source_kind="url", source_ref="x", canonical_source="x"
    )
    visuals = [b for b in blocks if b.type == BlockType.VISUAL]
    decorative = [b for b in visuals if b.visual_state == VisualBlockState.IGNORED_DECORATIVE]
    content = [b for b in visuals if b.visual_state == VisualBlockState.REVIEW_REQUIRED]
    # emoji (class hint), avatar (class hint), logo (class hint) → 3 decorative
    # content (Burp screenshot) → 1 unresolved
    assert len(decorative) >= 3
    assert len(content) >= 1
    for d in decorative:
        assert d.coverage_state == "decorative_with_reason"
        assert d.coverage_reason
    for c in content:
        assert c.coverage_state == "review_required"


def test_dom_visual_blocks_have_explicit_coverage_state():
    """Every visual block in any HTML fixture ends in an explicit coverage state."""
    for fname in ("copy_button.html", "lazy_load.html", "decorative_mixed.html"):
        html = _read_html(fname)
        blocks, _ = extract_blocks_from_html(
            html=html, source_kind="url", source_ref="x", canonical_source="x"
        )
        visuals = [b for b in blocks if b.type == BlockType.VISUAL]
        for v in visuals:
            assert v.coverage_state in COVERAGE_STATES, (
                f"{fname}: visual {v.block_id} has coverage_state={v.coverage_state!r}"
            )


def test_dom_provenance_has_selector():
    """Every visual block evidence record has a DOM selector."""
    html = _read_html("decorative_mixed.html")
    blocks, _ = extract_blocks_from_html(
        html=html, source_kind="url", source_ref="x", canonical_source="x"
    )
    for b in blocks:
        if b.type != BlockType.VISUAL:
            continue
        for ev in b.evidence:
            assert ev.selector, f"visual {b.block_id} has empty selector"
            assert ev.kind.value == "dom_element"


# ---------------------------------------------------------------------------
# End-to-end conversion
# ---------------------------------------------------------------------------


def test_html_conversion_has_complete_coverage_ledger(tmp_path: Path):
    """Converting a capture HTML fixture produces a diagnostics.json with a
    complete visual_coverage ledger (missing == 0)."""
    from writeup2md.adapters.url import _convert_html_string

    cfg = build_config(Profile.MACBOOK)
    html = _read_html("decorative_mixed.html")
    result = _convert_html_string(
        html=html,
        base_url="https://example.com/deco.html",
        source="https://example.com/deco.html",
        output_root=tmp_path,
        config=cfg,
        force=False,
        keep_evidence=True,
        explicit_id=None,
        tags=None,
        extra=None,
    )
    diag = json.loads((result.document_dir / "diagnostics.json").read_text(encoding="utf-8"))
    vc = diag.get("visual_coverage")
    assert vc is not None
    assert vc.get("missing", 1) == 0, f"expected missing=0, got {vc}"
    assert vc.get("all_covered") is True
