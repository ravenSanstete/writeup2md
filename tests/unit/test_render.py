"""Tests for the Markdown renderer and image-reference stripping."""

from __future__ import annotations

import pytest

from writeup2md.models import (
    Block,
    BlockType,
    Document,
    DocumentStatus,
    EnrichedVisual,
    Manifest,
    SourceRecord,
    SourceType,
    VisualBlockState,
    VisualType,
)
from writeup2md.render import (
    _strip_editor_line_numbers,
    count_image_references,
    render_block_markdown,
    render_markdown,
    strip_image_references,
)


def _doc(blocks: list[Block]) -> Document:
    return Document(
        manifest=Manifest(
            document_id="d",
            source="x",
            source_type=SourceType.HTML,
            canonical_source="x",
            captured_at="2026-06-19T00:00:00Z",
            content_sha256="a" * 64,
            config_sha256="b" * 64,
            status=DocumentStatus.ACCEPTED,
        ),
        source=SourceRecord(
            source_type=SourceType.HTML,
            source="x",
            canonical_source="x",
            captured_at="2026-06-19T00:00:00Z",
            content_sha256="a" * 64,
        ),
        blocks=blocks,
    )


def test_render_heading_and_paragraph():
    blocks = [
        Block(block_id="b_000000", order=0, type=BlockType.HEADING, text="Title", heading_level=1),
        Block(block_id="b_000001", order=1, type=BlockType.PARAGRAPH, text="Hello world."),
    ]
    md = render_markdown(_doc(blocks))
    assert md.startswith("# Title")
    assert "Hello world." in md


def test_render_native_code_block():
    b = Block(
        block_id="b_000000",
        order=0,
        type=BlockType.NATIVE_CODE,
        text="print('hi')",
        language="python",
    )
    md = render_block_markdown(b)
    assert md == "```python\nprint('hi')\n```"


def test_render_visual_resolved_uses_enrichment_text():
    b = Block(
        block_id="b_000001",
        order=1,
        type=BlockType.VISUAL,
        visual_type=VisualType.TERMINAL,
        visual_state=VisualBlockState.RESOLVED_OCR,
        enrichment=EnrichedVisual(
            visual_type=VisualType.TERMINAL,
            raw_text="$ ls\nfile.txt",
            selected_text="$ ls\nfile.txt",
            language="bash",
            confidence=0.95,
        ),
    )
    md = render_block_markdown(b)
    assert md.startswith("```bash")
    assert "$ ls" in md


def test_render_visual_unresolved_emits_notice_in_document_mode():
    """In document mode, an unresolved visual emits a textual notice
    (never silent, never an image link). In strict mode it emits an
    HTML-comment marker so the review UI can locate the block."""
    b = Block(
        block_id="b_000002",
        order=2,
        type=BlockType.VISUAL,
        visual_type=VisualType.CODE,
        visual_state=VisualBlockState.REVIEW_REQUIRED,
    )
    md_doc = render_block_markdown(b, mode="document")
    assert "unresolved" in md_doc.lower()
    assert "```" not in md_doc  # no fenced block (no text to put in it)
    assert "![" not in md_doc  # no image link

    md_strict = render_block_markdown(b, mode="strict")
    # Strict mode emits a marker (REVIEW REQUIRED or UNRESOLVED) for the
    # review UI to locate the block.
    assert "writeup2md:" in md_strict
    assert "```" not in md_strict


def test_render_visual_review_required_with_text_surfaces_it_in_document_mode():
    """TASK_18: in document mode, review_required with non-empty text
    surfaces the transcription with a notice. In strict mode it emits
    a marker for the review UI."""
    b = Block(
        block_id="b_000004",
        order=4,
        type=BlockType.VISUAL,
        visual_type=VisualType.CODE,
        visual_state=VisualBlockState.REVIEW_REQUIRED,
        enrichment=EnrichedVisual(
            visual_type=VisualType.CODE,
            raw_text="import os",
            selected_text="import os",
            confidence=0.0,
        ),
    )
    md_doc = render_block_markdown(b, mode="document")
    assert "import os" in md_doc
    assert "```" in md_doc  # fenced code block
    assert "uncertain" in md_doc.lower()

    md_strict = render_block_markdown(b, mode="strict")
    assert "REVIEW REQUIRED" in md_strict
    assert "import os" not in md_strict


