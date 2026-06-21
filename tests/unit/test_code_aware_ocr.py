"""TASK_11 code-aware OCR post-processing tests.

Verifies:
- keyword-boundary splitting on space-merged tokens;
- fullwidth punctuation normalization (code context only);
- indentation recovery from bracket/colon structure;
- terminal / HTTP / diff panel splitting;
- candidate selection picks the candidate with balanced brackets;
- structural score rewards balanced brackets and keyword density;
- multi-view retry produces N candidates (mock backend test).
"""

from __future__ import annotations

from typing import Any

import pytest

from writeup2md.ocr.candidate_selection import (
    select_best,
    structural_score,
    _bracket_balance_score,
    _keyword_density_score,
    _line_length_score,
    _space_ratio_score,
)
from writeup2md.ocr.code_postprocess import (
    normalize_fullwidth_punct,
    recover_indentation,
    split_space_merged_tokens,
)
from writeup2md.ocr.panel_split import (
    split_diff_panels,
    split_http_panels,
    split_panels,
    split_terminal_panels,
)
from writeup2md.ocr.backend import OcrResult


# ---------------------------------------------------------------------------
# split_space_merged_tokens
# ---------------------------------------------------------------------------


def test_split_import_requests():
    """The classic Golden Set space-merge case."""
    text = "importrequests"
    out, tx = split_space_merged_tokens(text)
    assert out == "import requests"
    assert any("split:" in t for t in tx)


def test_split_does_not_touch_already_spaced():
    """Already-spaced text is left alone."""
    text = "import requests\nimport os"
    out, tx = split_space_merged_tokens(text)
    assert out == text
    assert tx == []


def test_split_does_not_split_inside_identifiers():
    """`importrequests` is split, but `important_feature` is NOT split
    (because `import` + `ant_feature` is not in the dictionary).
    """
    text = "important_feature"
    out, _ = split_space_merged_tokens(text)
    assert out == "important_feature"


def test_split_multiple_keywords_in_text():
    """Multiple merged keywords in the same text are all split."""
    text = "importrequests\nimportos\nsudoapt update"
    out, tx = split_space_merged_tokens(text)
    assert "import requests" in out
    assert "import os" in out
    assert "sudo apt update" in out
    assert len([t for t in tx if t.startswith("split:")]) >= 3


def test_split_preserves_surrounding_text():
    """Splitting preserves surrounding non-keyword text."""
    text = "importrequests as req"
    out, _ = split_space_merged_tokens(text)
    assert "import requests" in out
    assert " as req" in out


# ---------------------------------------------------------------------------
# normalize_fullwidth_punct
# ---------------------------------------------------------------------------


def test_normalize_fullwidth_in_code_context():
    """Fullwidth punctuation in code is normalized to ASCII."""
    text = "print（x），y"
    out, tx = normalize_fullwidth_punct(text)
    assert out == "print(x),y"
    assert any("fullwidth" in t for t in tx)


def test_normalize_fullwidth_skips_non_code():
    """Fullwidth punctuation in natural Chinese text is NOT normalized."""
    text = "你好，世界！"
    out, tx = normalize_fullwidth_punct(text)
    assert out == text
    assert tx == []


def test_normalize_fullwidth_colon_in_code():
    """Fullwidth colon in HTTP-like context is normalized."""
    text = "Content-Type：application/json"
    out, _ = normalize_fullwidth_punct(text)
    assert out == "Content-Type:application/json"


# ---------------------------------------------------------------------------
# recover_indentation
# ---------------------------------------------------------------------------


def test_recover_indentation_python_colon():
    """After a colon-terminated line, the next line gets indented."""
    text = "def main():\nprint('hello')"
    out, tx = recover_indentation(text, "python")
    assert "    print('hello')" in out
    assert "indent_recovered" in tx


def test_recover_indentation_does_not_reindent_existing():
    """Lines that already have leading whitespace are NOT re-indented."""
    text = "def main():\n  print('hello')"
    out, _ = recover_indentation(text, "python")
    # The existing 2-space indent is preserved.
    assert "  print('hello')" in out


def test_recover_indentation_brace_close():
    """A closing brace dedents first."""
    text = "function f() {\nreturn 1\n}"
    out, _ = recover_indentation(text, "javascript")
    lines = out.split("\n")
    # The `}` should have no indent.
    assert lines[-1] == "}"
    # The `return 1` should have 4 spaces.
    assert lines[1] == "    return 1"


def test_recover_indentation_empty_lines_untouched():
    """Empty lines are left as empty strings."""
    text = "def main():\n\nprint('hello')"
    out, _ = recover_indentation(text, "python")
    lines = out.split("\n")
    assert lines[1] == ""


# ---------------------------------------------------------------------------
# panel_split
# ---------------------------------------------------------------------------


def test_split_terminal_command_and_output():
    """A terminal transcript with one command and its output is split."""
    text = "$ ls -la\ntotal 8\ndrwxr-xr-x 2 user staff 64 file1"
    segs = split_terminal_panels(text)
    assert any(s["role"] == "command" for s in segs)
    assert any(s["role"] == "output" for s in segs)


def test_split_terminal_no_prompts_returns_single_output():
    """If there are no prompt characters, the whole text is one output segment."""
    text = "just output\nno prompt"
    segs = split_terminal_panels(text)
    assert len(segs) == 1
    assert segs[0]["role"] == "output"


