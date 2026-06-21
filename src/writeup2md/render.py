"""Pure-text Markdown renderer for the unified IR."""

from __future__ import annotations

import re
import unicodedata

from .models import (
    Block,
    BlockType,
    Document,
    EnrichedVisual,
    VisualBlockState,
    VisualType,
)


# Patterns we must NEVER emit in the final Markdown.
_IMAGE_MARKDOWN_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_IMAGE_HTML_RE = re.compile(r"<\s*img\b[^>]*>", re.IGNORECASE)
_BASE64_DATA_IMAGE_RE = re.compile(r"data:image/[^;]+;base64", re.IGNORECASE)


def _normalize_text(text: str) -> str:
    """Safe normalization: NFC unicode + CRLF/CR to LF."""
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text


def _strip_editor_line_numbers(text: str) -> tuple[str, list[str]]:
    """Remove editor-style leading line numbers ONLY when clearly chrome.

    Conservative: require that EVERY non-empty line begins with digits followed
    by whitespace. If any non-empty line lacks that prefix, return the text
    unchanged. This prevents accidentally mangling real code.
    """
    lines = text.split("\n")
    non_empty = [ln for ln in lines if ln.strip()]
    if len(non_empty) < 2:
        return text, []
    # Pattern: optional leading spaces, digits, then 1+ spaces, then content.
    pat = re.compile(r"^(\s*)(\d+)(\s+)(.*)$")
    matched = 0
    for ln in non_empty:
        m = pat.match(ln)
        if not m:
            return text, []
        # Reject if the "number" is part of a larger token like 0x10 or 1.5
        # by checking the boundary before digits.
        before = m.group(1)
        if before and not before.isspace():
            return text, []
        matched += 1
    if matched != len(non_empty):
        return text, []
    new_lines: list[str] = []
    for ln in lines:
        if not ln.strip():
            new_lines.append(ln)
            continue
        m = pat.match(ln)
        assert m is not None
        # Preserve indentation that follows the number's trailing whitespace
        # by replacing "<spaces><num><spaces>" with a consistent indent of the
        # same width as the trailing whitespace run minus one. We instead
        # drop the number and the original separating whitespace, then re-add
        # a single space only if there was content following.
        rest = m.group(4)
        new_lines.append(rest)
    return "\n".join(new_lines), ["removed_editor_line_numbers"]


def render_block_markdown(block: Block, *, mode: str = "document") -> str:
    """Render a single block to Markdown text (no surrounding fences for non-code)."""
    if block.type == BlockType.HEADING:
        level = block.heading_level or 2
        level = max(1, min(6, level))
        title = (block.text or "").strip()
        return f"{'#' * level} {title}"

    if block.type == BlockType.PARAGRAPH:
        return _normalize_text(block.text or "")

    if block.type == BlockType.LIST:
        items = block.list_items or []
        return "\n".join(f"- {_normalize_text(it)}" for it in items)

    if block.type == BlockType.QUOTE:
        text = _normalize_text(block.text or "")
        return "\n".join(f"> {ln}" for ln in text.split("\n"))

    if block.type == BlockType.HORIZONTAL_RULE:
        return "---"

    if block.type == BlockType.TABLE:
        rows = block.table_rows or []
        if not rows:
            return ""
        lines = []
        header = rows[0]
        lines.append("| " + " | ".join(header) + " |")
        lines.append("| " + " | ".join("---" for _ in header) + " |")
        for r in rows[1:]:
            # pad or truncate to header width
            r_padded = list(r) + [""] * (len(header) - len(r))
            r_padded = r_padded[: len(header)]
            lines.append("| " + " | ".join(r_padded) + " |")
        return "\n".join(lines)

    if block.type == BlockType.NATIVE_CODE:
        lang = block.language or ""
        text = _normalize_text(block.text or "")
        return _render_code_fence(text, lang)

    if block.type == BlockType.VISUAL:
        return render_visual_block(block, mode=mode)

    return _normalize_text(block.text or "")


