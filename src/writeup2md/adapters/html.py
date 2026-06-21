"""Local HTML adapter — parses files directly without Playwright."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import WriteupConfig
from ..dom_extract import extract_blocks_from_html, write_asset
from ..models import (
    Document,
    DocumentStatus,
    EvidenceKind,
    EvidenceRef,
    Manifest,
    SourceRecord,
    SourceType,
    VisualBlockState,
    VisualType,
    canonicalize_source,
    compute_document_id,
    content_sha256_bytes,
    content_sha256_text,
    next_block_id,
    now_iso_utc,
)
from ..persist import finalize_document
from ..pipeline import ConversionResult


def convert_html(
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
) -> ConversionResult:
    """Convert a local HTML file to a document directory."""
    src_path = Path(source).expanduser().resolve()
    if not src_path.is_file():
        raise FileNotFoundError(f"HTML file not found: {source}")
    content_bytes = src_path.read_bytes()
    html = content_bytes.decode("utf-8", errors="replace")

    canonical = canonicalize_source(str(src_path))
    content_sha = content_sha256_bytes(content_bytes)
    config_sha = config.config_sha256()
    doc_id = compute_document_id(
        source=str(src_path),
        canonical_source=canonical,
        content_sha256=content_sha,
        config_sha256=config_sha,
        explicit_id=explicit_id,
    )
    captured = now_iso_utc()
    manifest = Manifest(
        document_id=doc_id,
        source=str(src_path),
        source_type=SourceType.HTML,
        canonical_source=canonical,
        captured_at=captured,
        content_sha256=content_sha,
        config_sha256=config_sha,
        status=DocumentStatus.REVIEW,
        tags=tags or [],
        profile=config.pipeline.profile.value,
        extra=extra or {},
    )
    src_record = SourceRecord(
        source_type=SourceType.HTML,
        source=str(src_path),
        canonical_source=canonical,
        captured_at=captured,
        content_sha256=content_sha,
        extra={"content_bytes": len(content_bytes)},
    )

    # TASK_20: human-readable directory name (<slug>-<short_hash>).
    from ..slugify import human_readable_dir_name, update_index_file

    dir_name = human_readable_dir_name(str(src_path), "html", content_sha)
    document_dir = output_root / dir_name
    update_index_file(output_root, dir_name, doc_id, str(src_path))

    # Image handler: only handles file:// and absolute local paths.
    def _image_handler(img):
        from ..dom_extract import DomImage  # local import for clarity

        if not img.src:
            return None
        # For local HTML, try to resolve relative paths against the source directory.
        candidate: Path | None = None
        if img.src.startswith(("http://", "https://")):
            return None  # remote images require a network fetch; skip in offline mode
        if img.src.startswith("file://"):
            candidate = Path(img.src[len("file://"):])
        else:
            candidate = (src_path.parent / img.src).resolve()
        if candidate and candidate.is_file():
            data = candidate.read_bytes()
            ext = candidate.suffix.lower() or ".png"
            return write_asset(document_dir, "elements", data, ext=ext)
        return None

    blocks, _images = extract_blocks_from_html(
        html=html,
        source_kind="html",
        source_ref=str(src_path),
        canonical_source=canonical,
        image_handler=_image_handler,
    )

    doc = finalize_document(
        document_dir=document_dir,
        manifest=manifest,
        source=src_record,
        blocks=blocks,
        config=config,
        raw_assets={"page.html": content_bytes, "source.html": content_bytes},
        warnings=[],
        errors=[],
        force=force,
        keep_evidence=keep_evidence,
    )
    return ConversionResult(
        document_id=doc_id,
        document_dir=document_dir,
        status=doc.manifest.status,
        document=doc,
    )
