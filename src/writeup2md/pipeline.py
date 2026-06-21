"""High-level conversion pipeline for single-source conversion.

This module is the orchestrator. It detects the source type, calls the
appropriate adapter, builds the unified IR, optionally enriches visuals via
OCR, runs quality gates, and writes the document directory.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import WriteupConfig
from .models import Document, DocumentStatus


@dataclass
class ConversionResult:
    document_id: str
    document_dir: Path
    status: DocumentStatus
    document: Document


def detect_source_type(source: str) -> str:
    """Detect 'url', 'pdf', or 'html' from a source string."""
    s = source.strip()
    if s.startswith(("http://", "https://")):
        return "url"
    if s.startswith("file://"):
        # Treat file:// URLs uniformly as URL-type sources so Playwright handles them.
        return "url"
    p = Path(s)
    if p.is_file():
        suffix = p.suffix.lower()
        if suffix == ".pdf":
            return "pdf"
        if suffix in (".html", ".htm"):
            return "html"
    if s.lower().endswith(".pdf"):
        return "pdf"
    if s.lower().endswith((".html", ".htm")):
        return "html"
    raise ValueError(f"cannot detect source type for: {source!r}")


def convert_source(
    *,
    source: str,
    output_root: Path | str,
    config: WriteupConfig,
    force: bool = False,
    keep_evidence: bool = True,
    device: str | None = None,
    page_range: tuple[int, int] | None = None,
    resume: bool = True,
    restart_failed: bool = False,
    stop_after_verified_pages: int | None = None,
) -> ConversionResult:
    """Convert one source into a document directory.

    ``page_range`` is an optional ``(start, stop)`` half-open range of
    0-indexed PDF pages. Only honored for PDF sources. Used by the
    TASK_16 baseline runner; not part of the public CLI surface.
    """
    source_type = detect_source_type(source)

    if source_type == "url":
        from .adapters.url import convert_url

        return convert_url(
            source=source,
            output_root=Path(output_root),
            config=config,
            force=force,
            keep_evidence=keep_evidence,
            device=device,
        )
    if source_type == "pdf":
        if page_range is None:
            from .pdf_checkpoint import convert_pdf_checkpointed

            return convert_pdf_checkpointed(
                source=source,
                output_root=Path(output_root),
                config=config,
                force=force,
                keep_evidence=keep_evidence,
                device=device,
                resume=resume,
                restart_failed=restart_failed,
                stop_after_verified_pages=stop_after_verified_pages,
            )

        from .adapters.pdf import convert_pdf

        return convert_pdf(
            source=source,
            output_root=Path(output_root),
            config=config,
            force=force,
            keep_evidence=keep_evidence,
            device=device,
            page_range=page_range,
        )
    if source_type == "html":
        from .adapters.html import convert_html

        return convert_html(
            source=source,
            output_root=Path(output_root),
            config=config,
            force=force,
            keep_evidence=keep_evidence,
            device=device,
        )
    raise ValueError(f"unsupported source type: {source_type}")
