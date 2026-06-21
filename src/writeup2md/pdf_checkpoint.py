"""Round 4 page-level checkpointing for full-book PDF conversion."""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import sqlite3
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .adapters.pdf import extract_pdf_page_blocks
from .completeness import check_completeness
from .config import WriteupConfig
from .models import (
    Block,
    BlockType,
    Document,
    DocumentStatus,
    Manifest,
    SourceRecord,
    SourceType,
    VisualBlockState,
    canonicalize_source,
    compute_document_id,
    content_sha256_bytes,
    now_iso_utc,
)
from .ocr.model_identity import PADDLEOCR_VL_REPO, PADDLEOCR_VL_REVISION
from .persist import finalize_document
from .performance import PerformanceRecorder
from .pipeline import ConversionResult
from .provenance import provenance_to_dicts
from .render import count_image_references, render_markdown
from .reconstruction import RECONSTRUCTION_DIAGNOSTICS_JSON, reconstruct_cross_page_blocks
from .slugify import human_readable_dir_name, update_index_file
from .workspace import atomic_write_json, atomic_write_text, ensure_document_dirs, write_jsonl


EXTRACTION_SCHEMA_VERSION = "pdf-page-shards-v1"
STATE_DIR = "state"
PAGES_DIR = "pages"
DOCUMENT_STATE_JSON = "document_state.json"
PAGE_STATE_SQLITE = "page_state.sqlite"
EVENTS_JSONL = "events.jsonl"
FULL_DOCUMENT_COMPLETENESS_JSON = "full_document_completeness.json"
FULL_DOCUMENT_COMPLETENESS_MD = "full_document_completeness.md"

PAGE_STATES = {
    "pending",
    "extracting",
    "native_extracted",
    "visuals_detected",
    "ocr_processing",
    "rendered",
    "verified",
    "failed",
}


class PdfCheckpointInterrupted(RuntimeError):
    """Raised after a controlled or OS interruption preserves page shards."""

    def __init__(self, document_dir: Path, resume_command: str) -> None:
        super().__init__(f"PDF conversion interrupted. Resume with: {resume_command}")
        self.document_dir = document_dir
        self.resume_command = resume_command


@dataclass
class PageProgress:
    pages_total: int
    verified: int
    processing: int
    pending: int
    failed: int
    last_completed_page: int | None


