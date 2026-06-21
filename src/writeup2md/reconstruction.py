"""Cross-page reconstruction for full-book PDF page shards."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .models import Block, BlockType
from .workspace import atomic_write_text


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
    filtered = _remove_repeated_furniture(blocks, removed)
    merged = _merge_cross_page_blocks(filtered)
    if document_dir is not None:
        _write_removed_records(document_dir, removed)
    return merged, removed


def _remove_repeated_furniture(blocks: list[Block], removed: list[dict[str, Any]]) -> list[Block]:
    page_count = len({page for block in blocks for page in [_block_page(block)] if page is not None})
    if page_count < 3:
        return blocks
    candidates: dict[str, list[Block]] = defaultdict(list)
    for block in blocks:
        if block.type not in (BlockType.PARAGRAPH, BlockType.HEADING):
            continue
        text = (block.text or "").strip()
        if not text or len(text) > 120:
            continue
        page = _block_page(block)
        bbox = _block_bbox(block)
        if page is None or bbox is None:
            continue
        y0, y1 = bbox[1], bbox[3]
        # PyMuPDF coordinates are page-local. Furniture normally sits near the
        # top or bottom; keep the threshold intentionally broad.
        near_edge = y0 < 90 or y1 > 700
        if not near_edge and not _looks_like_page_number(text):
            continue
        candidates[_norm(text)].append(block)

    repeated = {
        text_norm
        for text_norm, hits in candidates.items()
        if len({ _block_page(b) for b in hits }) >= max(3, int(page_count * 0.35))
    }
    out: list[Block] = []
    for block in blocks:
        text_norm = _norm(block.text or "")
        if text_norm in repeated and block.type in (BlockType.PARAGRAPH, BlockType.HEADING):
            removed.append(
                {
                    "block_id": block.block_id,
                    "page": _block_page(block),
                    "text": block.text,
                    "reason": "repeated header/footer/page-number candidate",
                    "evidence_count": len(candidates[text_norm]),
                }
            )
            continue
        out.append(block)
    return out


def _merge_cross_page_blocks(blocks: list[Block]) -> list[Block]:
    out: list[Block] = []
    for block in sorted(blocks, key=lambda b: b.order):
        if not out:
            out.append(block)
            continue
        prev = out[-1]
        if _are_adjacent_pages(prev, block) and _can_merge_prose(prev, block):
            merged_text, transformations = _merge_prose_text(prev.text or "", block.text or "")
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
            continue
        if _are_adjacent_pages(prev, block) and _can_merge_code(prev, block):
            out[-1] = prev.model_copy(
                update={
                    "text": (prev.text or "").rstrip("\n") + "\n" + (block.text or "").lstrip("\n"),
                    "evidence": [*prev.evidence, *block.evidence],
                    "extra": {
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
                }
            )
            continue
        out.append(block)
    return [b.model_copy(update={"order": i}) for i, b in enumerate(out)]


def _can_merge_prose(prev: Block, block: Block) -> bool:
    if prev.type != BlockType.PARAGRAPH or block.type != BlockType.PARAGRAPH:
        return False
    a = (prev.text or "").rstrip()
    b = (block.text or "").lstrip()
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
    if prev.type != BlockType.NATIVE_CODE or block.type != BlockType.NATIVE_CODE:
        return False
    if (prev.language or "") != (block.language or ""):
        return False
    a = (prev.text or "").rstrip()
    b = (block.text or "").lstrip()
    if not a or not b:
        return False
    if re.search(r"[\{\(\[:]\s*$", a):
        return True
    if b.startswith((" ", "\t", ".", ")", "]", "}")):
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


def _looks_like_page_number(text: str) -> bool:
    return bool(re.fullmatch(r"(page\s*)?\d{1,4}", text.strip(), re.IGNORECASE))


def _looks_codeish(text: str) -> bool:
    return bool(
        re.search(
            r"(--\w+|https?://|/[A-Za-z0-9_.\-/]+|[A-Za-z_][A-Za-z0-9_]*\(|[0-9a-f]{16,})",
            text,
        )
    )


def _write_removed_records(document_dir: Path, removed: list[dict[str, Any]]) -> None:
    path = document_dir / "reconstruction_removed.jsonl"
    text = "".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in removed)
    atomic_write_text(path, text)
