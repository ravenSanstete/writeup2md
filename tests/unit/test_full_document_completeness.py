from __future__ import annotations

from writeup2md.pdf_checkpoint import (
    _looks_chatty_visual_description,
    _looks_extremely_duplicated,
    _looks_one_char_per_line,
    _looks_repeated_hallucinated_chars,
)


def test_detects_one_character_per_line_pattern() -> None:
    text = "\n".join("abcdefghijabcdefghij")
    assert _looks_one_char_per_line(text)


def test_detects_extreme_duplicate_lines() -> None:
    text = "\n".join(["HEADER"] * 25 + ["body"] * 2)
    assert _looks_extremely_duplicated(text)


def test_detects_chatty_visual_description() -> None:
    text = "The provided image is a graphic design and does not contain any chart."
    assert _looks_chatty_visual_description(text)


def test_detects_repeated_hallucinated_chars() -> None:
    assert _looks_repeated_hallucinated_chars("0" * 100)
