from __future__ import annotations

import json
from pathlib import Path

from writeup2md.models import (
    Block,
    BlockType,
    EnrichedVisual,
    EvidenceKind,
    EvidenceRef,
    SourceType,
    VisualBlockState,
    VisualType,
)
from writeup2md.reconstruction import reconstruct_cross_page_blocks


def _ev(page: int, y0: float = 100.0, y1: float = 120.0) -> EvidenceRef:
    return EvidenceRef(
        kind=EvidenceKind.PDF_REGION,
        page=page,
        bbox=[10.0, y0, 200.0, y1],
        asset_path="",
    )


def _block(i: int, text: str, page: int, *, y0: float = 100.0, kind=BlockType.PARAGRAPH) -> Block:
    return Block(
        block_id=f"b_{i:06d}",
        order=i,
        type=kind,
        text=text,
        evidence=[_ev(page, y0, y0 + 20)],
        source_kind=SourceType.PDF,
    )


def _visual(i: int, text: str, page: int, *, y0: float = 760.0) -> Block:
    return Block(
        block_id=f"b_{i:06d}",
        order=i,
        type=BlockType.VISUAL,
        visual_type=VisualType.CODE,
        visual_state=VisualBlockState.RESOLVED_OCR,
        enrichment=EnrichedVisual(
            visual_type=VisualType.CODE,
            raw_text=text,
            selected_text=text,
            confidence=0.95,
            review_required=False,
        ),
        evidence=[_ev(page, y0, y0 + 20)],
        source_kind=SourceType.PDF,
    )


def test_repeated_header_footer_removed_with_strong_evidence() -> None:
    blocks = []
    for page in range(5):
        blocks.append(_block(page * 2, "A Bug Hunter's Diary", page, y0=30))
        blocks.append(_block(page * 2 + 1, f"Unique body {page}", page, y0=200))

    out, removed = reconstruct_cross_page_blocks(blocks)

    assert len(removed) == 5
    assert all("A Bug Hunter" not in (b.text or "") for b in out)
    assert any("Unique body 3" in (b.text or "") for b in out)


def test_odd_even_running_headers_removed() -> None:
    blocks = []
    for page in range(8):
        header = "Chapter 2    16" if page % 2 == 0 else "Back to the '90s    17"
        blocks.append(_block(page * 2, header, page, y0=30))
        blocks.append(_block(page * 2 + 1, f"Body content page {page}", page, y0=220))

    out, removed = reconstruct_cross_page_blocks(blocks)

    assert removed
    assert all("Chapter 2" not in (b.text or "") for b in out)
    assert all("Back to the" not in (b.text or "") for b in out)
    assert any("Body content page 7" in (b.text or "") for b in out)


def test_tcpdf_generator_visual_removed() -> None:
    blocks = []
    for page in range(3):
        blocks.append(_visual(page * 2, "Powered by TCPDF (www.tcpdf.org)", page))
        blocks.append(_block(page * 2 + 1, f"Useful text {page}", page, y0=200))

    out, removed = reconstruct_cross_page_blocks(blocks)

    assert len(removed) == 3
    assert all("TCPDF" not in (b.enrichment.selected_text if b.enrichment else b.text or "") for b in out)


def test_page_number_only_removed() -> None:
    blocks = []
    for page in range(4):
        blocks.append(_block(page * 2, str(page + 1), page, y0=770))
        blocks.append(_block(page * 2 + 1, f"Body paragraph {page}", page, y0=200))

    out, removed = reconstruct_cross_page_blocks(blocks)

    assert len(removed) == 4
    assert all((b.text or "").strip() not in {"1", "2", "3", "4"} for b in out)


def test_repeated_code_is_not_removed() -> None:
    blocks = [
        _block(i, "print('same')", i, y0=30, kind=BlockType.NATIVE_CODE)
        for i in range(5)
    ]

    out, removed = reconstruct_cross_page_blocks(blocks)

    assert len(out) == 5
    assert removed == []


def test_toc_entries_are_not_removed_as_furniture() -> None:
    blocks = []
    for page in range(5):
        blocks.append(_block(page * 2, "Chapter 1: Bug Hunting . . . . 3", page, y0=260))
        blocks.append(_block(page * 2 + 1, f"TOC body {page}", page, y0=300))

    out, removed = reconstruct_cross_page_blocks(blocks)

    assert removed == []
    assert len(out) == 10


def test_cross_page_paragraph_dehyphenation_for_prose() -> None:
    blocks = [
        _block(1, "The request was still send-", 0),
        _block(2, "ing when the server closed the socket.", 1),
    ]

    out, _ = reconstruct_cross_page_blocks(blocks)

    assert len(out) == 1
    assert out[0].text == "The request was still sending when the server closed the socket."
    assert "dehyphenated_cross_page_prose" in out[0].extra["transformations"]


def test_cross_page_paragraph_does_not_dehyphenate_codeish_text() -> None:
    blocks = [
        _block(1, "Run curl --head-", 0),
        _block(2, "ers http://example.test", 1),
    ]

    out, _ = reconstruct_cross_page_blocks(blocks)

    assert len(out) == 2


def test_header_footer_between_cross_page_paragraph_is_removed_then_merged() -> None:
    blocks = [
        _block(1, "The parser continued send-", 0, y0=500),
        _block(2, "Chapter 4    52", 0, y0=760),
        _block(3, "ing bytes after the page break.", 1, y0=100),
        _block(4, "Chapter 4    53", 1, y0=760),
        _block(5, "A complete paragraph.", 2, y0=100),
        _block(6, "Chapter 4    54", 2, y0=760),
    ]

    out, removed = reconstruct_cross_page_blocks(blocks)

    assert len(removed) == 3
    assert len(out) == 2
    assert out[0].text == "The parser continued sending bytes after the page break."


def test_cross_page_code_merge_same_language() -> None:
    a = _block(1, "if user:", 0, kind=BlockType.NATIVE_CODE)
    a.language = "python"
    b = _block(2, "    print(user)", 1, kind=BlockType.NATIVE_CODE)
    b.language = "python"

    out, _ = reconstruct_cross_page_blocks([a, b])

    assert len(out) == 1
    assert out[0].text == "if user:\n    print(user)"
    assert "merged_cross_page_code" in out[0].extra["transformations"]


def test_cross_page_code_merge_line_number_continuity() -> None:
    a = _block(1, "10 if (argc > 1) {\n11     puts(argv[1]);", 0, kind=BlockType.NATIVE_CODE)
    a.language = "c"
    b = _block(2, "12 }\n13 return 0;", 1, kind=BlockType.NATIVE_CODE)
    b.language = "c"

    out, _ = reconstruct_cross_page_blocks([a, b])

    assert len(out) == 1
    assert "12 }" in (out[0].text or "")


def test_unsafe_merge_candidate_recorded(tmp_path: Path) -> None:
    blocks = [
        _block(1, "This line may continue", 0),
        _block(2, "but the next block is a heading-like paragraph", 1, kind=BlockType.QUOTE),
    ]

    reconstruct_cross_page_blocks(blocks, document_dir=tmp_path)

    diagnostics = json.loads((tmp_path / "reconstruction_diagnostics.json").read_text())
    assert diagnostics["unsafe_merge_candidates_skipped"] == 1
