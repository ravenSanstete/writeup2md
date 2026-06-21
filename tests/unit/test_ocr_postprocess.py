"""Unit tests for OCR post-processing."""

from __future__ import annotations

from writeup2md.ocr.postprocess import postprocess, split_terminal_commands


def test_postprocess_strips_editor_line_numbers():
    raw = "1  import os\n2  import sys\n3  print('hi')\n4  exit()"
    r = postprocess(raw_text=raw, visual_type="code", language="python", base_confidence=0.9)
    assert "1  " not in r.selected_text
    assert "import os" in r.selected_text
    assert "removed_editor_line_numbers" in r.transformations


def test_postprocess_preserves_real_code_with_numbers():
    raw = "import os\n0x10 == 16\nx = 1.5"
    r = postprocess(raw_text=raw, visual_type="code", language="python", base_confidence=0.9)
    # Should not strip line numbers since they aren't editor chrome.
    assert "0x10" in r.selected_text


def test_postprocess_normalizes_crlf():
    raw = "line1\r\nline2\r\nline3"
    r = postprocess(raw_text=raw, visual_type="code", language="text", base_confidence=0.9)
    assert "\r" not in r.selected_text
    assert "line1\nline2\nline3" in r.selected_text


def test_split_terminal_commands_basic():
    text = "$ ls\nfile.txt\n$ whoami\nroot"
    segs = split_terminal_commands(text)
    assert len(segs) >= 2
    assert any(s["role"] == "command" and "ls" in s["text"] for s in segs)
    assert any(s["role"] == "output" and "file.txt" in s["text"] for s in segs)


def test_split_terminal_commands_no_prompt_returns_output_only():
    text = "just some output\nwithout prompts"
    segs = split_terminal_commands(text)
    assert all(s["role"] == "output" for s in segs)


def test_postprocess_terminal_emits_segments():
    text = "$ python exploit.py\n[+] success"
    r = postprocess(raw_text=text, visual_type="terminal", language="bash", base_confidence=0.9)
    assert "terminal_command_output_split" in r.transformations
    assert any(s["role"] == "command" for s in r.segments)


def test_postprocess_http_preserves_verbatim():
    text = "POST /login HTTP/1.1\nHost: example.com\n\nuser=admin"
    r = postprocess(raw_text=text, visual_type="http", language="http", base_confidence=0.9)
    assert "POST /login HTTP/1.1" in r.selected_text
    assert "user=admin" in r.selected_text


def test_postprocess_diff_preserves_markers():
    text = "--- a/x.py\n+++ b/x.py\n@@ -1,3 +1,3 @@\n-old\n+new\n ctx"
    r = postprocess(raw_text=text, visual_type="diff", language="diff", base_confidence=0.9)
    assert "---" in r.selected_text
    assert "+++" in r.selected_text
    assert "-old" in r.selected_text
    assert "+new" in r.selected_text