def test_render_visual_decorative_emits_nothing():
    """TASK_18: decorative visuals emit nothing visible. Provenance is
    preserved in document.json, not in document.md."""
    b = Block(
        block_id="b_000003",
        order=3,
        type=BlockType.VISUAL,
        visual_type=VisualType.DECORATIVE,
        visual_state=VisualBlockState.IGNORED_DECORATIVE,
        enrichment=EnrichedVisual(
            visual_type=VisualType.DECORATIVE,
            raw_text="",
            selected_text="",
            confidence=1.0,
        ),
    )
    md = render_block_markdown(b)
    assert md == ""


def test_render_http_block_uses_http_fence():
    b = Block(
        block_id="b_000004",
        order=4,
        type=BlockType.VISUAL,
        visual_type=VisualType.HTTP,
        visual_state=VisualBlockState.RESOLVED_OCR,
        enrichment=EnrichedVisual(
            visual_type=VisualType.HTTP,
            raw_text="GET / HTTP/1.1\nHost: example.com",
            selected_text="GET / HTTP/1.1\nHost: example.com",
            confidence=0.9,
        ),
    )
    md = render_block_markdown(b)
    assert md.startswith("```http")


def test_strip_image_references_removes_all_image_forms():
    md = "Before\n![alt](http://x/y.png)\n<img src='x'>\nafter"
    out = strip_image_references(md)
    assert "![" not in out
    assert "<img" not in out
    assert "Before" in out
    assert "after" in out


def test_count_image_references_zero_for_clean_md():
    md = "# Title\n\nsome text\n```python\nprint(1)\n```"
    assert count_image_references(md) == 0


def test_count_image_references_catches_base64():
    md = "text data:image/png;base64,iVBORw0KG more text"
    # base64 data image URI should be detected in raw markdown
    assert count_image_references(md) >= 1
    # and stripped from the final output
    assert count_image_references(strip_image_references(md)) == 0


def test_strip_editor_line_numbers_when_consistent():
    text = "1  import os\n2  import sys\n3  print('hi')\n4  exit()"
    out, transforms = _strip_editor_line_numbers(text)
    assert "import os" in out
    assert "1 " not in out.split("\n")[0]
    assert "removed_editor_line_numbers" in transforms


def test_strip_editor_line_numbers_leaves_real_code_alone():
    text = "import os\n0x10 == 16\nx = 1.5"
    out, transforms = _strip_editor_line_numbers(text)
    assert out == text
    assert transforms == []


def test_render_table_block():
    b = Block(
        block_id="b_000010",
        order=10,
        type=BlockType.TABLE,
        table_rows=[["a", "b"], ["1", "2"], ["3", "4"]],
    )
    md = render_block_markdown(b)
    assert "| a | b |" in md
    assert "| --- | --- |" in md
    assert "| 1 | 2 |" in md


def test_render_list_block():
    b = Block(
        block_id="b_000011",
        order=11,
        type=BlockType.LIST,
        list_items=["first", "second", "third"],
    )
    md = render_block_markdown(b)
    assert "- first" in md
    assert "- second" in md
    assert "- third" in md


def test_render_quote_block():
    b = Block(block_id="b_000012", order=12, type=BlockType.QUOTE, text="line1\nline2")
    md = render_block_markdown(b)
    assert "> line1" in md
    assert "> line2" in md


def test_render_normalizes_crlf():
    b = Block(
        block_id="b_000013",
        order=13,
        type=BlockType.NATIVE_CODE,
        text="a\r\nb\r\nc",
        language="text",
    )
    md = render_block_markdown(b)
    assert "\r" not in md


def test_render_code_fence_escapes_inner_triple_backticks():
    """TASK_18.E: a literal ``` inside a code block must be escaped with
    a longer fence (````)."""
    inner = "Here is a fenced block:\n```\nprint('hi')\n```\nDone."
    b = Block(
        block_id="b_000014",
        order=14,
        type=BlockType.NATIVE_CODE,
        text=inner,
        language="markdown",
    )
    md = render_block_markdown(b)
    # The outer fence must be longer than ``` because the content has ```.
    assert md.startswith("````")
    assert md.endswith("````")
    # The inner ``` must be preserved verbatim.
    assert "```\nprint('hi')\n```" in md


