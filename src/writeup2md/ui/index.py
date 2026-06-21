"""Compact document index for the Streamlit UI.

The index is a single list of small dicts, one per document, holding only
the fields needed for the dashboard and search. It is built once and cached
via `@st.cache_data` keyed by directory modification time, so manual
corrections invalidate only the affected views.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class DocumentIndexEntry:
    document_id: str
    source: str
    source_type: str
    canonical_source: str
    status: str
    captured_at: str
    quality_score: float
    block_count: int
    unresolved_visuals: int
    markdown_images: int
    document_dir: str
    title: str


def _dir_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _extract_title(document_dir: Path) -> str:
    md_path = document_dir / "document.md"
    if md_path.is_file():
        try:
            text = md_path.read_text(encoding="utf-8")
            for line in text.splitlines():
                s = line.strip()
                if s.startswith("# "):
                    return s[2:].strip()[:200]
                if s and not s.startswith("```"):
                    return s[:200]
        except Exception:  # noqa: BLE001
            pass
    return document_dir.name


def build_index(result_root: Path) -> list[DocumentIndexEntry]:
    """Build a compact index of all documents in `result_root`.

    Skips the batch-state files and status subdirectories. Only top-level
    directories that contain a `manifest.json` are considered documents.
    """
    entries: list[DocumentIndexEntry] = []
    if not result_root.is_dir():
        return entries
    for child in sorted(result_root.iterdir()):
        if not child.is_dir():
            continue
        if child.name in {"accepted", "review", "rejected", "failed"}:
            continue
        manifest_path = child / "manifest.json"
        if not manifest_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        diagnostics = {}
        diag_path = child / "diagnostics.json"
        if diag_path.is_file():
            try:
                diagnostics = json.loads(diag_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                pass
        document_json = {}
        doc_path = child / "document.json"
        if doc_path.is_file():
            try:
                document_json = json.loads(doc_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                pass
        quality = diagnostics.get("quality", {}) if isinstance(diagnostics, dict) else {}
        entries.append(
            DocumentIndexEntry(
                document_id=manifest.get("document_id", child.name),
                source=manifest.get("source", ""),
                source_type=manifest.get("source_type", ""),
                canonical_source=manifest.get("canonical_source", ""),
                status=manifest.get("status", ""),
                captured_at=manifest.get("captured_at", ""),
                quality_score=float(quality.get("overall_quality_score", 0.0) or 0.0),
                block_count=len(document_json.get("blocks", []) if isinstance(document_json, dict) else []),
                unresolved_visuals=len(
                    diagnostics.get("unresolved_important_visuals", []) or []
                ) if isinstance(diagnostics, dict) else 0,
                markdown_images=diagnostics.get("markdown_image_count", 0) if isinstance(diagnostics, dict) else 0,
                document_dir=str(child),
                title=_extract_title(child),
            )
        )
    return entries


def index_signature(result_root: Path) -> tuple:
    """Return a cache signature keyed on directory mtimes.

    We sample the result root's mtime plus the mtime of each top-level
    document directory. This is cheap (one stat per document) and invalidates
    the cache when documents are added/removed or their contents change.
    """
    if not result_root.is_dir():
        return (str(result_root), 0.0)
    sigs: list = [str(result_root), _dir_mtime(result_root)]
    for child in sorted(result_root.iterdir()):
        if child.is_dir() and child.name not in {"accepted", "review", "rejected", "failed"}:
            sigs.append((child.name, _dir_mtime(child)))
    return tuple(sigs)
