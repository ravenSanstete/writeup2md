"""Cross-page reconstruction for full-book PDF page shards."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import Block, BlockType, VisualType
from .workspace import atomic_write_json, atomic_write_text


RECONSTRUCTION_DIAGNOSTICS_JSON = "reconstruction_diagnostics.json"

_EDGE_BAND_PT = 90.0
_MAX_FURNITURE_TEXT_LEN = 160
_GENERATOR_PATTERNS = (
    re.compile(r"\bpowered\s+by\s+tcpdf\b", re.IGNORECASE),
    re.compile(r"\bcreated\s+with\s+tcpdf\b", re.IGNORECASE),
    re.compile(r"\bgenerated\s+by\s+tcpdf\b", re.IGNORECASE),
)
_CODE_VISUAL_TYPES = {
    VisualType.CODE,
    VisualType.TERMINAL,
    VisualType.HTTP,
    VisualType.DIFF,
    VisualType.CONFIGURATION,
    VisualType.LOG,
    VisualType.STACK_TRACE,
}


@dataclass
class ReconstructionStats:
    furniture_removed_count: int = 0
    cross_page_paragraph_merges: int = 0
    cross_page_code_merges: int = 0
    unsafe_merge_candidates_skipped: int = 0
    unsafe_merge_candidates: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "furniture_removed_count": self.furniture_removed_count,
            "cross_page_paragraph_merges": self.cross_page_paragraph_merges,
            "cross_page_code_merges": self.cross_page_code_merges,
            "unsafe_merge_candidates_skipped": self.unsafe_merge_candidates_skipped,
            "unsafe_merge_candidates": self.unsafe_merge_candidates,
        }


def reconstruct_cross_page_blocks(
    blocks: list[Block],
    *,
    document_dir: Path | None = None,
) -> tuple[list[Block], list[dict[str, Any]]]:
    """Apply conservative document-level reconstruction.

    The pass avoids inventing content. It only removes repeated page furniture
    with strong cross-page evidence and merges adjacent page-boundary prose or
    code blocks when block type/context supports continuation.
    """
    removed: list[dict[str, Any]] = []
    stats = ReconstructionStats()
    filtered = _remove_repeated_furniture(blocks, removed)
    stats.furniture_removed_count = len(removed)
    merged = _merge_cross_page_blocks(filtered, stats)
    if document_dir is not None:
        _write_removed_records(document_dir, removed)
        atomic_write_json(document_dir / RECONSTRUCTION_DIAGNOSTICS_JSON, stats.to_dict())
    return merged, removed


def _remove_repeated_furniture(blocks: list[Block], removed: list[dict[str, Any]]) -> list[Block]:
    page_count = len({page for block in blocks for page in [_block_page(block)] if page is not None})
    if page_count < 3:
        return blocks
    page_bottoms = _infer_page_bottoms(blocks)
    candidates: dict[str, list[Block]] = defaultdict(list)
    candidate_meta: dict[str, dict[str, Any]] = {}
    for block in blocks:
        if not _eligible_for_furniture(block):
            continue
        text = _block_text(block).strip()
        if not text or len(text) > _MAX_FURNITURE_TEXT_LEN:
            continue
        page = _block_page(block)
        bbox = _block_bbox(block)
        if page is None or bbox is None:
            continue
        band = _page_band(block, page_bottoms)
        if band == "body" and not _looks_like_page_number(text) and not _is_known_generator(text):
            continue
        signature = _furniture_signature(text)
        if not signature:
            continue
        candidates[signature].append(block)
        candidate_meta.setdefault(
            signature,
            {
                "signature": signature,
                "band": band,
                "sample_text": text,
                "known_generator": _is_known_generator(text),
                "page_number_like": _looks_like_page_number(text),
            },
        )

    repeated = {
        signature
        for signature, hits in candidates.items()
        if _strong_furniture_evidence(signature, hits, candidate_meta[signature], page_count)
    }
    out: list[Block] = []
    for block in blocks:
        signature = _furniture_signature(_block_text(block))
        if signature in repeated and _eligible_for_furniture(block):
            hits = candidates[signature]
            pages = sorted(p for p in {_block_page(b) for b in hits} if p is not None)
            removed.append(
                {
                    "block_id": block.block_id,
                    "page": _block_page(block),
                    "text": _block_text(block),
                    "bbox": _block_bbox(block),
                    "reason": _furniture_reason(signature, candidate_meta[signature]),
                    "signature": signature,
                    "evidence_count": len(hits),
                    "pages": pages,
                    "confidence": _furniture_confidence(hits, page_count, candidate_meta[signature]),
                }
            )
            continue
        out.append(block)
    return out


def _merge_cross_page_blocks(blocks: list[Block], stats: ReconstructionStats) -> list[Block]:
    out: list[Block] = []
    for block in sorted(blocks, key=lambda b: b.order):
        if not out:
            out.append(block)
            continue
        prev = out[-1]
        if _are_adjacent_pages(prev, block) and _can_merge_prose(prev, block):
            merged_text, transformations = _merge_prose_text(_block_text(prev), _block_text(block))
            out[-1] = prev.model_copy(
                update={
                    "text": merged_text,
                    "evidence": [*prev.evidence, *block.evidence],
                    "extra": {
                        **prev.extra,
                        "cross_page_merged_blocks": [
                            *prev.extra.get("cross_page_merged_blocks", []),
                            block.block_id,
                        ],
                        "transformations": [
                            *prev.extra.get("transformations", []),
                            *transformations,
                        ],
                    },
                }
            )
            stats.cross_page_paragraph_merges += 1
            continue
        if _are_adjacent_pages(prev, block) and _can_merge_code(prev, block):
            merged_text = _block_text(prev).rstrip("\n") + "\n" + _block_text(block).lstrip("\n")
            out[-1] = _copy_block_with_text(
                prev,
                merged_text,
                evidence=[*prev.evidence, *block.evidence],
                extra={
                    **prev.extra,
                    "cross_page_merged_blocks": [
                        *prev.extra.get("cross_page_merged_blocks", []),
                        block.block_id,
                    ],
                    "transformations": [
                        *prev.extra.get("transformations", []),
                        "merged_cross_page_code",
                    ],
                },
            )
            stats.cross_page_code_merges += 1
            continue
        if _are_adjacent_pages(prev, block) and _looks_like_boundary_continuation(prev, block):
            stats.unsafe_merge_candidates_skipped += 1
            stats.unsafe_merge_candidates.append(
                {
                    "previous_block_id": prev.block_id,
                    "next_block_id": block.block_id,
                    "previous_page": _block_page(prev),
                    "next_page": _block_page(block),
                    "reason": "boundary continuation signals present but merge rules were not strong enough",
                    "previous_excerpt": _block_text(prev)[-120:],
                    "next_excerpt": _block_text(block)[:120],
                }
            )
        out.append(block)
    return [b.model_copy(update={"order": i}) for i, b in enumerate(out)]


def _can_merge_prose(prev: Block, block: Block) -> bool:
    if prev.type != BlockType.PARAGRAPH or block.type != BlockType.PARAGRAPH:
        return False
    a = _block_text(prev).rstrip()
    b = _block_text(block).lstrip()
    if not a or not b:
        return False
    if _looks_codeish(a) or _looks_codeish(b):
        return False
    if a.endswith((".", "!", "?", ":", ";", "。", "！", "？")):
        return False
    return bool(re.match(r"^[a-z,，)]", b))


def _merge_prose_text(a: str, b: str) -> tuple[str, list[str]]:
    transformations: list[str] = ["merged_cross_page_paragraph"]
    a = a.rstrip()
    b = b.lstrip()
    if a.endswith("-") and b and b[0].islower() and not _looks_codeish(a[-40:] + b[:40]):
        transformations.append("dehyphenated_cross_page_prose")
        return a[:-1] + b, transformations
    return a + " " + b, transformations


def _can_merge_code(prev: Block, block: Block) -> bool:
    if not (_is_codeish_block(prev) and _is_codeish_block(block)):
        return False
    if _block_language(prev) != _block_language(block):
        return False
    a = _block_text(prev).rstrip()
    b = _block_text(block).lstrip()
    if not a or not b:
        return False
    if re.search(r"[\{\(\[:]\s*$", a):
        return True
    if _unbalanced_code_context(a):
        return True
    if _line_numbers_continue(a, b):
        return True
    if b.startswith((" ", "\t", ".", ")", "]", "}")):
        return True
    return False


def _eligible_for_furniture(block: Block) -> bool:
    if block.type in (BlockType.PARAGRAPH, BlockType.HEADING):
        return True
    if block.type == BlockType.VISUAL and _is_known_generator(_block_text(block)):
        return True
    return False


def _are_adjacent_pages(prev: Block, block: Block) -> bool:
    p1 = _block_page(prev)
    p2 = _block_page(block)
    return p1 is not None and p2 is not None and p2 == p1 + 1


def _block_page(block: Block) -> int | None:
    if not block.evidence:
        return None
    return block.evidence[0].page


def _block_bbox(block: Block) -> list[float] | None:
    if not block.evidence:
        return None
    return block.evidence[0].bbox


def _norm(text: str) -> str:
    return " ".join(text.lower().strip().split())


def _furniture_signature(text: str) -> str:
    text = _norm(text)
    if not text:
        return ""
    text = text.replace("’", "'").replace("–", "-").replace("—", "-")
    text = re.sub(r"\bpage\s+\d{1,4}\b", "page#", text)
    text = re.sub(r"\b\d{1,4}\s+chapter\s+\d{1,3}\b", "chapter#", text)
    text = re.sub(r"\bchapter\s+\d{1,3}\s+\d{1,4}\b", "chapter#", text)
    text = re.sub(r"\bchapter\s+\d{1,3}\b", "chapter#", text)
    text = re.sub(r"\b\d{1,4}\b", "#", text)
    text = re.sub(r"[\s\.\-_:|]+", " ", text).strip()
    if _is_known_generator(text):
        return "generator:tcpdf"
    if re.fullmatch(r"(page#|#)", text):
        return "page-number"
    # For running titles like "Back to the '90s 17" or "16 Chapter 2",
    # the numeric stripping above leaves the stable title/chapter signature.
    return text


def _looks_like_page_number(text: str) -> bool:
    return bool(re.fullmatch(r"(page\s*)?\d{1,4}", text.strip(), re.IGNORECASE))


def _is_known_generator(text: str) -> bool:
    return any(p.search(text) for p in _GENERATOR_PATTERNS)


def _looks_codeish(text: str) -> bool:
    return bool(
        re.search(
            r"(--\w+|https?://|/[A-Za-z0-9_.\-/]+|[A-Za-z_][A-Za-z0-9_]*\(|[0-9a-f]{16,})",
            text,
        )
    )


def _block_text(block: Block) -> str:
    if block.text:
        return block.text
    if block.enrichment is not None:
        return block.enrichment.selected_text or block.enrichment.raw_text or ""
    return ""


def _copy_block_with_text(
    block: Block,
    text: str,
    *,
    evidence,
    extra: dict[str, Any],
) -> Block:
    if block.enrichment is not None:
        enrichment = block.enrichment.model_copy(
            update={
                "selected_text": text,
                "raw_text": text,
            }
        )
        return block.model_copy(update={"enrichment": enrichment, "evidence": evidence, "extra": extra})
    return block.model_copy(update={"text": text, "evidence": evidence, "extra": extra})


def _block_language(block: Block) -> str:
    if block.language:
        return block.language
    if block.enrichment is not None and block.enrichment.language:
        return block.enrichment.language
    if block.visual_type is not None:
        return block.visual_type.value
    return ""


def _is_codeish_block(block: Block) -> bool:
    if block.type == BlockType.NATIVE_CODE:
        return True
    return block.type == BlockType.VISUAL and block.visual_type in _CODE_VISUAL_TYPES


def _infer_page_bottoms(blocks: list[Block]) -> dict[int, float]:
    bottoms: dict[int, float] = {}
    for block in blocks:
        page = _block_page(block)
        bbox = _block_bbox(block)
        if page is None or bbox is None:
            continue
        bottoms[page] = max(bottoms.get(page, 0.0), float(bbox[3]))
    return bottoms


def _page_band(block: Block, page_bottoms: dict[int, float]) -> str:
    page = _block_page(block)
    bbox = _block_bbox(block)
    if page is None or bbox is None:
        return "body"
    y0, y1 = float(bbox[1]), float(bbox[3])
    bottom = page_bottoms.get(page, 0.0)
    if y0 <= _EDGE_BAND_PT:
        return "top"
    if bottom > 500 and y1 >= bottom - _EDGE_BAND_PT:
        return "bottom"
    if y1 > 700:
        return "bottom"
    return "body"


def _strong_furniture_evidence(
    signature: str,
    hits: list[Block],
    meta: dict[str, Any],
    page_count: int,
) -> bool:
    pages = {p for p in (_block_page(b) for b in hits) if p is not None}
    if not pages:
        return False
    if meta.get("known_generator"):
        return len(pages) >= 2 or page_count <= 3
    if meta.get("page_number_like") or signature == "page-number":
        return len(pages) >= 2
    required = max(3, int(page_count * 0.25))
    return len(pages) >= required and _coordinate_stable(hits)


def _coordinate_stable(hits: list[Block]) -> bool:
    ys = []
    for block in hits:
        bbox = _block_bbox(block)
        if bbox is not None:
            ys.append(float(bbox[1]))
    if len(ys) < 2:
        return False
    return max(ys) - min(ys) <= 36.0


def _furniture_confidence(hits: list[Block], page_count: int, meta: dict[str, Any]) -> float:
    pages = {p for p in (_block_page(b) for b in hits) if p is not None}
    recurrence = min(1.0, len(pages) / max(1, page_count))
    confidence = 0.65 + recurrence * 0.3
    if meta.get("known_generator") or meta.get("page_number_like"):
        confidence += 0.15
    if _coordinate_stable(hits):
        confidence += 0.1
    return min(0.99, round(confidence, 3))


def _furniture_reason(signature: str, meta: dict[str, Any]) -> str:
    if meta.get("known_generator"):
        return "known PDF generator footer/header"
    if meta.get("page_number_like") or signature == "page-number":
        return "page-number-only furniture"
    return "repeated header/footer/running-title candidate"


def _unbalanced_code_context(text: str) -> bool:
    pairs = {"(": ")", "[": "]", "{": "}"}
    for open_ch, close_ch in pairs.items():
        if text.count(open_ch) > text.count(close_ch):
            return True
    return False


def _line_numbers_continue(a: str, b: str) -> bool:
    last = _last_line_number(a)
    first = _first_line_number(b)
    return last is not None and first is not None and first in (last + 1, last + 2)


def _last_line_number(text: str) -> int | None:
    for line in reversed(text.splitlines()):
        m = re.match(r"^\s*(\d{1,5})\b", line)
        if m:
            return int(m.group(1))
    return None


def _first_line_number(text: str) -> int | None:
    for line in text.splitlines():
        m = re.match(r"^\s*(\d{1,5})\b", line)
        if m:
            return int(m.group(1))
    return None


def _looks_like_boundary_continuation(prev: Block, block: Block) -> bool:
    a = _block_text(prev).rstrip()
    b = _block_text(block).lstrip()
    if not a or not b:
        return False
    if _block_page(prev) is None or _block_page(block) is None:
        return False
    if a.endswith((".", "!", "?", "。", "！", "？")):
        return False
    return bool(re.match(r"^[a-z,，)]", b)) or _line_numbers_continue(a, b)


def _write_removed_records(document_dir: Path, removed: list[dict[str, Any]]) -> None:
    path = document_dir / "reconstruction_removed.jsonl"
    text = "".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in removed)
    atomic_write_text(path, text)
