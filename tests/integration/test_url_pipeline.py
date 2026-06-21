"""Integration test for local-HTML conversion end-to-end."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from writeup2md.adapters.html import convert_html
from writeup2md.config import Profile, build_config


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "html"


@pytest.fixture
def html_path() -> Path:
    return FIXTURE_DIR / "tutorial.html"


def test_convert_html_produces_full_document_layout(tmp_path: Path, html_path: Path):
    cfg = build_config(Profile.MACBOOK)
    result = convert_html(
        source=str(html_path),
        output_root=tmp_path,
        config=cfg,
        force=False,
        keep_evidence=True,
    )
    d = result.document_dir
    assert (d / "document.md").is_file()
    assert (d / "document.json").is_file()
    assert (d / "manifest.json").is_file()
    assert (d / "diagnostics.json").is_file()
    assert (d / "provenance.jsonl").is_file()
    assert (d / "raw").is_dir()
    assert (d / "evidence").is_dir()


def test_convert_html_markdown_has_no_images(tmp_path: Path, html_path: Path):
    cfg = build_config(Profile.MACBOOK)
    result = convert_html(
        source=str(html_path), output_root=tmp_path, config=cfg, keep_evidence=True
    )
    md = (result.document_dir / "document.md").read_text(encoding="utf-8")
    assert "![" not in md
    assert "<img" not in md
    assert "data:image/" not in md


def test_convert_html_markdown_contains_code_blocks(tmp_path: Path, html_path: Path):
    cfg = build_config(Profile.MACBOOK)
    result = convert_html(
        source=str(html_path), output_root=tmp_path, config=cfg, keep_evidence=True
    )
    md = (result.document_dir / "document.md").read_text(encoding="utf-8")
    assert "```python" in md
    assert "```bash" in md
    assert "```http" in md
    assert "import requests" in md


def test_convert_html_status_is_review_due_to_unresolved_image(tmp_path: Path, html_path: Path):
    cfg = build_config(Profile.MACBOOK)
    cfg.ocr.backend = "rapid"  # pin rapid to preserve pre-TASK_17 expectation
    result = convert_html(
        source=str(html_path), output_root=tmp_path, config=cfg, keep_evidence=True
    )
    # The tutorial.html contains one content image. Under the calibrated
    # threshold model on rapidocr (the pre-TASK_17 backend), the image
    # becomes a review_required visual block. Status should be review.
    # NOTE: PaddleOCR-VL (the TASK_15 production backend) transcribes
    # this image successfully, so under that backend the status is
    # `accepted`. This test pins rapidocr to preserve the original
    # assertion's premise.
    assert result.status.value == "review"


def test_convert_html_provenance_has_one_record_per_block(tmp_path: Path, html_path: Path):
    cfg = build_config(Profile.MACBOOK)
    result = convert_html(
        source=str(html_path), output_root=tmp_path, config=cfg, keep_evidence=True
    )
    provenance = (result.document_dir / "provenance.jsonl").read_text(
        encoding="utf-8"
    ).strip().split("\n")
    doc = json.loads((result.document_dir / "document.json").read_text(encoding="utf-8"))
    assert len(provenance) == len(doc["blocks"])
    for line in provenance:
        rec = json.loads(line)
        assert rec["block_id"]
        assert rec["source_kind"] == "html"


def test_convert_html_deterministic_id(tmp_path: Path, html_path: Path):
    cfg = build_config(Profile.MACBOOK)
    r1 = convert_html(source=str(html_path), output_root=tmp_path, config=cfg, keep_evidence=True)
    r2 = convert_html(source=str(html_path), output_root=tmp_path, config=cfg, keep_evidence=True)
    assert r1.document_id == r2.document_id


def test_convert_html_evidence_image_captured(tmp_path: Path, html_path: Path):
    cfg = build_config(Profile.MACBOOK)
    result = convert_html(
        source=str(html_path), output_root=tmp_path, config=cfg, keep_evidence=True
    )
    # The login_form.png fixture should be captured to evidence/elements/.
    elements_dir = result.document_dir / "evidence" / "elements"
    assert elements_dir.is_dir()
    files = list(elements_dir.iterdir())
    assert len(files) >= 1
    # evidence bytes must match the source fixture (immutable).
    src_bytes = (FIXTURE_DIR / "login_form.png").read_bytes()
    found = False
    for f in files:
        if f.read_bytes() == src_bytes:
            found = True
            break
    assert found


def test_convert_html_raw_html_preserved(tmp_path: Path, html_path: Path):
    cfg = build_config(Profile.MACBOOK)
    result = convert_html(
        source=str(html_path), output_root=tmp_path, config=cfg, keep_evidence=True
    )
    raw = (result.document_dir / "raw" / "page.html").read_text(encoding="utf-8")
    assert "SQL Injection 101" in raw
