from __future__ import annotations

from writeup2md.models import Block, BlockType, EvidenceKind, EvidenceRef, SourceType
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


def test_repeated_header_footer_removed_with_strong_evidence() -> None:
    blocks = []
    for page in range(5):
        blocks.append(_block(page * 2, "A Bug Hunter's Diary", page, y0=30))
        blocks.append(_block(page * 2 + 1, f"Unique body {page}", page, y0=200))

    out, removed = reconstruct_cross_page_blocks(blocks)

    assert len(removed) == 5
    assert all("A Bug Hunter" not in (b.text or "") for b in out)
    assert any("Unique body 3" in (b.text or "") for b in out)


def test_repeated_code_is_not_removed() -> None:
    blocks = [
        _block(i, "print('same')", i, y0=30, kind=BlockType.NATIVE_CODE)
        for i in range(5)
    ]

    out, removed = reconstruct_cross_page_blocks(blocks)

    assert len(out) == 5
    assert removed == []


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


def test_cross_page_code_merge_same_language() -> None:
    a = _block(1, "if user:", 0, kind=BlockType.NATIVE_CODE)
    a.language = "python"
    b = _block(2, "    print(user)", 1, kind=BlockType.NATIVE_CODE)
    b.language = "python"

    out, _ = reconstruct_cross_page_blocks([a, b])

    assert len(out) == 1
    assert out[0].text == "if user:\n    print(user)"
    assert "merged_cross_page_code" in out[0].extra["transformations"]
