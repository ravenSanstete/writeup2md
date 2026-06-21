"""Visual coverage ledger.

Every visual block in the main content area must end in exactly one
explicit state:

    transcribed                  — OCR produced text, accepted or routed to review
    native_text_used             — native PDF text or DOM code used instead of OCR
    decorative_with_reason       — image classified as decorative
    duplicate_with_reference     — image duplicates native text/DOM, reference recorded
    review_required              — could not be resolved; needs human review
    failed_with_diagnostic       — pipeline error; diagnostic recorded

This module provides:
- `COVERAGE_STATES` — the canonical set
- `apply_coverage_state(block, state, reason)` — sets both block.coverage_state
  and block.enrichment.coverage_state (when enrichment exists)
- `coverage_summary(blocks)` — counts by state, for diagnostics
- `assert_all_visuals_covered(blocks)` — raises if any visual is uncovered
"""

from __future__ import annotations

from typing import Any

from .models import Block, BlockType, VisualBlockState


COVERAGE_STATES: frozenset[str] = frozenset(
    {
        "transcribed",
        "native_text_used",
        "decorative_with_reason",
        "duplicate_with_reference",
        "review_required",
        "failed_with_diagnostic",
    }
)


def apply_coverage_state(block: Block, state: str, reason: str = "") -> None:
    """Set the coverage state on a block. Validates against the canonical set."""
    if state not in COVERAGE_STATES:
        raise ValueError(
            f"unknown coverage state {state!r}; must be one of {sorted(COVERAGE_STATES)}"
        )
    block.coverage_state = state
    block.coverage_reason = reason or None
    if block.enrichment is not None:
        block.enrichment.coverage_state = state
        block.enrichment.coverage_reason = reason or None


def derive_coverage_state_from_visual_state(block: Block) -> str:
    """Map a VisualBlockState to a coverage state.

    Used when no explicit reason was recorded. Returns the best-fitting
    coverage state. Does NOT mutate the block.
    """
    vs = block.visual_state
    if vs == VisualBlockState.RESOLVED_OCR or vs == VisualBlockState.RESOLVED_NATIVE or vs == VisualBlockState.RESOLVED_STRUCTURED:
        return "transcribed"
    if vs == VisualBlockState.IGNORED_DECORATIVE:
        return "decorative_with_reason"
    if vs == VisualBlockState.FAILED:
        return "failed_with_diagnostic"
    # REVIEW_REQUIRED or None
    return "review_required"


def coverage_summary(blocks: list[Block]) -> dict[str, Any]:
    """Return a summary of coverage states across the given blocks.

    Only visual blocks are counted. The summary includes a `missing` count
    for visual blocks without an explicit coverage_state.
    """
    counts: dict[str, int] = {s: 0 for s in COVERAGE_STATES}
    missing = 0
    total_visual = 0
    for b in blocks:
        if b.type != BlockType.VISUAL:
            continue
        total_visual += 1
        if b.coverage_state is None:
            # Try to derive from visual_state when possible.
            derived = derive_coverage_state_from_visual_state(b)
            if derived and b.visual_state in (
                VisualBlockState.RESOLVED_OCR,
                VisualBlockState.RESOLVED_NATIVE,
                VisualBlockState.RESOLVED_STRUCTURED,
                VisualBlockState.IGNORED_DECORATIVE,
                VisualBlockState.FAILED,
            ):
                counts[derived] += 1
            else:
                missing += 1
        else:
            counts[b.coverage_state] += 1
    return {
        "total_visual_blocks": total_visual,
        "by_state": counts,
        "missing": missing,
        "all_covered": missing == 0,
    }


def assert_all_visuals_covered(blocks: list[Block]) -> None:
    """Raise AssertionError if any visual block lacks an explicit coverage state.

    Used by tests. Visual blocks with a resolvable visual_state (resolved_*,
    ignored_decorative, failed) are considered covered even without an
    explicit coverage_state field, because the visual_state itself is the
    ledger entry.
    """
    uncovered: list[str] = []
    for b in blocks:
        if b.type != BlockType.VISUAL:
            continue
        if b.coverage_state is not None:
            continue
        if b.visual_state in (
            VisualBlockState.RESOLVED_OCR,
            VisualBlockState.RESOLVED_NATIVE,
            VisualBlockState.RESOLVED_STRUCTURED,
            VisualBlockState.IGNORED_DECORATIVE,
            VisualBlockState.FAILED,
        ):
            continue
        # REVIEW_REQUIRED with no coverage_state is uncovered (silently
        # routed without an explicit ledger entry).
        uncovered.append(b.block_id)
    if uncovered:
        raise AssertionError(
            f"{len(uncovered)} visual block(s) lack explicit coverage state: {uncovered[:5]}"
        )
