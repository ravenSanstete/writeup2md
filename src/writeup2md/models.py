"""Unified document intermediate representation (IR) for writeup2md.

All inputs (PDF, URL, HTML) become the same sequence of Block instances so the
Markdown renderer never needs to know the source type.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


SCHEMA_VERSION = "1.0"


class SourceType(str, Enum):
    PDF = "pdf"
    URL = "url"
    HTML = "html"


class DocumentStatus(str, Enum):
    ACCEPTED = "accepted"
    REVIEW = "review"
    REJECTED = "rejected"
    FAILED = "failed"


class VisualBlockState(str, Enum):
    RESOLVED_NATIVE = "resolved_native"
    RESOLVED_OCR = "resolved_ocr"
    RESOLVED_STRUCTURED = "resolved_structured"
    REVIEW_REQUIRED = "review_required"
    IGNORED_DECORATIVE = "ignored_decorative"
    FAILED = "failed"


class VisualType(str, Enum):
    CODE = "code"
    TERMINAL = "terminal"
    HTTP = "http"
    DIFF = "diff"
    CONFIGURATION = "configuration"
    LOG = "log"
    STACK_TRACE = "stack_trace"
    TABLE = "table"
    DIAGRAM = "diagram"
    UI_SCREENSHOT = "ui_screenshot"
    DECORATIVE = "decorative"
    UNKNOWN = "unknown"


# Visual types considered "important" — i.e. they must be resolved for acceptance.
IMPORTANT_VISUAL_TYPES: frozenset[VisualType] = frozenset(
    {
        VisualType.CODE,
        VisualType.TERMINAL,
        VisualType.HTTP,
        VisualType.DIFF,
        VisualType.CONFIGURATION,
        VisualType.LOG,
        VisualType.STACK_TRACE,
        VisualType.TABLE,
    }
)


# Visual types that may safely be marked decorative.
DECORATIVE_VISUAL_TYPES: frozenset[VisualType] = frozenset(
    {VisualType.DECORATIVE, VisualType.UI_SCREENSHOT, VisualType.DIAGRAM}
)


class BlockType(str, Enum):
    PARAGRAPH = "paragraph"
    HEADING = "heading"
    NATIVE_CODE = "native_code"
    VISUAL = "visual"
    LIST = "list"
    QUOTE = "quote"
    TABLE = "table"
    HORIZONTAL_RULE = "horizontal_rule"
    UNKNOWN = "unknown"


class EvidenceKind(str, Enum):
    PDF_REGION = "pdf_region"
    DOM_ELEMENT = "dom_element"
    URL_ASSET = "url_asset"
    RAW_FILE = "raw_file"


class EvidenceRef(BaseModel):
    """Reference to an original source asset."""

    kind: EvidenceKind
    page: int | None = None
    bbox: list[float] | None = None
    url: str | None = None
    selector: str | None = None
    xpath: str | None = None
    asset_path: str
    content_sha256: str | None = None
    captured_at: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class Provenance(BaseModel):
    """Provenance record for a final Markdown block."""

    block_id: str
    source_kind: SourceType
    source_ref: str  # canonical_source
    evidence: list[EvidenceRef] = Field(default_factory=list)
    transformations: list[str] = Field(default_factory=list)
    raw_text: str | None = None
    final_text: str | None = None


class EnrichedVisual(BaseModel):
    """Post-OCR enrichment record for a visual block."""

    visual_type: VisualType
    raw_text: str
    selected_text: str
    language: str | None = None
    segments: list[dict[str, Any]] = Field(default_factory=list)
    confidence: float = 0.0
    review_required: bool = False
    transformations: list[str] = Field(default_factory=list)
    backend: str | None = None
    backend_version: str | None = None
    # Visual coverage ledger (TASK_10). One of:
    # transcribed | native_text_used | decorative_with_reason |
    # duplicate_with_reference | review_required | failed_with_diagnostic.
    # None for blocks that have not yet been resolved.
    coverage_state: str | None = None
    coverage_reason: str | None = None


class Block(BaseModel):
    """A single ordered block in the unified IR."""

    block_id: str
    order: int
    type: BlockType
    text: str | None = None
    language: str | None = None
    heading_level: int | None = None
    list_items: list[str] | None = None
    table_rows: list[list[str]] | None = None
    visual_type: VisualType | None = None
    visual_state: VisualBlockState | None = None
    enrichment: EnrichedVisual | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)
    provenance_source_ref: str | None = None
    source_kind: SourceType | None = None
    extra: dict[str, Any] = Field(default_factory=dict)
    # Visual coverage ledger (TASK_10). Top-level mirror of
    # enrichment.coverage_state so the diagnostics/UI can read it without
    # dereferencing enrichment. None for non-visual blocks or unresolved ones.
    coverage_state: str | None = None
    coverage_reason: str | None = None

    @field_validator("order")
    @classmethod
    def _order_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("block order must be >= 0")
        return v


class SourceRecord(BaseModel):
    """Identity of the source a document came from."""

    source_type: SourceType
    source: str
    canonical_source: str
    captured_at: str
    content_sha256: str
    extra: dict[str, Any] = Field(default_factory=dict)


class Manifest(BaseModel):
    schema_version: str = SCHEMA_VERSION
    document_id: str
    source: str
    source_type: SourceType
    canonical_source: str
    captured_at: str
    content_sha256: str
    config_sha256: str
    status: DocumentStatus
    tags: list[str] = Field(default_factory=list)
    profile: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class QualityReport(BaseModel):
    """Aggregated quality metrics for a document."""

    native_text_coverage: float = 0.0
    important_visual_resolution_rate: float = 0.0
    ocr_enriched_block_count: int = 0
    unresolved_visual_count: int = 0
    reading_order_violations: int = 0
    markdown_image_count: int = 0
    overall_quality_score: float = 0.0
    block_counts_by_type: dict[str, int] = Field(default_factory=dict)
    unresolved_blocks: list[str] = Field(default_factory=list)
    low_confidence_blocks: list[str] = Field(default_factory=list)
    ocr_confidence_distribution: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class Diagnostics(BaseModel):
    """Per-document diagnostics file content."""

    schema_version: str = SCHEMA_VERSION
    document_id: str
    status: DocumentStatus
    status_reasons: list[str] = Field(default_factory=list)
    block_counts: dict[str, int] = Field(default_factory=dict)
    unresolved_important_visuals: list[str] = Field(default_factory=list)
    low_confidence_blocks: list[str] = Field(default_factory=list)
    ocr_confidence_distribution: dict[str, int] = Field(default_factory=dict)
    markdown_image_count: int = 0
    processing_warnings: list[str] = Field(default_factory=list)
    processing_errors: list[str] = Field(default_factory=list)
    quality: QualityReport = Field(default_factory=QualityReport)
    # Visual coverage ledger (TASK_10). Summary of how every visual block
    # ended. Includes per-state counts plus a `missing` count for any visual
    # block that lacks an explicit coverage_state.
    visual_coverage: dict[str, Any] | None = None


class Document(BaseModel):
    """Top-level document model combining IR + manifest + diagnostics."""

    manifest: Manifest
    source: SourceRecord
    blocks: list[Block] = Field(default_factory=list)
    diagnostics: Diagnostics | None = None
    provenance: list[Provenance] = Field(default_factory=list)


def now_iso_utc() -> str:
    """Return current UTC time in ISO 8601 with second precision and 'Z' suffix."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Deterministic document IDs