def convert_pdf_checkpointed(
    *,
    source: str,
    output_root: Path,
    config: WriteupConfig,
    force: bool = False,
    keep_evidence: bool = True,
    device: str | None = None,
    explicit_id: str | None = None,
    tags: list[str] | None = None,
    extra: dict[str, Any] | None = None,
    resume: bool = True,
    restart_failed: bool = False,
    stop_after_verified_pages: int | None = None,
) -> ConversionResult:
    """Convert an entire PDF using durable page shards.

    `stop_after_verified_pages` is a test-only hook for interruption harnesses.
    It is never wired to the public CLI as a production page limit.
    """
    try:
        import fitz  # type: ignore
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("pymupdf is required for PDF conversion") from e

    src_path = Path(source).expanduser().resolve()
    if not src_path.is_file():
        raise FileNotFoundError(f"PDF file not found: {source}")

    content_bytes = src_path.read_bytes()
    source_sha = content_sha256_bytes(content_bytes)
    canonical = canonicalize_source(str(src_path))
    shard_config_sha = _checkpoint_config_sha(config)
    config_sha = config.config_sha256()
    doc_id = compute_document_id(
        source=str(src_path),
        canonical_source=canonical,
        content_sha256=source_sha,
        config_sha256=config_sha,
        explicit_id=explicit_id,
    )
    dir_name = human_readable_dir_name(str(src_path), "pdf", source_sha)
    document_dir = output_root / dir_name
    update_index_file(output_root, dir_name, doc_id, str(src_path))

    if force and document_dir.exists():
        shutil.rmtree(document_dir)

    ensure_document_dirs(document_dir)
    state_dir = document_dir / STATE_DIR
    pages_dir = document_dir / PAGES_DIR
    state_dir.mkdir(parents=True, exist_ok=True)
    pages_dir.mkdir(parents=True, exist_ok=True)

    raw_source = document_dir / "raw" / "source.pdf"
    if force or not raw_source.exists():
        raw_source.write_bytes(content_bytes)

    pdf_doc = fitz.open(stream=content_bytes, filetype="pdf")
    interrupted = _InterruptionFlag()
    old_sigint = signal.getsignal(signal.SIGINT)
    old_sigterm = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGINT, interrupted.handler)
    signal.signal(signal.SIGTERM, interrupted.handler)

    captured = now_iso_utc()
    manifest_extra = dict(extra or {})
    manifest_extra.update(
        {
            "checkpointing": True,
            "extraction_schema": EXTRACTION_SCHEMA_VERSION,
            "pages_total": len(pdf_doc),
        }
    )
    manifest = Manifest(
        document_id=doc_id,
        source=str(src_path),
        source_type=SourceType.PDF,
        canonical_source=canonical,
        captured_at=captured,
        content_sha256=source_sha,
        config_sha256=config_sha,
        status=DocumentStatus.REVIEW,
        tags=tags or [],
        profile=config.pipeline.profile.value,
        extra=manifest_extra,
    )
    src_record = SourceRecord(
        source_type=SourceType.PDF,
        source=str(src_path),
        canonical_source=canonical,
        captured_at=captured,
        content_sha256=source_sha,
        extra={"content_bytes": len(content_bytes), "pages_total": len(pdf_doc)},
    )

    try:
        _init_sqlite(state_dir / PAGE_STATE_SQLITE)
        perf = PerformanceRecorder()
        doc_state = _load_or_initialize_document_state(
            document_dir=document_dir,
            manifest=manifest,
            source_sha=source_sha,
            shard_config_sha=shard_config_sha,
            pages_total=len(pdf_doc),
            force=force,
        )
        compatible = _state_is_compatible(
            doc_state,
            source_sha=source_sha,
            shard_config_sha=shard_config_sha,
        )
        if not compatible:
            _archive_incompatible_shards(document_dir)
            doc_state = _new_document_state(
                manifest=manifest,
                source_sha=source_sha,
                shard_config_sha=shard_config_sha,
                pages_total=len(pdf_doc),
            )
        _write_document_state(document_dir, doc_state)

        for page_index in range(len(pdf_doc)):
            page_number = page_index + 1
            if interrupted.interrupted:
                raise PdfCheckpointInterrupted(
                    document_dir, _resume_command(src_path, output_root)
                )
            page_dir = _page_dir(document_dir, page_number)
            if _page_verified_and_valid(
                page_dir=page_dir,
                page_number=page_number,
                source_sha=source_sha,
                shard_config_sha=shard_config_sha,
            ):
                _upsert_page_sqlite(
                    state_dir / PAGE_STATE_SQLITE,
                    _read_json(page_dir / "page_state.json"),
                )
                continue
            existing_state = _read_json(page_dir / "page_state.json") if page_dir.exists() else {}
            if existing_state.get("state") == "failed" and not restart_failed:
                _upsert_page_sqlite(state_dir / PAGE_STATE_SQLITE, existing_state)
                continue

            page_metrics = _process_one_page(
                pdf_doc=pdf_doc,
                page_index=page_index,
                document_dir=document_dir,
                config=config,
                manifest=manifest,
                source=src_record,
                source_sha=source_sha,
                shard_config_sha=shard_config_sha,
                canonical=canonical,
                keep_evidence=keep_evidence,
                force=force,
            )
            interval = max(1, int(getattr(config.runtime, "performance_interval_pages", 1)))
            if page_number == 1 or page_number == len(pdf_doc) or page_number % interval == 0:
                perf.record_page(
                    document_dir=document_dir,
                    current_page=page_number,
                    pages_total=len(pdf_doc),
                    active_page_buffers=1,
                    page_ocr_calls=page_metrics["ocr_calls"],
                    page_ocr_latency_s=page_metrics["ocr_latency_s"],
                    retries=page_metrics["retries"],
                )
            _append_event(
                document_dir,
                {
                    "event": "page_verified",
                    "page_number": page_number,
                    "at": now_iso_utc(),
                },
            )
            if (
                stop_after_verified_pages is not None
                and _progress_from_pages(document_dir, len(pdf_doc)).verified
                >= stop_after_verified_pages
            ):
                raise PdfCheckpointInterrupted(
                    document_dir, _resume_command(src_path, output_root)
                )

        progress = _progress_from_pages(document_dir, len(pdf_doc))
        doc_state.update(
            {
                "state": "compiling" if progress.failed == 0 else "incomplete",
                "updated_at": now_iso_utc(),
                "progress": progress.__dict__,
            }
        )
        _write_document_state(document_dir, doc_state)
        final_doc = compile_document_from_page_shards(
            document_dir=document_dir,
            manifest=manifest,
            source=src_record,
            config=config,
            force=force,
        )
        doc_state.update(
            {
                "state": "complete",
                "updated_at": now_iso_utc(),
                "status": final_doc.manifest.status.value,
                "progress": _progress_from_pages(document_dir, len(pdf_doc)).__dict__,
            }
        )
        _write_document_state(document_dir, doc_state)
        return ConversionResult(
            document_id=doc_id,
            document_dir=document_dir,
            status=final_doc.manifest.status,
            document=final_doc,
        )
    finally:
        try:
            pdf_doc.close()
        finally:
            signal.signal(signal.SIGINT, old_sigint)
            signal.signal(signal.SIGTERM, old_sigterm)


