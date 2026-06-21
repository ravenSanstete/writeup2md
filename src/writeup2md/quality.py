"""Quality gates and document status calculation.

Implements the acceptance policy from docs/06_QUALITY_AND_TESTING.md:

A document is accepted only when:
- processing completed;
- Markdown is non-empty;
- no images remain in Markdown;
- all important visuals are resolved;
- every OCR-derived block has evidence;
- no hard quality gate failed.
"""

from __future__ import annotations

from typing import Iterable

from .config import WriteupConfig
from .models import (
    Block,
    BlockType,
    Diagnostics,
    Document,
    DocumentStatus,
    IMPORTANT_VISUAL_TYPES,
    QualityReport,
    VisualBlockState,
    VisualType,
)
from .render import count_image_references, render_markdown, strip_image_references


IMPORTANT_RESOLVED_STATES: frozenset[VisualBlockState] = frozenset(
    {
        VisualBlockState.RESOLVED_NATIVE,
        VisualBlockState.RESOLVED_OCR,
        VisualBlockState.RESOLVED_STRUCTURED,
    }
)


def is_important_visual(block: Block) -> bool:
    """A visual is 'important' if it is not clearly decorative.

    UNKNOWN visuals are treated as important-by-default for safety — we have
    not yet classified them, so we must not silently discard them. The OCR
    router (TASK_04) will later reclassify them as code/terminal/HTTP/... or
    decorative.
    """
    if block.type != BlockType.VISUAL:
        return False
    vtype = block.visual_type or VisualType.UNKNOWN
    if vtype == VisualType.UNKNOWN:
        return True
    return vtype in IMPORTANT_VISUAL_TYPES


def is_unresolved_important(block: Block) -> bool:
    if not is_important_visual(block):
        return False
    state = block.visual_state
    if state is None:
        return True
    return state not in IMPORTANT_RESOLVED_STATES and state != VisualBlockState.IGNORED_DECORATIVE


def is_low_confidence(block: Block, threshold: float = 0.7) -> bool:
    if block.enrichment is None:
        return False
    return block.enrichment.confidence < threshold and block.enrichment.review_required


def compute_quality_report(document: Document) -> QualityReport:
    blocks = document.blocks
    total_blocks = len(blocks)
    native_text_blocks = sum(
        1
        for b in blocks
        if b.type in (BlockType.PARAGRAPH, BlockType.HEADING, BlockType.LIST, BlockType.QUOTE)
        and b.text
    )
    native_code_blocks = sum(1 for b in blocks if b.type == BlockType.NATIVE_CODE)
    visual_blocks = [b for b in blocks if b.type == BlockType.VISUAL]
    important_visuals = [b for b in visual_blocks if is_important_visual(b)]
    unresolved = [b for b in important_visuals if is_unresolved_important(b)]
    ocr_enriched = sum(
        1 for b in visual_blocks if b.visual_state == VisualBlockState.RESOLVED_OCR
    )

    # Count images in the *raw* render (before stripping) so leaked image
    # syntax is detected by the quality gate.
    raw_md = render_markdown(document, strip_images=False)
    md_images = count_image_references(raw_md)

    block_counts: dict[str, int] = {}
    for b in blocks:
        block_counts[b.type.value] = block_counts.get(b.type.value, 0) + 1

    # Reading order violations: count blocks whose `order` field is non-monotonic.
    orders = [b.order for b in blocks]
    reading_order_violations = sum(
        1 for i in range(1, len(orders)) if orders[i] <= orders[i - 1]
    )

    # OCR confidence distribution buckets.
    conf_dist: dict[str, int] = {"low": 0, "medium": 0, "high": 0, "none": 0}
    for b in visual_blocks:
        if b.enrichment is None or b.visual_state != VisualBlockState.RESOLVED_OCR:
            conf_dist["none"] += 1
            continue
        c = b.enrichment.confidence
        if c < 0.6:
            conf_dist["low"] += 1
        elif c < 0.85:
            conf_dist["medium"] += 1
        else:
            conf_dist["high"] += 1

    # Coverage metrics
    native_text_coverage = 0.0
    if total_blocks > 0:
        native_text_coverage = (
            (native_text_blocks + native_code_blocks) / total_blocks if total_blocks else 0.0
        )
    important_resolution_rate = 0.0
    if important_visuals:
        important_resolution_rate = (
            len(important_visuals) - len(unresolved)
        ) / len(important_visuals)

    # Overall score: weighted combination.
    score = 0.0
    if total_blocks > 0:
        score = 0.5 * native_text_coverage + 0.4 * important_resolution_rate
        if md_images == 0:
            score += 0.1
    score = max(0.0, min(1.0, score))

    low_conf_blocks = [b.block_id for b in blocks if is_low_confidence(b)]

    return QualityReport(
        native_text_coverage=native_text_coverage,
        important_visual_resolution_rate=important_resolution_rate,
        ocr_enriched_block_count=ocr_enriched,
        unresolved_visual_count=len(unresolved),
        reading_order_violations=reading_order_violations,
        markdown_image_count=md_images,
        overall_quality_score=score,
        block_counts_by_type=block_counts,
        unresolved_blocks=[b.block_id for b in unresolved],
        low_confidence_blocks=low_conf_blocks,
        ocr_confidence_distribution=conf_dist,
    )


def calculate_status(
    document: Document,
    config: WriteupConfig,
    *,
    completed: bool = True,
    hard_errors: Iterable[str] = (),
) -> DocumentStatus:
    """Decide document status based on quality gates."""
    errors = list(hard_errors)
    if not completed:
        return DocumentStatus.FAILED

    raw_md = render_markdown(document, strip_images=False)
    if count_image_references(raw_md) > 0:
        # Final markdown contains images — hard failure.
        return DocumentStatus.REJECTED

    stripped_md = strip_image_references(raw_md)
    if not stripped_md.strip():
        return DocumentStatus.FAILED

    report = compute_quality_report(document)
    if report.markdown_image_count > 0:
        return DocumentStatus.REJECTED
    if config.quality.accepted_requires_zero_unresolved_visuals and report.unresolved_visual_count > 0:
        policy = config.quality.unresolved_important_visual_policy
        if policy == "review":
            return DocumentStatus.REVIEW
        if policy == "reject":
            return DocumentStatus.REJECTED
        return DocumentStatus.REVIEW
    if errors:
        return DocumentStatus.REJECTED
    return DocumentStatus.ACCEPTED


def build_diagnostics(
    document: Document,
    *,
    status_reasons: list[str] | None = None,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
) -> Diagnostics:
    report = compute_quality_report(document)
    # Visual coverage ledger (TASK_10).
    from .coverage import coverage_summary

    visual_coverage = coverage_summary(document.blocks)
    return Diagnostics(
        document_id=document.manifest.document_id,
        status=document.manifest.status,
        status_reasons=status_reasons or [],
        block_counts=report.block_counts_by_type,
        unresolved_important_visuals=report.unresolved_blocks,
        low_confidence_blocks=report.low_confidence_blocks,
        ocr_confidence_distribution=report.ocr_confidence_distribution,
        markdown_image_count=report.markdown_image_count,
        processing_warnings=warnings or [],
        processing_errors=errors or [],
        quality=report,
        visual_coverage=visual_coverage,
    )