# ---------------------------------------------------------------------------

_BLOCK_ID_RE = re.compile(r"[^a-zA-Z0-9]+")


def canonicalize_source(source: str) -> str:
    """Produce a canonical source identifier.

    For URLs: scheme normalized to lowercase, host lowercased, fragment dropped,
    trailing slash dropped. For local paths: resolved absolute, no symlink
    resolution (so the user-visible path is preserved). For everything else,
    returned as-is.
    """
    lowered = source.lower()
    if lowered.startswith(("http://", "https://")):
        from urllib.parse import urlsplit, urlunsplit

        parts = urlsplit(source)
        scheme = parts.scheme.lower()
        netloc = parts.netloc.lower()
        path = parts.path
        if path.endswith("/"):
            path = path[:-1]
        return urlunsplit((scheme, netloc, path, parts.query, ""))
    return source


def content_sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def content_sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_document_id(
    *,
    source: str,
    canonical_source: str,
    content_sha256: str,
    config_sha256: str,
    explicit_id: str | None = None,
) -> str:
    """Deterministic document ID.

    If an explicit id is provided, use it after slug-style normalization.
    Otherwise, derive a stable 16-hex-char id from canonical_source and content
    hash. Config hash is mixed in only when the user opts in via including it
    explicitly; for v1 we include it so a config change produces a new document
    slot (matching the resume/skip rule).
    """
    if explicit_id:
        slug = _BLOCK_ID_RE.sub("-", explicit_id.strip().lower()).strip("-")
        return slug or "doc"

    h = hashlib.sha256()
    h.update(canonical_source.encode("utf-8"))
    h.update(b"\x1f")
    h.update(content_sha256.encode("utf-8"))
    h.update(b"\x1f")
    h.update(config_sha256.encode("utf-8"))
    return h.hexdigest()[:16]


def next_block_id(index: int, prefix: str = "b") -> str:
    """Return a deterministic, zero-padded block id."""
    return f"{prefix}_{index:06d}"