def compile_document_from_page_shards(
    *,
    document_dir: Path,
    manifest: Manifest,
    source: SourceRecord,
    config: WriteupConfig,
    force: bool = False,
) -> Document:
    """Rebuild final document artifacts from verified page shards only."""
    pages_total = int(manifest.extra.get("pages_total", 0)) if manifest.extra else 0
    blocks: list[Block] = []
    warnings: list[str] = []
    for page_number in range(1, pages_total + 1):
        pdir = _page_dir(document_dir, page_number)
        if not _page_verified_and_valid(
            page_dir=pdir,
            page_number=page_number,
            source_sha=manifest.content_sha256,
            shard_config_sha=_checkpoint_config_sha(config),
        ):
            warnings.append(f"page {page_number} is not verified; omitted from compile")
            continue
        page_doc = Document.model_validate(_read_json(pdir / "page.json"))
        for block in page_doc.blocks:
            blocks.append(_prefix_page_evidence(block, page_number))
    blocks, removed = reconstruct_cross_page_blocks(blocks, document_dir=document_dir)
    if removed:
        warnings.append(f"cross-page reconstruction removed {len(removed)} repeated header/footer blocks")

    doc = finalize_document(
        document_dir=document_dir,
        manifest=manifest,
        source=source,
        blocks=blocks,
        config=config,
        raw_assets=None,
        warnings=warnings,
        errors=[],
        force=force,
        enrich=False,
    )
    _write_full_document_completeness(document_dir, doc, pages_total)
    return doc


def read_pdf_checkpoint_status(document_dir: Path) -> PageProgress:
    state = _read_json(document_dir / STATE_DIR / DOCUMENT_STATE_JSON)
    pages_total = int(state.get("pages_total", 0))
    return _progress_from_pages(document_dir, pages_total)


