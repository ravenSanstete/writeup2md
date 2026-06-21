"""`writeup2md inspect` implementation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class InspectInfo:
    document_id: str
    source: str
    source_type: str
    status: str
    quality_score: float
    block_count: int
    unresolved_visuals: int
    markdown_images: int
    artifacts: dict[str, Path]


def inspect_document(result_dir: Path | str) -> InspectInfo:
    d = Path(result_dir)
    manifest_path = d / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"no manifest.json in {d}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    diagnostics_path = d / "diagnostics.json"
    diagnostics = (
        json.loads(diagnostics_path.read_text(encoding="utf-8"))
        if diagnostics_path.is_file()
        else {}
    )
    document_json_path = d / "document.json"
    blocks: list = []
    if document_json_path.is_file():
        doc = json.loads(document_json_path.read_text(encoding="utf-8"))
        blocks = doc.get("blocks", [])

    md_path = d / "document.md"
    md_text = md_path.read_text(encoding="utf-8") if md_path.is_file() else ""
    md_images = md_text.count("![") + md_text.count("<img")

    quality = diagnostics.get("quality", {}) if isinstance(diagnostics, dict) else {}
    artifacts = {
        name: d / fname
        for name, fname in {
            "manifest": "manifest.json",
            "document_md": "document.md",
            "document_json": "document.json",
            "diagnostics": "diagnostics.json",
            "provenance": "provenance.jsonl",
        }.items()
        if (d / fname).exists()
    }

    return InspectInfo(
        document_id=manifest.get("document_id", d.name),
        source=manifest.get("source", ""),
        source_type=manifest.get("source_type", ""),
        status=manifest.get("status", ""),
        quality_score=float(quality.get("overall_quality_score", 0.0) or 0.0),
        block_count=len(blocks),
        unresolved_visuals=len(diagnostics.get("unresolved_important_visuals", []) or []),
        markdown_images=md_images,
        artifacts=artifacts,
    )


def export_reviews(result_dir: Path | str, output_path: Path | str) -> int:
    """Export human revisions from a document directory to a JSONL file.

    Returns the number of records written. TASK_13.
    """
    from .ui.review_store import export_reviews_jsonl

    d = Path(result_dir)
    if not (d / "manifest.json").is_file():
        raise FileNotFoundError(f"no manifest.json in {d}")
    return export_reviews_jsonl(d, output_path)
