"""Tests for DOM-order block extraction."""

from __future__ import annotations

from pathlib import Path

import pytest

from writeup2md.dom_extract import (
    extract_blocks_from_html,
    parse_html,
    select_article_root,
)


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "html" / "tutorial.html"
HTML = FIXTURE.read_text(encoding="utf-8")


def test_article_root_picks_article_tag():
    soup = parse_html(HTML)
    root = select_article_root(soup)
    assert root.name == "article"


def test_extract_emits_heading_first():
    blocks, _images = extract_blocks_from_html(
        html=HTML,
        source_kind="html",
        source_ref="x",
        canonical_source="x",
    )
    assert blocks[0].type.value == "heading"
    assert "SQL Injection 101" in (blocks[0].text or "")


def test_extract_preserves_order_of_headings_and_paragraphs():
    blocks, _ = extract_blocks_from_html(
        html=HTML, source_kind="html", source_ref="x", canonical_source="x"
    )
    types = [b.type.value for b in blocks]
    # First heading is the title (h1), then a paragraph, then h2 "Reconnaissance".
    assert types[0] == "heading"
    assert "paragraph" in types
    # the second heading (h2 Reconnaissance) appears after the first paragraph
    first_para_idx = types.index("paragraph")
    second_heading_idx = types.index("heading", 1)
    assert second_heading_idx > first_para_idx


def test_extract_native_code_blocks_with_language():
    blocks, _ = extract_blocks_from_html(
        html=HTML, source_kind="html", source_ref="x", canonical_source="x"
    )
    code_blocks = [b for b in blocks if b.type.value == "native_code"]
    assert len(code_blocks) >= 3
    langs = [b.language for b in code_blocks]
    assert "python" in langs
    assert "bash" in langs
    assert "http" in langs


def test_extract_list_block():
    blocks, _ = extract_blocks_from_html(
        html=HTML, source_kind="html", source_ref="x", canonical_source="x"
    )
    lists = [b for b in blocks if b.type.value == "list"]
    assert len(lists) >= 1
    assert "Use parameterized queries." in (lists[0].list_items or [])


def test_extract_quote_block():
    blocks, _ = extract_blocks_from_html(
        html=HTML, source_kind="html", source_ref="x", canonical_source="x"
    )
    quotes = [b for b in blocks if b.type.value == "quote"]
    assert len(quotes) >= 1
    assert "OWASP Top 10" in (quotes[0].text or "")


def test_extract_image_becomes_unresolved_visual_block():
    blocks, images = extract_blocks_from_html(
        html=HTML, source_kind="html", source_ref="x", canonical_source="x"
    )
    visuals = [b for b in blocks if b.type.value == "visual"]
    assert len(visuals) >= 1
    assert all(b.visual_state.value == "review_required" for b in visuals)
    assert all(b.visual_type.value == "unknown" for b in visuals)
    assert len(images) >= 1


def test_extract_hr_block():
    blocks, _ = extract_blocks_from_html(
        html=HTML, source_kind="html", source_ref="x", canonical_source="x"
    )
    hrs = [b for b in blocks if b.type.value == "horizontal_rule"]
    assert len(hrs) >= 1


def test_extract_skips_script_and_style():
    html = """
    <html><body><article>
      <style>.x { color: red; }</style>
      <script>console.log('hi')</script>
      <p>Real content.</p>
    </article></body></html>
    """
    blocks, _ = extract_blocks_from_html(
        html=html, source_kind="html", source_ref="x", canonical_source="x"
    )
    texts = " ".join(b.text or "" for b in blocks if b.text)
    assert "color: red" not in texts
    assert "console.log" not in texts
    assert "Real content." in texts