def _process_one_page(
    *,
    pdf_doc,
    page_index: int,
    document_dir: Path,
    config: WriteupConfig,
    manifest: Manifest,
    source: SourceRecord,
    source_sha: str,
    shard_config_sha: str,
    canonical: str,
    keep_evidence: bool,
    force: bool,
) -> dict[str, Any]:
    page_number = page_index + 1
    final_page_dir = _page_dir(document_dir, page_number)
    tmp_page_dir = final_page_dir.parent / f".{final_page_dir.name}.tmp.{os.getpid()}"
    if tmp_page_dir.exists():
        shutil.rmtree(tmp_page_dir)
    ensure_document_dirs(tmp_page_dir)
    (tmp_page_dir / "evidence").mkdir(exist_ok=True)

    state = _base_page_state(
        page_number=page_number,
        source_page_index=page_index,
        source_sha=source_sha,
        shard_config_sha=shard_config_sha,
        state="extracting",
    )
    _write_page_state(tmp_page_dir, state)
    _upsert_page_sqlite(document_dir / STATE_DIR / PAGE_STATE_SQLITE, state)

    page = pdf_doc.load_page(page_index)
    try:
        blocks, warnings, _ = extract_pdf_page_blocks(
            page=page,
            page_index=page_index,
            document_dir=tmp_page_dir,
            config=config,
            canonical_source=canonical,
            start_order=page_index * 10000,
        )
    finally:
        page = None

    native_text_chars = sum(len(b.text or "") for b in blocks if b.type != BlockType.VISUAL)
    visual_count = sum(1 for b in blocks if b.type == BlockType.VISUAL)
    state.update(
        {
            "state": "visuals_detected" if visual_count else "native_extracted",
            "native_text_chars": native_text_chars,
            "visual_count": visual_count,
        }
    )
    _write_page_state(tmp_page_dir, state)
    _upsert_page_sqlite(document_dir / STATE_DIR / PAGE_STATE_SQLITE, state)

    state["state"] = "ocr_processing" if visual_count else "rendered"
    _write_page_state(tmp_page_dir, state)
    _upsert_page_sqlite(document_dir / STATE_DIR / PAGE_STATE_SQLITE, state)

    page_manifest = manifest.model_copy(
        update={
            "document_id": f"{manifest.document_id}-p{page_number:06d}",
            "extra": {
                **(manifest.extra or {}),
                "page_number": page_number,
                "source_page_index": page_index,
                "page_shard": True,
            },
        }
    )
    page_source = source.model_copy(
        update={
            "extra": {
                **(source.extra or {}),
                "page_number": page_number,
                "source_page_index": page_index,
            }
        }
    )
    unresolved_visuals = sum(
        1
        for b in blocks
        if b.type == BlockType.VISUAL
        and b.visual_state not in (
            VisualBlockState.RESOLVED_NATIVE,
            VisualBlockState.RESOLVED_OCR,
            VisualBlockState.RESOLVED_STRUCTURED,
            VisualBlockState.IGNORED_DECORATIVE,
        )
    )
    enrich_started = time.monotonic()
    page_doc = finalize_document(
        document_dir=tmp_page_dir,
        manifest=page_manifest,
        source=page_source,
        blocks=blocks,
        config=config,
        raw_assets=None,
        warnings=warnings,
        errors=[],
        force=force,
        keep_evidence=keep_evidence,
    )
    enrich_elapsed = time.monotonic() - enrich_started
    page_md = (tmp_page_dir / "document.md").read_text(encoding="utf-8")
    os.replace(tmp_page_dir / "document.md", tmp_page_dir / "page.md")
    os.replace(tmp_page_dir / "document.json", tmp_page_dir / "page.json")

    page_completeness = check_completeness(
        document=page_doc,
        markdown_text=page_md,
        markdown_path=tmp_page_dir / "page.md",
        mode=getattr(config.quality, "mode", "document") or "document",
    )
    atomic_write_json(tmp_page_dir / "completeness.json", page_completeness)
    write_jsonl(
        tmp_page_dir / "provenance.jsonl",
        provenance_to_dicts(page_doc.provenance),
    )
    state.update(
        {
            "state": "verified",
            "visuals_represented": _visuals_represented(page_doc.blocks),
            "page_markdown_sha256": content_sha256_bytes(page_md.encode("utf-8")),
            "completed_at": now_iso_utc(),
            "error": None,
        }
    )
    _write_page_state(tmp_page_dir, state)

    if final_page_dir.exists():
        shutil.rmtree(final_page_dir)
    os.replace(tmp_page_dir, final_page_dir)
    _upsert_page_sqlite(document_dir / STATE_DIR / PAGE_STATE_SQLITE, state)
    actual_ocr_calls = sum(1 for b in page_doc.blocks if b.enrichment is not None)
    return {
        "ocr_calls": actual_ocr_calls if actual_ocr_calls else unresolved_visuals,
        "ocr_latency_s": enrich_elapsed if unresolved_visuals else 0.0,
        "retries": 0,
    }


def _checkpoint_config_sha(config: WriteupConfig) -> str:
    data = config.model_dump(mode="json")
    # Worker count and resume policy should not invalidate extracted page content.
    data.get("pipeline", {}).pop("workers", None)
    data.get("pipeline", {}).pop("max_workers", None)
    data.get("pipeline", {}).pop("resume", None)
    text = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return content_sha256_bytes(text.encode("utf-8"))


def _new_document_state(
    *,
    manifest: Manifest,
    source_sha: str,
    shard_config_sha: str,
    pages_total: int,
) -> dict[str, Any]:
    return {
        "document_id": manifest.document_id,
        "source": manifest.source,
        "source_pdf_sha256": source_sha,
        "config_sha256": shard_config_sha,
        "model_repo": PADDLEOCR_VL_REPO,
        "model_revision": PADDLEOCR_VL_REVISION,
        "extraction_schema": EXTRACTION_SCHEMA_VERSION,
        "pages_total": pages_total,
        "state": "running",
        "created_at": now_iso_utc(),
        "updated_at": now_iso_utc(),
        "status": "unknown",
    }


