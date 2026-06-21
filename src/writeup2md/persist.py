"""Shared helpers for assembling and persisting a document directory."""

from __future__ import annotations

from pathlib import Path

from .completeness import (
    apply_completeness_to_status,
    is_suspicious_document,
    write_completeness_artifacts,
)
from .config import WriteupConfig
from .models import (
    Block,
    Document,
    DocumentStatus,
    Manifest,
    SourceRecord,
    SourceType,
)
from .provenance import build_provenance_records, provenance_to_dicts
from .quality import build_diagnostics, calculate_status
from .render import render_markdown
from .workspace import (
    DIAGNOSTICS_JSON,
    DOCUMENT_JSON,
    DOCUMENT_MD,
    MANIFEST_JSON,
    PROVENANCE_JSONL,
    atomic_write_json,
    atomic_write_text,
    ensure_document_dirs,
    write_jsonl,
)


def finalize_document(
    *,
    document_dir: Path,
    manifest: Manifest,
    source: SourceRecord,
    blocks: list[Block],
    config: WriteupConfig,
    raw_assets: dict[str, bytes] | None = None,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
    status_reasons: list[str] | None = None,
    force: bool = False,
    keep_evidence: bool = True,
    enrich: bool = True,
    ocr_backend=None,
    ocr_backend_name: str | None = None,
) -> Document:
    """Compute status, write all artifacts, return the assembled Document."""
    ensure_document_dirs(document_dir)

    # Persist raw assets (immutable).
    if raw_assets:
        raw_dir = document_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        for name, content in raw_assets.items():
            target = raw_dir / name
            if target.exists() and not force:
                continue
            target.write_bytes(content)

    # Build a preliminary document.
    doc = Document(manifest=manifest, source=source, blocks=blocks)

    # Optionally enrich unresolved visual blocks via OCR.
    if enrich and any(
        b.type.value == "visual" and b.visual_state is not None
        and b.visual_state.value not in ("resolved_native", "resolved_ocr", "resolved_structured", "ignored_decorative")
        for b in blocks
    ):
        try:
            from .ocr.enricher import enrich_document

            enrichment_warnings: list[str] = []

            def _on_warning(msg: str) -> None:
                enrichment_warnings.append(msg)

            doc = enrich_document(
                doc,
                document_dir=document_dir,
                config=config,
                backend=ocr_backend,
                backend_name=ocr_backend_name,
                on_warning=_on_warning,
            )
            # Pull the enriched blocks back into the local list so the rest of
            # finalize operates on the updated state.
            blocks = doc.blocks
            if enrichment_warnings:
                if warnings is None:
                    warnings = []
                warnings.extend(enrichment_warnings)
        except Exception as e:  # noqa: BLE001
            if warnings is None:
                warnings = []
            warnings.append(f"OCR enrichment failed: {e}")
            # Continue without enrichment — visual blocks remain review_required.

    # Recompute status & diagnostics with the (possibly enriched) blocks.
    doc = Document(manifest=manifest, source=source, blocks=blocks)
    status = calculate_status(doc, config, completed=True, hard_errors=errors or [])
    manifest = manifest.model_copy(update={"status": status})
    doc = Document(manifest=manifest, source=source, blocks=blocks)
    diagnostics = build_diagnostics(
        doc,
        status_reasons=status_reasons or [],
        warnings=warnings or [],
        errors=errors or [],
    )
    diagnostics = diagnostics.model_copy(update={"status": status})
    doc = Document(manifest=manifest, source=source, blocks=blocks, diagnostics=diagnostics)
    doc.provenance = build_provenance_records(doc)

    # Write artifacts. TASK_18: render in document mode by default;
    # strict mode keeps HTML-comment markers for review_required
    # visuals so the review UI can locate them.
    render_mode = getattr(config.quality, "mode", "document") or "document"
    md = render_markdown(doc, mode=render_mode)

    # TASK_19: completeness gates. Compute invariants, apply them to
    # status, then write completeness.json + quality_report.json.
    suspicious, suspicious_reason = is_suspicious_document(doc, md)
    completeness = write_completeness_artifacts(
        document_dir=document_dir,
        document=doc,
        markdown_text=md,
        mode=render_mode,
        diagnostics=diagnostics,
    )
    final_status, completeness_reasons = apply_completeness_to_status(
        status=status,
        completeness=completeness,
        is_suspicious=suspicious,
    )
    if final_status != status:
        status = final_status
        manifest = manifest.model_copy(update={"status": status})
        diagnostics = diagnostics.model_copy(update={"status": status})
        if status_reasons is None:
            status_reasons = []
        status_reasons = list(status_reasons) + completeness_reasons
        if suspicious_reason:
            status_reasons.append(suspicious_reason)
        diagnostics = diagnostics.model_copy(
            update={"status_reasons": status_reasons}
        )
        doc = Document(
            manifest=manifest, source=source, blocks=blocks, diagnostics=diagnostics
        )
        doc.provenance = build_provenance_records(doc)
        # Re-render in case status change affects anything (it shouldn't
        # for the markdown body, but provenance is rebuilt above).
        md = render_markdown(doc, mode=render_mode)

    atomic_write_text(document_dir / DOCUMENT_MD, md)
    atomic_write_json(document_dir / DOCUMENT_JSON, doc.model_dump(mode="json"))
    atomic_write_json(document_dir / MANIFEST_JSON, manifest.model_dump(mode="json"))
    atomic_write_json(document_dir / DIAGNOSTICS_JSON, diagnostics.model_dump(mode="json"))
    write_jsonl(document_dir / PROVENANCE_JSONL, provenance_to_dicts(doc.provenance))

    return doc
