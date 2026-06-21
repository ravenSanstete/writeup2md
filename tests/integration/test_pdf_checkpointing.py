from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from writeup2md.config import Profile, build_config
from writeup2md.models import Document, Manifest, SourceRecord
from writeup2md.pdf_checkpoint import (
    EXTRACTION_SCHEMA_VERSION,
    PAGES_DIR,
    STATE_DIR,
    PdfCheckpointInterrupted,
    compile_document_from_page_shards,
    convert_pdf_checkpointed,
    read_pdf_checkpoint_status,
)


FIXTURE_PDF = Path("tests/fixtures/pdf/writeup.pdf")


def _cfg():
    cfg = build_config(Profile.MACBOOK)
    cfg.ocr.backend = "mock"
    return cfg


def _doc_dir(root: Path) -> Path:
    dirs = [p for p in root.iterdir() if p.is_dir()]
    assert len(dirs) == 1
    return dirs[0]


def test_interruption_after_n_pages_preserves_verified_shards(tmp_path: Path) -> None:
    with pytest.raises(PdfCheckpointInterrupted):
        convert_pdf_checkpointed(
            source=str(FIXTURE_PDF),
            output_root=tmp_path,
            config=_cfg(),
            force=True,
            stop_after_verified_pages=1,
        )

    out = _doc_dir(tmp_path)
    progress = read_pdf_checkpoint_status(out)
    assert progress.pages_total == 2
    assert progress.verified == 1
    assert (out / PAGES_DIR / "000001" / "page.json").is_file()
    assert not (out / PAGES_DIR / "000002" / "page.json").exists()


def test_resume_skips_verified_pages_and_finishes(tmp_path: Path) -> None:
    with pytest.raises(PdfCheckpointInterrupted):
        convert_pdf_checkpointed(
            source=str(FIXTURE_PDF),
            output_root=tmp_path,
            config=_cfg(),
            force=True,
            stop_after_verified_pages=1,
        )
    out = _doc_dir(tmp_path)
    first_state = json.loads((out / PAGES_DIR / "000001" / "page_state.json").read_text())

    result = convert_pdf_checkpointed(
        source=str(FIXTURE_PDF),
        output_root=tmp_path,
        config=_cfg(),
        resume=True,
    )

    assert result.status.value == "accepted"
    progress = read_pdf_checkpoint_status(out)
    assert progress.verified == 2
    second_state = json.loads((out / PAGES_DIR / "000001" / "page_state.json").read_text())
    assert second_state["started_at"] == first_state["started_at"]


def test_failed_page_restart_reprocesses_only_when_requested(tmp_path: Path) -> None:
    convert_pdf_checkpointed(
        source=str(FIXTURE_PDF),
        output_root=tmp_path,
        config=_cfg(),
        force=True,
    )
    out = _doc_dir(tmp_path)
    page2 = out / PAGES_DIR / "000002"
    state = json.loads((page2 / "page_state.json").read_text())
    state["state"] = "failed"
    (page2 / "page_state.json").write_text(json.dumps(state), encoding="utf-8")

    convert_pdf_checkpointed(source=str(FIXTURE_PDF), output_root=tmp_path, config=_cfg())
    assert json.loads((page2 / "page_state.json").read_text())["state"] == "failed"

    convert_pdf_checkpointed(
        source=str(FIXTURE_PDF),
        output_root=tmp_path,
        config=_cfg(),
        restart_failed=True,
    )
    assert json.loads((page2 / "page_state.json").read_text())["state"] == "verified"


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_pdf_sha256", "bad-source"),
        ("model_revision", "bad-revision"),
        ("extraction_schema", "bad-schema"),
    ],
)
def test_incompatible_document_state_invalidates_shards(
    tmp_path: Path, field: str, value: str
) -> None:
    convert_pdf_checkpointed(
        source=str(FIXTURE_PDF),
        output_root=tmp_path,
        config=_cfg(),
        force=True,
    )
    out = _doc_dir(tmp_path)
    state_path = out / STATE_DIR / "document_state.json"
    state = json.loads(state_path.read_text())
    state[field] = value
    state_path.write_text(json.dumps(state), encoding="utf-8")

    convert_pdf_checkpointed(source=str(FIXTURE_PDF), output_root=tmp_path, config=_cfg())

    assert any(p.name.startswith("pages.invalid.") for p in out.iterdir())
    new_state = json.loads((out / STATE_DIR / "document_state.json").read_text())
    assert new_state["extraction_schema"] == EXTRACTION_SCHEMA_VERSION
    assert read_pdf_checkpoint_status(out).verified == 2


def test_worker_count_change_does_not_invalidate_content(tmp_path: Path) -> None:
    cfg = _cfg()
    convert_pdf_checkpointed(source=str(FIXTURE_PDF), output_root=tmp_path, config=cfg, force=True)
    out = _doc_dir(tmp_path)
    first_state = json.loads((out / PAGES_DIR / "000001" / "page_state.json").read_text())

    cfg2 = _cfg()
    cfg2.pipeline.workers = 2
    convert_pdf_checkpointed(source=str(FIXTURE_PDF), output_root=tmp_path, config=cfg2)

    second_state = json.loads((out / PAGES_DIR / "000001" / "page_state.json").read_text())
    assert second_state["started_at"] == first_state["started_at"]
    assert not any(p.name.startswith("pages.invalid.") for p in out.iterdir())


def test_final_compilation_from_existing_page_shards(tmp_path: Path) -> None:
    convert_pdf_checkpointed(source=str(FIXTURE_PDF), output_root=tmp_path, config=_cfg(), force=True)
    out = _doc_dir(tmp_path)
    manifest = Manifest.model_validate(json.loads((out / "manifest.json").read_text()))
    source = SourceRecord.model_validate(
        json.loads((out / "document.json").read_text())["source"]
    )
    (out / "document.md").unlink()

    doc = compile_document_from_page_shards(
        document_dir=out,
        manifest=manifest,
        source=source,
        config=_cfg(),
    )

    assert isinstance(doc, Document)
    assert (out / "document.md").is_file()
    assert "SQL Injection 101" in (out / "document.md").read_text()


def test_atomic_page_state_updates_sqlite_after_artifacts_exist(tmp_path: Path) -> None:
    convert_pdf_checkpointed(source=str(FIXTURE_PDF), output_root=tmp_path, config=_cfg(), force=True)
    out = _doc_dir(tmp_path)
    page1 = out / PAGES_DIR / "000001"
    state = json.loads((page1 / "page_state.json").read_text())
    assert state["state"] == "verified"
    for name in ("page.json", "page.md", "completeness.json", "provenance.jsonl"):
        assert (page1 / name).is_file()
    with sqlite3.connect(out / STATE_DIR / "page_state.sqlite") as conn:
        row = conn.execute("SELECT state FROM page_state WHERE page_number = 1").fetchone()
    assert row == ("verified",)


def test_corrupt_page_shard_is_rebuilt_on_resume(tmp_path: Path) -> None:
    convert_pdf_checkpointed(source=str(FIXTURE_PDF), output_root=tmp_path, config=_cfg(), force=True)
    out = _doc_dir(tmp_path)
    page1_md = out / PAGES_DIR / "000001" / "page.md"
    page1_md.write_text("corrupt", encoding="utf-8")

    convert_pdf_checkpointed(source=str(FIXTURE_PDF), output_root=tmp_path, config=_cfg())

    assert "corrupt" not in page1_md.read_text(encoding="utf-8")