def _load_or_initialize_document_state(
    *,
    document_dir: Path,
    manifest: Manifest,
    source_sha: str,
    shard_config_sha: str,
    pages_total: int,
    force: bool,
) -> dict[str, Any]:
    path = document_dir / STATE_DIR / DOCUMENT_STATE_JSON
    if path.is_file() and not force:
        return _read_json(path)
    return _new_document_state(
        manifest=manifest,
        source_sha=source_sha,
        shard_config_sha=shard_config_sha,
        pages_total=pages_total,
    )


def _state_is_compatible(
    state: dict[str, Any],
    *,
    source_sha: str,
    shard_config_sha: str,
) -> bool:
    return (
        state.get("source_pdf_sha256") == source_sha
        and state.get("config_sha256") == shard_config_sha
        and state.get("model_repo") == PADDLEOCR_VL_REPO
        and state.get("model_revision") == PADDLEOCR_VL_REVISION
        and state.get("extraction_schema") == EXTRACTION_SCHEMA_VERSION
    )


def _archive_incompatible_shards(document_dir: Path) -> None:
    ts = int(time.time())
    for name in (PAGES_DIR, STATE_DIR):
        p = document_dir / name
        if p.exists():
            p.rename(document_dir / f"{name}.invalid.{ts}")
    (document_dir / PAGES_DIR).mkdir(parents=True, exist_ok=True)
    (document_dir / STATE_DIR).mkdir(parents=True, exist_ok=True)
    _init_sqlite(document_dir / STATE_DIR / PAGE_STATE_SQLITE)


def _write_document_state(document_dir: Path, state: dict[str, Any]) -> None:
    atomic_write_json(document_dir / STATE_DIR / DOCUMENT_STATE_JSON, state)


def _base_page_state(
    *,
    page_number: int,
    source_page_index: int,
    source_sha: str,
    shard_config_sha: str,
    state: str,
) -> dict[str, Any]:
    return {
        "page_number": page_number,
        "source_page_index": source_page_index,
        "source_pdf_sha256": source_sha,
        "config_sha256": shard_config_sha,
        "model_repo": PADDLEOCR_VL_REPO,
        "model_revision": PADDLEOCR_VL_REVISION,
        "extraction_schema": EXTRACTION_SCHEMA_VERSION,
        "state": state,
        "native_text_chars": 0,
        "visual_count": 0,
        "visuals_represented": 0,
        "page_markdown_sha256": "",
        "started_at": now_iso_utc(),
        "completed_at": None,
        "error": None,
    }


def _write_page_state(page_dir: Path, state: dict[str, Any]) -> None:
    if state.get("state") not in PAGE_STATES:
        raise ValueError(f"unknown page state: {state.get('state')}")
    atomic_write_json(page_dir / "page_state.json", state)


def _page_verified_and_valid(
    *,
    page_dir: Path,
    page_number: int,
    source_sha: str,
    shard_config_sha: str,
) -> bool:
    required = ["page.json", "page.md", "completeness.json", "provenance.jsonl", "page_state.json"]
    if not page_dir.is_dir() or any(not (page_dir / name).is_file() for name in required):
        return False
    try:
        state = _read_json(page_dir / "page_state.json")
        if state.get("state") != "verified":
            return False
        if state.get("page_number") != page_number:
            return False
        if state.get("source_pdf_sha256") != source_sha:
            return False
        if state.get("config_sha256") != shard_config_sha:
            return False
        if state.get("model_revision") != PADDLEOCR_VL_REVISION:
            return False
        md = (page_dir / "page.md").read_bytes()
        return content_sha256_bytes(md) == state.get("page_markdown_sha256")
    except Exception:  # noqa: BLE001
        return False


def _visuals_represented(blocks: list[Block]) -> int:
    represented = 0
    for b in blocks:
        if b.type != BlockType.VISUAL:
            continue
        if b.visual_state is not None and b.visual_state != VisualBlockState.FAILED:
            represented += 1
    return represented


def _prefix_page_evidence(block: Block, page_number: int) -> Block:
    prefix = f"pages/{page_number:06d}/"
    evidence = []
    for ev in block.evidence:
        asset_path = ev.asset_path
        if asset_path and not asset_path.startswith(("pages/", "raw/")):
            asset_path = prefix + asset_path
        evidence.append(ev.model_copy(update={"asset_path": asset_path}))
    return block.model_copy(update={"evidence": evidence})


