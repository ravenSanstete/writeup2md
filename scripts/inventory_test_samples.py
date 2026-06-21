#!/usr/bin/env python3
"""Build a test_samples inventory.

Walks `test_samples/`, classifies every file, and writes:
- reports/TEST_SAMPLES_INVENTORY.json
- reports/TEST_SAMPLES_INVENTORY.md
- reports/TEST_SAMPLES_MANIFEST.jsonl

Treats test_samples/ as immutable — never writes inside it.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = ROOT / "test_samples"
REPORTS_DIR = ROOT / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

SUPPORTED_PDF = ".pdf"
SUPPORTED_HTML = (".html", ".htm")
URL_TXT_EXT = ".txt"
MANIFEST_EXT = (".jsonl", ".json")
IMAGE_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".tif", ".tiff",
    ".bmp", ".svg",
}


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pdf_page_count(p: Path) -> int | None:
    try:
        import fitz  # type: ignore
        d = fitz.open(str(p))
        n = len(d)
        d.close()
        return n
    except Exception:
        return None


def looks_like_url_list(p: Path) -> bool:
    try:
        with p.open("r", encoding="utf-8", errors="ignore") as f:
            head = [next(f, "") for _ in range(20)]
    except Exception:
        return False
    url_lines = [ln.strip() for ln in head if ln.strip().startswith(("http://", "https://"))]
    return len(url_lines) >= 2


def looks_like_manifest(p: Path, ext: str) -> bool:
    if ext == ".jsonl":
        try:
            with p.open("r", encoding="utf-8", errors="ignore") as f:
                first = next(f, "").strip()
            json.loads(first)
            return True
        except Exception:
            return False
    if ext == ".json":
        try:
            with p.open("r", encoding="utf-8", errors="ignore") as f:
                data = json.load(f)
            return isinstance(data, (dict, list))
        except Exception:
            return False
    return False


def classify(p: Path) -> tuple[str, dict[str, Any]]:
    ext = p.suffix.lower()
    if ext == SUPPORTED_PDF:
        n_pages = pdf_page_count(p)
        return "pdf", {"page_count": n_pages}
    if ext in SUPPORTED_HTML:
        return "html", {"page_count": None}
    if ext in MANIFEST_EXT and looks_like_manifest(p, ext):
        return "manifest", {"page_count": None}
    if ext == URL_TXT_EXT and looks_like_url_list(p):
        return "manifest", {"page_count": None, "manifest_kind": "url_list"}
    if ext in IMAGE_EXT:
        return "unsupported", {"page_count": None, "reason": "standalone image file"}
    if ext in (".md",):
        return "unsupported", {"page_count": None, "reason": "markdown artifact"}
    return "unsupported", {"page_count": None, "reason": f"unknown extension {ext}"}


def make_sample_id(idx: int, p: Path) -> str:
    base = p.stem.lower()
    # Slugify
    keep = []
    for ch in base:
        if ch.isalnum() or ch in "-_":
            keep.append(ch)
        elif ch in " .，（）":
            keep.append("-")
    slug = "".join(keep)
    while "--" in slug:
        slug = slug.replace("--", "-")
    slug = slug.strip("-")
    if not slug:
        slug = f"sample-{idx}"
    return f"{idx:02d}-{slug[:50]}"


def main() -> int:
    if not SAMPLES_DIR.is_dir():
        print(f"ERROR: {SAMPLES_DIR} not found", file=sys.stderr)
        return 1

    samples: list[dict[str, Any]] = []
    all_files = sorted([p for p in SAMPLES_DIR.rglob("*") if p.is_file()])
    for idx, p in enumerate(all_files, start=1):
        rel = str(p.relative_to(ROOT))
        stype, extra = classify(p)
        sha = sha256_file(p)
        size = p.stat().st_size
        sample_id = make_sample_id(idx, p)
        notes_parts: list[str] = []
        if stype == "unsupported":
            notes_parts.append(extra.get("reason", "unsupported"))
        if stype == "pdf" and extra.get("page_count") is None:
            notes_parts.append("could not read page count")
        record = {
            "sample_id": sample_id,
            "source": p.name,
            "source_type": stype,
            "path": rel,
            "sha256": sha,
            "size_bytes": size,
            "page_count": extra.get("page_count"),
            "asset_directory": None,
            "expected_processing": stype in ("pdf", "html", "url", "manifest"),
            "notes": "; ".join(notes_parts),
        }
        samples.append(record)

    # Aggregate summary
    by_type: dict[str, int] = {}
    for s in samples:
        by_type[s["source_type"]] = by_type.get(s["source_type"], 0) + 1
    total_pages = sum(s["page_count"] or 0 for s in samples if s["source_type"] == "pdf")

    summary = {
        "root": str(SAMPLES_DIR.relative_to(ROOT)),
        "total_files": len(samples),
        "by_type": by_type,
        "total_pdf_pages": total_pages,
        "processable_count": sum(1 for s in samples if s["expected_processing"]),
        "unsupported_count": sum(1 for s in samples if not s["expected_processing"]),
    }
    payload = {"summary": summary, "samples": samples}

    (REPORTS_DIR / "TEST_SAMPLES_INVENTORY.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    with (REPORTS_DIR / "TEST_SAMPLES_MANIFEST.jsonl").open("w", encoding="utf-8") as f:
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")

    # Markdown
    md_lines = [
        "# Test Samples Inventory",
        "",
        f"Root: `{summary['root']}`",
        f"Total files: **{summary['total_files']}**",
        f"Processable: **{summary['processable_count']}**  Unsupported: **{summary['unsupported_count']}**",
        f"Total PDF pages across all PDFs: **{summary['total_pdf_pages']}**",
        "",
        "## By type",
        "",
        "| Source type | Count |",
        "| --- | ---: |",
    ]
    for t, n in sorted(by_type.items()):
        md_lines.append(f"| {t} | {n} |")
    md_lines += ["", "## Samples", "", "| sample_id | type | size | pages | source |", "| --- | --- | ---: | ---: | --- |"]
    for s in samples:
        pages = s["page_count"] if s["page_count"] is not None else "-"
        md_lines.append(
            f"| {s['sample_id']} | {s['source_type']} | {s['size_bytes']:,} | {pages} | {s['source'][:80]} |"
        )
    (REPORTS_DIR / "TEST_SAMPLES_INVENTORY.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    print(f"inventory: {len(samples)} samples ({summary['total_pdf_pages']} PDF pages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
