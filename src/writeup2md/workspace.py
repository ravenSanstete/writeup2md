"""Workspace layout and atomic file writing for writeup2md."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .models import SCHEMA_VERSION


# Subdirectory names inside a document directory.
RAW_DIR = "raw"
EVIDENCE_DIR = "evidence"
EVIDENCE_REGIONS_DIR = "evidence/regions"
EVIDENCE_ELEMENTS_DIR = "evidence/elements"
REVIEW_DIR = "review"

# File names.
DOCUMENT_MD = "document.md"
DOCUMENT_JSON = "document.json"
MANIFEST_JSON = "manifest.json"
DIAGNOSTICS_JSON = "diagnostics.json"
PROVENANCE_JSONL = "provenance.jsonl"

# Review artifacts.
REVISIONS_JSONL = "revisions.jsonl"
REVIEW_STATE_JSON = "review_state.json"
DOCUMENT_REVIEWED_MD = "document.reviewed.md"


def document_dir(root: Path | str, document_id: str) -> Path:
    """Return the output directory for a document id."""
    return Path(root) / document_id


def ensure_document_dirs(out_dir: Path) -> None:
    """Create the canonical document directory layout."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / RAW_DIR).mkdir(exist_ok=True)
    (out_dir / EVIDENCE_DIR).mkdir(exist_ok=True)
    (out_dir / EVIDENCE_REGIONS_DIR).mkdir(parents=True, exist_ok=True)
    (out_dir / EVIDENCE_ELEMENTS_DIR).mkdir(parents=True, exist_ok=True)
    (out_dir / REVIEW_DIR).mkdir(exist_ok=True)


def atomic_write_bytes(path: Path | str, data: bytes) -> None:
    """Write bytes atomically: temp file, fsync, rename."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=p.name + ".", dir=str(p.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_text(path: Path | str, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def atomic_write_json(path: Path | str, obj: object) -> None:
    """Write JSON atomically with stable, deterministic formatting."""
    text = json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    atomic_write_text(path, text)


def append_jsonl(path: Path | str, record: dict) -> None:
    """Append one record to a JSONL file."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n"
    with p.open("a", encoding="utf-8") as f:
        f.write(line)
        f.flush()


def write_jsonl(path: Path | str, records: list[dict]) -> None:
    """Write all records to a JSONL file, replacing existing content."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in records)
    atomic_write_text(p, text)


def write_provenance(path: Path | str, records: list[dict]) -> None:
    write_jsonl(path, records)


def schema_version() -> str:
    return SCHEMA_VERSION