def render_visual_block(block: Block, *, mode: str = "document") -> str:
    """Render a visual block to Markdown.

    ``mode``:
      - ``"document"`` (default): surface uncertain transcriptions with a
        textual notice followed by the OCR'd text in a fenced block.
        Never silently omit content.
      - ``"strict"``: emit an HTML-comment marker for review_required
        blocks so the review UI can locate them. This is the dataset-
        generation mode.
    """
    enrichment = block.enrichment
    state = block.visual_state
    vtype = (block.visual_type or "unknown").value

    if state == VisualBlockState.IGNORED_DECORATIVE:
        # Decorative — emit nothing visible. The block is still in
        # document.json and diagnostics.json for provenance.
        return ""

    # Resolved states: render the transcription as a fenced block.
    if state in (VisualBlockState.RESOLVED_OCR, VisualBlockState.RESOLVED_STRUCTURED) and enrichment is not None:
        text = enrichment.selected_text or enrichment.raw_text
        text = _normalize_text(text)
        if not text.strip():
            return _render_unresolved_notice(block, vtype, mode, "OCR returned empty output")
        lang = enrichment.language or _fence_language(enrichment.visual_type)
        return _render_code_fence(text, lang)

    # review_required with non-empty text in document mode: surface
    # the transcription with a textual notice.
    if state == VisualBlockState.REVIEW_REQUIRED and enrichment is not None:
        text = enrichment.selected_text or enrichment.raw_text
        text = _normalize_text(text)
        if text.strip():
            if mode == "strict":
                # Dataset mode — keep the marker for the review UI.
                return f"<!-- writeup2md: [REVIEW REQUIRED] visual={vtype} block={block.block_id} -->\n"
            # Document mode — surface the transcription with a notice.
            notice = (
                f"> The source contains a {vtype} visual at this position whose "
                f"transcription is uncertain. A partial transcription follows:\n"
            )
            lang = enrichment.language or _fence_language(enrichment.visual_type)
            return notice + _render_code_fence(text, lang)
        # review_required with no text — emit a textual notice.
        return _render_unresolved_notice(block, vtype, mode, "OCR returned empty output")

    if state == VisualBlockState.FAILED:
        reason = ""
        if enrichment is not None and enrichment.transformations:
            reason = "; ".join(enrichment.transformations)
        return _render_unresolved_notice(block, vtype, mode, reason or "OCR failed")

    # state is None or enrichment is None — surface honestly.
    return _render_unresolved_notice(block, vtype, mode, "visual not enriched")


def _render_unresolved_notice(block: Block, vtype: str, mode: str, reason: str) -> str:
    """Render a textual notice for a visual that could not be transcribed.

    Never silent. Never an image link.
    """
    if mode == "strict":
        return f"<!-- writeup2md: [UNRESOLVED] visual={vtype} block={block.block_id} -->\n"
    return (
        f"> The source contains an unresolved {vtype} visual at this position "
        f"({reason}).\n"
    )


def _render_code_fence(text: str, lang: str) -> str:
    """Render a fenced code block, escaping inner triple backticks if needed."""
    text = text.rstrip("\n")
    # If the text itself contains ``` we need a longer fence. Pick the
    # smallest fence length that does not collide.
    fence = "```"
    while fence in text:
        fence += "`"
    if lang and fence == "```":
        return f"```{lang}\n{text}\n```"
    if lang:
        # Inner triple-backticks present — use a longer fence. Language
        # tags are still attached.
        return f"{fence}{lang}\n{text}\n{fence}"
    return f"{fence}\n{text}\n{fence}"


def _fence_language(vtype: VisualType) -> str:
    return {
        VisualType.CODE: "",
        VisualType.TERMINAL: "bash",
        VisualType.HTTP: "http",
        VisualType.DIFF: "diff",
        VisualType.CONFIGURATION: "",
        VisualType.LOG: "log",
        VisualType.STACK_TRACE: "log",
        VisualType.TABLE: "",
    }.get(vtype, "")


def render_markdown(document: Document, *, strip_images: bool = True, mode: str = "document") -> str:
    """Render the full document to a single Markdown string.

    By default, strip any image references as a safety net so the written
    file never contains images. Pass ``strip_images=False`` to inspect the
    raw render (used by quality gates to detect leaked image syntax).

    ``mode`` selects the visual-block rendering policy (see
    :func:`render_visual_block`). The default is ``"document"``.
    """
    parts: list[str] = []
    blocks = sorted(document.blocks, key=lambda b: b.order)
    for i, block in enumerate(blocks):
        rendered = render_block_markdown(block, mode=mode)
        if rendered == "":
            continue
        parts.append(rendered)
        if i != len(blocks) - 1:
            parts.append("")  # blank line between blocks
    md = "\n\n".join(parts)
    md = md.strip() + "\n"
    if strip_images:
        md = strip_image_references(md)
    return md


def strip_image_references(markdown: str) -> str:
    """Remove any Markdown image syntax, HTML img tags and Base64 data URIs."""
    out = _IMAGE_MARKDOWN_RE.sub("", markdown)
    out = _IMAGE_HTML_RE.sub("", out)
    out = _BASE64_DATA_IMAGE_RE.sub("[removed-base64-image]", out)
    return out


def count_image_references(markdown: str) -> int:
    """Count image references (markdown, HTML img, base64) in raw markdown text."""
    n = 0
    n += len(_IMAGE_MARKDOWN_RE.findall(markdown))
    n += len(_IMAGE_HTML_RE.findall(markdown))
    n += len(_BASE64_DATA_IMAGE_RE.findall(markdown))
    return n


__all__ = [
    "render_block_markdown",
    "render_visual_block",
    "render_markdown",
    "strip_image_references",
    "count_image_references",
    "_strip_editor_line_numbers",
]
