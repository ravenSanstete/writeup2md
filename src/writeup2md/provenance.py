"""Build per-block provenance records and write the provenance ledger."""

from __future__ import annotations

from typing import Iterable

from .models import Block, Document, Provenance, SourceType
from .render import render_block_markdown


def build_provenance_records(document: Document) -> list[Provenance]:
    """One provenance record per final Markdown block."""
    out: list[Provenance] = []
    for block in sorted(document.blocks, key=lambda b: b.order):
        final_text = render_block_markdown(block)
        transformations: list[str] = []
        if block.enrichment is not None:
            transformations.extend(block.enrichment.transformations)
        out.append(
            Provenance(
                block_id=block.block_id,
                source_kind=document.source.source_type,
                source_ref=document.source.canonical_source,
                evidence=list(block.evidence),
                transformations=transformations,
                raw_text=block.enrichment.raw_text if block.enrichment else block.text,
                final_text=final_text,
            )
        )
    return out


def provenance_to_dicts(records: Iterable[Provenance]) -> list[dict]:
    return [r.model_dump(mode="json") for r in records]