def test_render_visual_blocks_in_source_order():
    """TASK_18.C: visual blocks are inserted at their source position,
    never appended at the end."""
    blocks = [
        Block(block_id="b_000000", order=0, type=BlockType.HEADING, text="Title", heading_level=1),
        Block(block_id="b_000001", order=1, type=BlockType.PARAGRAPH, text="Before visual."),
        Block(
            block_id="b_000002",
            order=2,
            type=BlockType.VISUAL,
            visual_type=VisualType.CODE,
            visual_state=VisualBlockState.RESOLVED_OCR,
            enrichment=EnrichedVisual(
                visual_type=VisualType.CODE,
                raw_text="import os",
                selected_text="import os",
                language="python",
                confidence=0.95,
            ),
        ),
        Block(block_id="b_000003", order=3, type=BlockType.PARAGRAPH, text="After visual."),
    ]
    md = render_markdown(_doc(blocks))
    pos_before = md.find("Before visual.")
    pos_visual = md.find("import os")
    pos_after = md.find("After visual.")
    assert 0 <= pos_before < pos_visual < pos_after


def test_render_default_mode_is_document():
    """TASK_18.A: default render mode is document (no HTML comments)."""
    b = Block(
        block_id="b_000015",
        order=15,
        type=BlockType.VISUAL,
        visual_type=VisualType.CODE,
        visual_state=VisualBlockState.REVIEW_REQUIRED,
        enrichment=EnrichedVisual(
            visual_type=VisualType.CODE,
            raw_text="import os",
            selected_text="import os",
            confidence=0.0,
        ),
    )
    md_default = render_block_markdown(b)  # no mode= → default
    assert "import os" in md_default
    assert "<!--" not in md_default


def test_render_no_html_comment_markers_in_document_mode():
    """TASK_18 acceptance gate 4: no <!-- writeup2md: --> markers in
    document mode."""
    blocks = [
        Block(
            block_id="b_000016",
            order=16,
            type=BlockType.VISUAL,
            visual_type=VisualType.CODE,
            visual_state=VisualBlockState.REVIEW_REQUIRED,
            enrichment=EnrichedVisual(
                visual_type=VisualType.CODE,
                raw_text="import os",
                selected_text="import os",
                confidence=0.0,
            ),
        ),
        Block(
            block_id="b_000017",
            order=17,
            type=BlockType.VISUAL,
            visual_type=VisualType.TERMINAL,
            visual_state=VisualBlockState.FAILED,
        ),
    ]
    md = render_markdown(_doc(blocks), mode="document")
    assert "<!-- writeup2md:" not in md
    assert "REVIEW REQUIRED" not in md
    assert "UNRESOLVED" not in md
    # Textual notices must be present.
    assert "uncertain" in md.lower() or "unresolved" in md.lower()


def test_render_markdown_well_formed_fences():
    """TASK_18 acceptance gate 6: every fenced code block has matching
    open and close fences. Fence collision (inner ``` ) is escaped with
    a longer outer fence."""
    import re

    blocks = [
        Block(
            block_id="b_000020",
            order=20,
            type=BlockType.NATIVE_CODE,
            text="print(1)",
            language="python",
        ),
        Block(
            block_id="b_000021",
            order=21,
            type=BlockType.NATIVE_CODE,
            text="```inner```",
            language="text",
        ),
        Block(
            block_id="b_000022",
            order=22,
            type=BlockType.NATIVE_CODE,
            text="plain code\nwith no inner fences",
            language="text",
        ),
    ]
    md = render_markdown(_doc(blocks))

    # Walk the markdown line-by-line with a proper state machine. A line
    # of N backticks (with optional language tag) toggles code-block
    # state when N >= the current fence length. Inner content lines
    # (e.g. "```inner```") do NOT toggle because they have non-backtick
    # characters mixed in.
    in_code = False
    fence_len = 0
    for line in md.split("\n"):
        m = re.match(r"^(`{3,})(\s*\S.*)?$", line)
        if not m:
            continue
        this_len = len(m.group(1))
        has_content = m.group(2) is not None
        if not in_code:
            # Opening fence.
            in_code = True
            fence_len = this_len
        else:
            # Inside a code block: a line of N backticks with no other
            # content closes the block when N >= fence_len. Otherwise
            # it's content.
            if not has_content and this_len >= fence_len:
                in_code = False
                fence_len = 0
    assert not in_code, "unclosed code fence at end of document"
