"""Integration tests for the PDF adapter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from writeup2md.adapters.pdf import convert_pdf
from writeup2md.config import Profile, build_config


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "pdf"


@pytest.fixture
def pdf_path() -> Path:
    p = FIXTURE_DIR / "writeup.pdf"
    if not p.is_file():
        pytest.skip("PDF fixture not available")
    return p


def test_convert_pdf_produces_full_layout(tmp_path: Path, pdf_path: Path):
    cfg = build_config(Profile.MACBOOK)
    result = convert_pdf(source=str(pdf_path), output_root=tmp_path, config=cfg, keep_evidence=True)
    d = result.document_dir
    assert (d / "document.md").is_file()
    assert (d / "document.json").is_file()
    assert (d / "manifest.json").is_file()
    assert (d / "diagnostics.json").is_file()
    assert (d / "provenance.jsonl").is_file()
    assert (d / "raw" / "source.pdf").is_file()


def test_convert_pdf_raw_source_immutable(tmp_path: Path, pdf_path: Path):
    cfg = build_config(Profile.MACBOOK)
    result = convert_pdf(source=str(pdf_path), output_root=tmp_path, config=cfg, keep_evidence=True)
    raw_bytes = (result.document_dir / "raw" / "source.pdf").read_bytes()
    src_bytes = pdf_path.read_bytes()
    assert raw_bytes == src_bytes


def test_convert_pdf_markdown_has_no_images(tmp_path: Path, pdf_path: Path):
    cfg = build_config(Profile.MACBOOK)
    result = convert_pdf(source=str(pdf_path), output_root=tmp_path, config=cfg, keep_evidence=True)
    md = (result.document_dir / "document.md").read_text(encoding="utf-8")
    assert "![" not in md
    assert "<img" not in md
    assert "data:image/" not in md


def test_convert_pdf_native_text_extracted(tmp_path: Path, pdf_path: Path):
    cfg = build_config(Profile.MACBOOK)
    result = convert_pdf(source=str(pdf_path), output_root=tmp_path, config=cfg, keep_evidence=True)
    md = (result.document_dir / "document.md").read_text(encoding="utf-8")
    assert "SQL Injection 101" in md
    assert "Reconnaissance" in md
    assert "import requests" in md


def test_convert_pdf_provenance_per_block(tmp_path: Path, pdf_path: Path):
    cfg = build_config(Profile.MACBOOK)
    result = convert_pdf(source=str(pdf_path), output_root=tmp_path, config=cfg, keep_evidence=True)
    provenance = (result.document_dir / "provenance.jsonl").read_text(encoding="utf-8").strip().split("\n")
    doc = json.loads((result.document_dir / "document.json").read_text(encoding="utf-8"))
    assert len(provenance) == len(doc["blocks"])
    for line in provenance:
        rec = json.loads(line)
        assert rec["source_kind"] == "pdf"


def test_convert_pdf_deterministic_id(tmp_path: Path, pdf_path: Path):
    cfg = build_config(Profile.MACBOOK)
    r1 = convert_pdf(source=str(pdf_path), output_root=tmp_path, config=cfg, keep_evidence=True)
    r2 = convert_pdf(source=str(pdf_path), output_root=tmp_path, config=cfg, keep_evidence=True)
    assert r1.document_id == r2.document_id


def test_convert_pdf_page_provenance_in_blocks(tmp_path: Path, pdf_path: Path):
    cfg = build_config(Profile.MACBOOK)
    result = convert_pdf(source=str(pdf_path), output_root=tmp_path, config=cfg, keep_evidence=True)
    doc = json.loads((result.document_dir / "document.json").read_text(encoding="utf-8"))
    # Every block has at least one evidence record with page >= 0
    for b in doc["blocks"]:
        if b["type"] == "horizontal_rule":
            continue
        # text-bearing blocks should have evidence with page index
        text_evs = [e for e in b.get("evidence", []) if e.get("kind") == "pdf_region"]
        if text_evs:
            assert all(isinstance(e.get("page"), int) for e in text_evs)


def test_convert_pdf_scanned_page_detection(tmp_path: Path):
    """A page with essentially no native text should be flagged as scanned."""
    import fitz

    pdf_path = tmp_path / "scanned.pdf"
    doc = fitz.open()
    page = doc.new_page()
    # Render nothing meaningful: just a near-empty page.
    page.insert_text((72, 72), " ", fontsize=10)
    doc.save(str(pdf_path))
    doc.close()

    from writeup2md.adapters.pdf import convert_pdf

    cfg = build_config(Profile.MACBOOK)
    # TASK_15: pin rapid so this scanned-page-detection test does not
    # depend on which OCR backend is installed.
    cfg.ocr.backend = "rapid"
    result = convert_pdf(source=str(pdf_path), output_root=tmp_path / "out", config=cfg, keep_evidence=True)
    diag = json.loads((result.document_dir / "diagnostics.json").read_text(encoding="utf-8"))
    assert any("scanned" in w for w in diag.get("processing_warnings", []))


def test_convert_pdf_code_block_detected_as_native_code(tmp_path: Path, pdf_path: Path):
    cfg = build_config(Profile.MACBOOK)
    result = convert_pdf(source=str(pdf_path), output_root=tmp_path, config=cfg, keep_evidence=True)
    doc = json.loads((result.document_dir / "document.json").read_text(encoding="utf-8"))
    code_blocks = [b for b in doc["blocks"] if b["type"] == "native_code"]
    assert len(code_blocks) >= 1
    joined = "\n".join(b.get("text", "") for b in code_blocks)
    assert "import requests" in joined or "$ curl" in joined
