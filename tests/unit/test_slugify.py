"""TASK_20 slugify tests."""

from __future__ import annotations

from pathlib import Path

from writeup2md.slugify import (
    slugify_source,
    human_readable_dir_name,
    update_index_file,
    MAX_SLUG_LEN,
    SHORT_HASH_LEN,
)


def test_slugify_pdf_path_uses_filename_stem():
    s = slugify_source("/path/to/A Bug Hunters Diary.pdf", "pdf")
    assert s == "a-bug-hunters-diary"


def test_slugify_html_path_uses_filename_stem():
    s = slugify_source("/path/to/tutorial.html", "html")
    assert s == "tutorial"


def test_slugify_url_uses_host_and_last_segment():
    s = slugify_source("https://example.com/articles/foo-bar", "url")
    assert s == "example-com-foo-bar"


def test_slugify_url_strips_www():
    s = slugify_source("https://www.example.com/post", "url")
    assert s == "example-com-post"


def test_slugify_url_no_path_uses_host_only():
    s = slugify_source("https://example.com", "url")
    assert s == "example-com"


def test_slugify_handles_unicode_filename():
    """Chinese filename: non-ASCII chars become spaces, then hyphens."""
    s = slugify_source("/path/to/漏洞战争.pdf", "pdf")
    # Non-ASCII chars are replaced with spaces (which become hyphens).
    # The exact output depends on the regex; verify it's filesystem-safe.
    assert all(c.isalnum() or c == "-" for c in s)
    assert len(s) > 0


def test_slugify_truncates_long_names():
    long_name = "a" * 200 + ".pdf"
    s = slugify_source(f"/path/to/{long_name}", "pdf")
    assert len(s) <= MAX_SLUG_LEN


def test_slugify_handles_special_chars():
    s = slugify_source("/path/to/Real-World Bug Hunting! (2024).pdf", "pdf")
    assert s == "real-world-bug-hunting-2024"


def test_human_readable_dir_name_combines_slug_and_short_hash():
    name = human_readable_dir_name(
        "/path/to/tutorial.html", "html",
        "b7aeaacb17879fd945e08d761a1a8cf42bbb171533808a045117c16f05b5e23e",
    )
    assert name == "tutorial-b7aeaacb"
    assert len(name.split("-")[-1]) == SHORT_HASH_LEN


def test_human_readable_dir_name_falls_back_on_empty_hash():
    name = human_readable_dir_name("/path/to/tutorial.html", "html", "")
    assert name.endswith("-00000000")


def test_update_index_file_creates_parent_and_writes_mapping(tmp_path: Path):
    out = tmp_path / "outputs"
    out.mkdir(parents=True, exist_ok=True)
    update_index_file(out, "tutorial-b7aeaacb", "af1841eeffdff224", "/path/to/tutorial.html")
    import json
    index_path = out / ".index.json"
    assert index_path.is_file()
    data = json.loads(index_path.read_text(encoding="utf-8"))
    assert "tutorial-b7aeaacb" in data
    assert data["tutorial-b7aeaacb"]["document_id"] == "af1841eeffdff224"
    assert data["tutorial-b7aeaacb"]["source"] == "/path/to/tutorial.html"


def test_update_index_file_appends_to_existing(tmp_path: Path):
    out = tmp_path / "outputs"
    out.mkdir(parents=True, exist_ok=True)
    update_index_file(out, "doc1-aaaaaaaa", "id1", "/path/to/doc1.pdf")
    update_index_file(out, "doc2-bbbbbbbb", "id2", "/path/to/doc2.pdf")
    import json
    data = json.loads((out / ".index.json").read_text(encoding="utf-8"))
    assert len(data) == 2
    assert "doc1-aaaaaaaa" in data
    assert "doc2-bbbbbbbb" in data


def test_update_index_file_overwrites_on_same_dir_name(tmp_path: Path):
    """Re-converting the same source updates the mapping (no duplicates)."""
    out = tmp_path / "outputs"
    out.mkdir(parents=True, exist_ok=True)
    update_index_file(out, "tutorial-b7aeaacb", "old-id", "/path/to/tutorial.html")
    update_index_file(out, "tutorial-b7aeaacb", "new-id", "/path/to/tutorial.html")
    import json
    data = json.loads((out / ".index.json").read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data["tutorial-b7aeaacb"]["document_id"] == "new-id"