def _write_full_document_completeness(document_dir: Path, doc: Document, pages_total: int) -> None:
    page_records = []
    suspicious_pages = []
    for page_number in range(1, pages_total + 1):
        page_dir = _page_dir(document_dir, page_number)
        state = _read_json(page_dir / "page_state.json") if (page_dir / "page_state.json").is_file() else {}
        md = (page_dir / "page.md").read_text(encoding="utf-8") if (page_dir / "page.md").is_file() else ""
        page_doc = Document.model_validate(_read_json(page_dir / "page.json")) if (page_dir / "page.json").is_file() else None
        blocks = page_doc.blocks if page_doc else []
        visual_blocks = [b for b in blocks if b.type == BlockType.VISUAL]
        represented = _visuals_represented(blocks)
        warnings: list[str] = []
        native_chars = state.get("native_text_chars", 0)
        if state.get("native_text_chars", 0) > 500 and len(md.strip()) < 100:
            warnings.append("substantial native text but very short page markdown")
        if native_chars > 0 and not blocks:
            warnings.append("non-empty page source but no extracted blocks")
        if state.get("visual_count", 0) and represented == 0:
            warnings.append("visuals detected but no visual representation")
        if _looks_one_char_per_line(md):
            warnings.append("one character per line pattern")
        if _looks_extremely_duplicated(md):
            warnings.append("extreme duplicated content pattern")
        if _looks_like_only_furniture(md):
            warnings.append("page appears to contain only header/footer/page number")
        if _looks_chatty_visual_description(md):
            warnings.append("chatty visual description detected")
        if _looks_repeated_hallucinated_chars(md):
            warnings.append("repeated hallucinated character pattern")
        if _page_processing_seconds(state) > 300:
            warnings.append("abnormally high page processing time")
        if state.get("page_number") != page_number:
            warnings.append("page order mismatch")
        if warnings:
            suspicious_pages.append({"page_number": page_number, "warnings": warnings})
        page_records.append(
            {
                "page_number": page_number,
                "state": state.get("state", "missing"),
                "native_text_chars": state.get("native_text_chars", 0),
                "final_page_markdown_chars": len(md),
                "visuals_detected": len(visual_blocks),
                "visuals_represented": represented,
                "visuals_uncertain": sum(
                    1 for b in visual_blocks if b.visual_state == VisualBlockState.REVIEW_REQUIRED
                ),
                "visuals_missing": max(0, len(visual_blocks) - represented),
                "heading_count": sum(1 for b in blocks if b.type == BlockType.HEADING),
                "code_block_count": sum(1 for b in blocks if b.type == BlockType.NATIVE_CODE)
                + sum(1 for b in visual_blocks if b.visual_state in (VisualBlockState.RESOLVED_OCR, VisualBlockState.RESOLVED_STRUCTURED)),
                "warnings": warnings,
            }
        )
    final_md = (document_dir / "document.md").read_text(encoding="utf-8")
    reconstruction = _read_reconstruction_diagnostics(document_dir)
    pages_verified = sum(1 for r in page_records if r["state"] == "verified")
    pages_failed = sum(1 for r in page_records if r["state"] == "failed")
    page_sequence_gaps = sum(1 for r in page_records if r["state"] == "missing")
    visuals_total = sum(r["visuals_detected"] for r in page_records)
    visuals_represented = sum(r["visuals_represented"] for r in page_records)
    visuals_uncertain = sum(r["visuals_uncertain"] for r in page_records)
    visuals_missing = sum(r["visuals_missing"] for r in page_records)
    invariants = {
        "pages_total": pages_total,
        "pages_visited": len(page_records),
        "pages_verified": pages_verified,
        "pages_failed": pages_failed,
        "pages_suspicious": len(suspicious_pages),
        "page_sequence_gaps": page_sequence_gaps,
        "visuals_total": visuals_total,
        "visuals_represented": visuals_represented,
        "visuals_uncertain": visuals_uncertain,
        "visuals_missing": visuals_missing,
        "native_text_chars_total": sum(r["native_text_chars"] for r in page_records),
        "final_markdown_chars": len(final_md),
        "native_text_coverage_ratio": (
            len(final_md) / max(1, sum(r["native_text_chars"] for r in page_records))
        ),
        "markdown_image_count": count_image_references(final_md),
        "html_img_count": final_md.lower().count("<img"),
        "base64_image_count": final_md.lower().count("data:image/"),
        "unclosed_fence_count": _count_unclosed_fences(final_md),
        "paddleocr_vl_fallback_count": _count_fallbacks(doc),
        "furniture_removed_count": reconstruction.get("furniture_removed_count", 0),
        "cross_page_paragraph_merges": reconstruction.get("cross_page_paragraph_merges", 0),
        "cross_page_code_merges": reconstruction.get("cross_page_code_merges", 0),
        "unsafe_merge_candidates_skipped": reconstruction.get("unsafe_merge_candidates_skipped", 0),
    }
    hard_pass = (
        invariants["pages_visited"] == pages_total
        and invariants["pages_verified"] == pages_total
        and invariants["pages_failed"] == 0
        and invariants["page_sequence_gaps"] == 0
        and invariants["visuals_missing"] == 0
        and invariants["markdown_image_count"] == 0
        and invariants["html_img_count"] == 0
        and invariants["base64_image_count"] == 0
        and invariants["unclosed_fence_count"] == 0
        and invariants["paddleocr_vl_fallback_count"] == 0
    )
    payload = {
        **invariants,
        "passed": hard_pass,
        "pages": page_records,
        "suspicious_pages": suspicious_pages,
    }
    atomic_write_json(document_dir / FULL_DOCUMENT_COMPLETENESS_JSON, payload)
    lines = [
        "# Full Document Completeness",
        "",
        f"- pages_total: {pages_total}",
        f"- pages_verified: {pages_verified}",
        f"- pages_failed: {pages_failed}",
        f"- page_sequence_gaps: {page_sequence_gaps}",
        f"- visuals_total: {visuals_total}",
        f"- visuals_missing: {visuals_missing}",
        f"- furniture_removed_count: {invariants['furniture_removed_count']}",
        f"- cross_page_paragraph_merges: {invariants['cross_page_paragraph_merges']}",
        f"- cross_page_code_merges: {invariants['cross_page_code_merges']}",
        f"- unsafe_merge_candidates_skipped: {invariants['unsafe_merge_candidates_skipped']}",
        f"- passed: {hard_pass}",
    ]
    if suspicious_pages:
        lines.extend(["", "## Suspicious Pages"])
        for item in suspicious_pages:
            lines.append(f"- page {item['page_number']}: {', '.join(item['warnings'])}")
    unsafe = reconstruction.get("unsafe_merge_candidates", [])
    if unsafe:
        lines.extend(["", "## Unsafe Merge Candidates Skipped"])
        for item in unsafe[:50]:
            lines.append(
                "- pages "
                f"{item.get('previous_page')}->{item.get('next_page')} "
                f"blocks {item.get('previous_block_id')}->{item.get('next_block_id')}: "
                f"{item.get('reason')}"
            )
    atomic_write_text(document_dir / FULL_DOCUMENT_COMPLETENESS_MD, "\n".join(lines) + "\n")


