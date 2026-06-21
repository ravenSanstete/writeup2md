"""Tests for workspace layout and atomic IO."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from writeup2md.workspace import (
    DOCUMENT_JSON,
    DOCUMENT_MD,
    DIAGNOSTICS_JSON,
    EVIDENCE_DIR,
    EVIDENCE_ELEMENTS_DIR,
    EVIDENCE_REGIONS_DIR,
    MANIFEST_JSON,
    PROVENANCE_JSONL,
    RAW_DIR,
    REVIEW_DIR,
    append_jsonl,
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_text,
    document_dir,
    ensure_document_dirs,
    write_jsonl,
)


def test_document_dir_paths(tmp_path: Path):
    d = document_dir(tmp_path, "abc123")
    assert d == tmp_path / "abc123"


def test_ensure_document_dirs_creates_layout(tmp_path: Path):
    d = tmp_path / "doc"
    ensure_document_dirs(d)
    assert (d / RAW_DIR).is_dir()
    assert (d / EVIDENCE_DIR).is_dir()
    assert (d / EVIDENCE_REGIONS_DIR).is_dir()
    assert (d / EVIDENCE_ELEMENTS_DIR).is_dir()
    assert (d / REVIEW_DIR).is_dir()


def test_atomic_write_text_round_trip(tmp_path: Path):
    p = tmp_path / "x.txt"
    atomic_write_text(p, "hello\nworld")
    assert p.read_text(encoding="utf-8") == "hello\nworld"


def test_atomic_write_bytes_round_trip(tmp_path: Path):
    p = tmp_path / "x.bin"
    atomic_write_bytes(p, b"\x00\x01\x02")
    assert p.read_bytes() == b"\x00\x01\x02"


def test_atomic_write_json_is_sorted(tmp_path: Path):
    p = tmp_path / "x.json"
    obj = {"b": 2, "a": 1, "nested": {"z": 0, "y": 1}}
    atomic_write_json(p, obj)
    text = p.read_text(encoding="utf-8")
    # keys sorted at each level
    assert text.index('"a"') < text.index('"b"')
    assert text.index('"y"') < text.index('"z"')
    # parses back equal
    assert json.loads(text) == obj


def test_append_jsonl(tmp_path: Path):
    p = tmp_path / "log.jsonl"
    append_jsonl(p, {"i": 1})
    append_jsonl(p, {"i": 2})
    lines = p.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["i"] == 1
    assert json.loads(lines[1])["i"] == 2


def test_write_jsonl_replaces_existing(tmp_path: Path):
    p = tmp_path / "log.jsonl"
    append_jsonl(p, {"old": True})
    write_jsonl(p, [{"new": 1}, {"new": 2}])
    lines = p.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    assert all("new" in ln for ln in lines)


def test_atomic_write_creates_parent_dirs(tmp_path: Path):
    p = tmp_path / "a" / "b" / "c.json"
    atomic_write_json(p, {"x": 1})
    assert p.is_file()