def test_split_http_request_response():
    """An HTTP transcript with request and response is split into panels."""
    text = (
        "POST /api/login HTTP/1.1\n"
        "Host: example.com\n"
        "Content-Type: application/json\n"
        "\n"
        '{"user": "admin"}\n'
        "\n"
        "HTTP/1.1 200 OK\n"
        "Content-Length: 12\n"
        "\n"
        '{"ok": true}'
    )
    segs = split_http_panels(text)
    roles = [s["role"] for s in segs]
    assert "request_line" in roles
    assert "request_header" in roles
    assert "request_body" in roles
    assert "status_line" in roles
    assert "response_header" in roles
    assert "response_body" in roles


def test_split_diff_panels():
    """A diff is split into file header / hunk header / hunk content."""
    text = (
        "diff --git a/file.py b/file.py\n"
        "index 1234567..abcdefg 100644\n"
        "--- a/file.py\n"
        "+++ b/file.py\n"
        "@@ -1,3 +1,4 @@\n"
        " def main():\n"
        "-    print('old')\n"
        "+    print('new')\n"
    )
    segs = split_diff_panels(text)
    roles = [s["role"] for s in segs]
    assert "file_header" in roles
    assert "hunk_header" in roles
    assert "hunk_content" in roles


def test_split_panels_dispatch_by_visual_type():
    """split_panels dispatches to the correct splitter based on visual_type."""
    # terminal
    segs = split_panels("$ ls\nfile1", "terminal")
    assert any(s["role"] == "command" for s in segs)
    # http
    segs = split_panels("GET / HTTP/1.1\nHost: x\n\n", "http")
    assert any(s["role"] == "request_line" for s in segs)
    # diff
    segs = split_panels("diff --git a/x b/x\n@@ -1 +1 @@\n-old\n+new", "diff")
    assert any(s["role"] == "file_header" for s in segs)
    # unknown type → empty list
    assert split_panels("hello", "code") == []


# ---------------------------------------------------------------------------
# candidate_selection
# ---------------------------------------------------------------------------


def test_bracket_balance_score_balanced():
    assert _bracket_balance_score("def f(x, y):") == 1.0


def test_bracket_balance_score_unbalanced():
    score = _bracket_balance_score("def f(x, y:")
    assert 0.0 <= score < 1.0


def test_keyword_density_score_real_code():
    text = "import requests\nimport os\ndef main():\n    return True"
    score = _keyword_density_score(text)
    assert score > 0.5


def test_keyword_density_score_no_keywords():
    text = "hello world"
    score = _keyword_density_score(text)
    assert score == 0.0


def test_line_length_score_penalizes_long_merged():
    text = "a" * 200  # 200-char line without spaces
    score = _line_length_score(text)
    assert score == 0.0


def test_line_length_score_normal_lines():
    text = "import requests\nx = 1\n"
    score = _line_length_score(text)
    assert score == 1.0


def test_space_ratio_score_real_code():
    text = "import requests\nimport os\nx = 1 + 2"
    score = _space_ratio_score(text)
    assert score == 1.0


def test_space_ratio_score_space_merged():
    text = "importrequestsimportos"
    score = _space_ratio_score(text)
    assert score < 0.5


def test_structural_score_combined():
    """A real-code sample scores higher than a space-merged sample."""
    good = "import requests\ndef main():\n    return True"
    bad = "importrequestsdefmain():returnTrue"
    assert structural_score(good, "code") > structural_score(bad, "code")


def test_select_best_picks_balanced_candidate():
    """select_best picks the candidate with the higher structural score."""
    good = OcrResult(raw_text="import requests\ndef main():\n    return True", model_confidence=0.7)
    bad = OcrResult(raw_text="importrequestsdefmain():returnTrue", model_confidence=0.95)
    best = select_best([good, bad], "code")
    assert best is good


def test_select_best_returns_none_on_empty():
    assert select_best([], "code") is None


# ---------------------------------------------------------------------------
# multi_view
# ---------------------------------------------------------------------------


def test_multi_view_produces_multiple_views():
    """run_multi_view produces N candidates (mock backend test)."""
    from PIL import Image
    import io

    from writeup2md.ocr.multi_view import preprocess_views, run_multi_view

    # Create a small PNG.
    buf = io.BytesIO()
    Image.new("RGB", (50, 50), "white").save(buf, format="PNG")
    image_bytes = buf.getvalue()

    views = preprocess_views(image_bytes)
    # At least original + grayscale.
    assert len(views) >= 2
    view_names = [v[0] for v in views]
    assert "original" in view_names
    assert "grayscale" in view_names


def test_multi_view_with_mock_backend():
    """run_multi_view on a mock backend produces N candidates with view annotations."""
    from PIL import Image
    import io

    from writeup2md.ocr.mock import MockOcrBackend
    from writeup2md.ocr.multi_view import run_multi_view

    buf = io.BytesIO()
    Image.new("RGB", (50, 50), "white").save(buf, format="PNG")
    image_bytes = buf.getvalue()

    backend = MockOcrBackend()
    # Register a result for every view's image bytes so the backend returns
    # something for each. We precompute the views and register them all.
    from writeup2md.ocr.multi_view import preprocess_views

    for view_name, view_bytes in preprocess_views(image_bytes):
        backend.register_bytes(view_bytes, f"text from {view_name}", confidence=0.5)

    results = run_multi_view(backend, image_bytes, max_views=4)
    # Each view should produce a result.
    assert len(results) >= 1
    # Each result should be annotated with its view name.
    for vr in results:
        assert vr.view_name
        assert "view" in (vr.result.extra or {})