def _read_reconstruction_diagnostics(document_dir: Path) -> dict[str, Any]:
    path = document_dir / RECONSTRUCTION_DIAGNOSTICS_JSON
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _count_unclosed_fences(markdown_text: str) -> int:
    in_code = False
    fence_len = 0
    for line in markdown_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("```"):
            continue
        tick_count = len(stripped) - len(stripped.lstrip("`"))
        if not in_code:
            in_code = True
            fence_len = tick_count
        elif stripped == "`" * tick_count and tick_count >= fence_len:
            in_code = False
            fence_len = 0
    return 1 if in_code else 0


def _count_fallbacks(doc: Document) -> int:
    count = 0
    for block in doc.blocks:
        if block.enrichment and block.enrichment.backend == "rapid":
            count += 1
    return count


def _looks_one_char_per_line(text: str) -> bool:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) < 20:
        return False
    short = sum(1 for ln in lines if len(ln) <= 2)
    return short / len(lines) > 0.8


def _looks_extremely_duplicated(text: str) -> bool:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) < 20:
        return False
    counts = Counter(lines)
    most_common = counts.most_common(1)[0][1]
    return most_common / len(lines) > 0.6


def _looks_like_only_furniture(text: str) -> bool:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines or len(lines) > 4:
        return False
    joined = " ".join(lines)
    return bool(re.fullmatch(r"(#+\s*)?[\w\s:'’-]{0,80}\s*(page\s*)?\d{0,4}", joined, re.IGNORECASE))


