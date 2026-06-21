"""Unit tests for OCR router classification."""

from __future__ import annotations

from writeup2md.models import Block, BlockType, VisualType
from writeup2md.ocr.router import (
    classify_from_context,
    classify_from_text,
    detect_language,
)


def _visual(extra: dict | None = None) -> Block:
    return Block(
        block_id="b_0",
        order=0,
        type=BlockType.VISUAL,
        extra=extra or {},
    )


def test_classify_decorative_from_alt():
    b = _visual({"alt": "site logo"})
    assert classify_from_context(b) == VisualType.DECORATIVE


def test_classify_diagram_from_alt():
    b = _visual({"alt": "architecture diagram"})
    assert classify_from_context(b) == VisualType.DIAGRAM


def test_classify_http_from_surrounding_text():
    b = _visual({"alt": ""})
    assert (
        classify_from_context(b, preceding_text="The HTTP request is shown:")
        == VisualType.HTTP
    )


def test_classify_terminal_from_surrounding_text():
    b = _visual({"alt": ""})
    assert classify_from_context(b, preceding_text="Terminal output:") == VisualType.TERMINAL


def test_classify_diff_from_surrounding_text():
    b = _visual({"alt": ""})
    assert classify_from_context(b, preceding_text="The git diff below") == VisualType.DIFF


def test_classify_http_from_text():
    text = "GET /api/users HTTP/1.1\nHost: example.com"
    assert classify_from_text(text) == VisualType.HTTP


def test_classify_diff_from_text():
    text = "--- a/foo.py\n+++ b/foo.py\n@@ -1,3 +1,3 @@\n-old\n+new"
    assert classify_from_text(text) == VisualType.DIFF


def test_classify_terminal_from_text():
    text = "$ ls -la\ntotal 0\n$ whoami\nroot"
    assert classify_from_text(text) == VisualType.TERMINAL


def test_classify_traceback_from_text():
    text = 'Traceback (most recent call last):\n  File "x.py", line 1, in <module>\n    raise Exception("boom")'
    assert classify_from_text(text) == VisualType.STACK_TRACE


def test_classify_log_from_text():
    text = "2026-06-19 12:00:00 INFO starting up\n2026-06-19 12:01:00 ERROR failed"
    assert classify_from_text(text) == VisualType.LOG


def test_classify_yaml_config():
    text = "host: example.com\nport: 8080\nssl: true"
    assert classify_from_text(text) == VisualType.CONFIGURATION


def test_classify_json_config():
    text = '{\n  "host": "example.com",\n  "port": 8080\n}'
    assert classify_from_text(text) == VisualType.CONFIGURATION


def test_classify_ini_config():
    text = "[server]\nhost = example.com\nport = 8080"
    assert classify_from_text(text) == VisualType.CONFIGURATION


def test_classify_code_default():
    text = "def hello():\n    print('hi')"
    assert classify_from_text(text, fallback=VisualType.CODE) == VisualType.CODE


def test_detect_language_python():
    assert detect_language("def f():\n    return 1", VisualType.CODE) == "python"


def test_detect_language_http():
    assert detect_language("GET / HTTP/1.1", VisualType.HTTP) == "http"


def test_detect_language_diff():
    assert detect_language("--- a\n+++ b", VisualType.DIFF) == "diff"


def test_detect_language_terminal():
    assert detect_language("$ ls", VisualType.TERMINAL) == "bash"


def test_detect_language_json():
    assert detect_language('{"a": 1}', VisualType.CONFIGURATION) == "json"