def _looks_chatty_visual_description(text: str) -> bool:
    lowered = text.lower()
    return any(
        phrase in lowered
        for phrase in (
            "the provided image",
            "does not contain any chart",
            "it is a graphic design",
            "cannot be converted into a table",
        )
    )


def _looks_repeated_hallucinated_chars(text: str) -> bool:
    compact = "".join(ch for ch in text if not ch.isspace())
    if len(compact) < 80:
        return False
    return bool(re.search(r"(.)\1{50,}", compact))


def _page_processing_seconds(state: dict[str, Any]) -> float:
    try:
        from datetime import datetime

        started = state.get("started_at")
        completed = state.get("completed_at")
        if not started or not completed:
            return 0.0
        a = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(completed).replace("Z", "+00:00"))
        return max(0.0, (b - a).total_seconds())
    except Exception:  # noqa: BLE001
        return 0.0


def _progress_from_pages(document_dir: Path, pages_total: int) -> PageProgress:
    verified = processing = pending = failed = 0
    last_completed: int | None = None
    for page_number in range(1, pages_total + 1):
        state_path = _page_dir(document_dir, page_number) / "page_state.json"
        state = _read_json(state_path) if state_path.is_file() else {"state": "pending"}
        st = state.get("state", "pending")
        if st == "verified":
            verified += 1
            last_completed = page_number
        elif st == "failed":
            failed += 1
        elif st in ("extracting", "native_extracted", "visuals_detected", "ocr_processing", "rendered"):
            processing += 1
        else:
            pending += 1
    return PageProgress(
        pages_total=pages_total,
        verified=verified,
        processing=processing,
        pending=pending,
        failed=failed,
        last_completed_page=last_completed,
    )


def _page_dir(document_dir: Path, page_number: int) -> Path:
    return document_dir / PAGES_DIR / f"{page_number:06d}"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _init_sqlite(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS page_state (
                page_number INTEGER PRIMARY KEY,
                state TEXT NOT NULL,
                source_page_index INTEGER NOT NULL,
                source_pdf_sha256 TEXT NOT NULL,
                config_sha256 TEXT NOT NULL,
                model_repo TEXT NOT NULL,
                model_revision TEXT NOT NULL,
                page_markdown_sha256 TEXT,
                started_at TEXT,
                completed_at TEXT,
                error TEXT,
                payload TEXT NOT NULL
            )
            """
        )


def _upsert_page_sqlite(path: Path, state: dict[str, Any]) -> None:
    if not state:
        return
    _init_sqlite(path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            INSERT INTO page_state (
                page_number, state, source_page_index, source_pdf_sha256,
                config_sha256, model_repo, model_revision,
                page_markdown_sha256, started_at, completed_at, error, payload
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(page_number) DO UPDATE SET
                state=excluded.state,
                source_page_index=excluded.source_page_index,
                source_pdf_sha256=excluded.source_pdf_sha256,
                config_sha256=excluded.config_sha256,
                model_repo=excluded.model_repo,
                model_revision=excluded.model_revision,
                page_markdown_sha256=excluded.page_markdown_sha256,
                started_at=excluded.started_at,
                completed_at=excluded.completed_at,
                error=excluded.error,
                payload=excluded.payload
            """,
            (
                state["page_number"],
                state["state"],
                state["source_page_index"],
                state["source_pdf_sha256"],
                state["config_sha256"],
                state["model_repo"],
                state["model_revision"],
                state.get("page_markdown_sha256"),
                state.get("started_at"),
                state.get("completed_at"),
                state.get("error"),
                json.dumps(state, sort_keys=True, ensure_ascii=False),
            ),
        )


def _append_event(document_dir: Path, record: dict[str, Any]) -> None:
    path = document_dir / STATE_DIR / EVENTS_JSONL
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
        f.flush()


def _resume_command(src_path: Path, output_root: Path) -> str:
    return f'writeup2md "{src_path}" --output "{output_root}" --resume'


class _InterruptionFlag:
    def __init__(self) -> None:
        self.interrupted = False

    def handler(self, signum, frame) -> None:  # noqa: ANN001
        self.interrupted = True
