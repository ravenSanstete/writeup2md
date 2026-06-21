"""DOM-order block extraction shared by URL and local-HTML adapters.

This module is intentionally framework-light. It accepts a parsed BeautifulSoup
tree and emits ordered IR blocks. The URL adapter supplies the tree by rendering
the page with Playwright and dumping the article HTML; the local HTML adapter
parses the file directly.

TASK_10 enhancements:
- lazy-loaded image handling: capture `data-src`, `srcset`, `picture/source`,
  `currentSrc` (caller can supply `currentSrc` via DomImage);
- copy-button / clipboard payload extraction: `<button>` with `data-copy`,
  `data-clipboard-text`, or `onclick` clipboard APIs is preferred as the code
  text source over the rendered `<pre><code>` text;
- hidden accessible code extraction: `<code aria-hidden="true">` siblings,
  `<pre>` with `display:none` text — used as fallback text source;
- content-image vs decorative classification: based on size, alt, classes,
  position — decorative images get `visual_type=DECORATIVE`;
- DOM-code-over-OCR priority: when a `<pre><code>` block exists, no separate
  visual block is created for its screenshot. The native code IS the source
  of truth.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from bs4 import BeautifulSoup, NavigableString, Tag

from .coverage import apply_coverage_state
from .models import (
    Block,
    BlockType,
    EvidenceKind,
    EvidenceRef,
    VisualBlockState,
    VisualType,
    next_block_id,
)


# Tags that are universally non-content and should be skipped wholesale.
# Note: `button` is intentionally NOT skipped here — we need to inspect it
# for copy-button / clipboard payloads (TASK_10). The _should_skip() helper
# still skips `button` for text extraction, but _extract_copy_button_payload
# looks inside it first.
_SKIP_TAGS: frozenset[str] = frozenset(
    {"script", "style", "noscript", "iframe", "svg", "math", "form"}
)
_SKIP_TAGS_FOR_TEXT: frozenset[str] = frozenset({"button"})

# Tags that mark article containers in priority order.
_ARTICLE_SELECTORS: tuple[str, ...] = (
    "article",
    "main",
    "[role=main]",
    "#main",
    "#content",
    ".post-content",
    ".article-content",
    ".entry-content",
    ".markdown-body",
)

# Classes / alt-text patterns that mark an image as decorative.
_DECORATIVE_CLASS_HINTS: tuple[str, ...] = (
    "emoji",
    "icon",
    "avatar",
    "logo",
    "decoration",
    "deco",
    "sprite",
    "ad-",
    "ad_",
    "advert",
)
_DECORATIVE_ALT_HINTS: tuple[str, ...] = (
    "icon",
    "avatar",
    "logo",
    "decoration",
)

# Maximum inline-image dimension (CSS px) below which an image is considered
# decorative when it also lacks meaningful alt text.
_DECORATIVE_MAX_DIM = 32


@dataclass
class ExtractedAsset:
    """A captured asset (image bytes written to disk)."""

    asset_path: str  # relative to document_dir
    content_sha256: str
    extra: dict


@dataclass
class DomImage:
    """A content image encountered during DOM traversal.

    TASK_10: supports lazy-loaded images via `data_src`, `srcset`, `picture_src`,
    and `current_src` fields. The caller's image_handler should prefer
    `current_src` first, then `data_src`, then `src`.
    """

    src: str | None
    alt: str
    title: str | None
    selector: str
    asset: ExtractedAsset | None = None
    # Lazy-load fields.
    data_src: str | None = None
    srcset: str | None = None
    picture_src: str | None = None
    current_src: str | None = None
    # Size hints for decorative classification (CSS px from width/height attrs).
    width: int | None = None
    height: int | None = None
    classes: list[str] | None = None

    def best_url(self) -> str | None:
        """Return the best URL to use for downloading this image.

        Priority: current_src (Playwright-resolved) > data_src (lazy) >
        picture_src > srcset first entry > src.
        """
        for v in (self.current_src, self.data_src, self.picture_src, self.src):
            if v:
                return v
        if self.srcset:
            # Pick the first URL (before any space/descriptor).
            first = self.srcset.split(",", 1)[0].strip().split(" ", 1)[0].strip()
            if first:
                return first
        return None


def parse_html(html: str) -> BeautifulSoup:
    """Parse HTML using lxml if available, else stdlib parser."""
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:  # noqa: BLE001
        return BeautifulSoup(html, "html.parser")


def select_article_root(soup: BeautifulSoup) -> Tag:
    """Pick the best article container candidate."""
    body = soup.body or soup
    for sel in _ARTICLE_SELECTORS:
        node = body.select_one(sel)
        if node is not None:
            return node
    return body


def _selector_for(tag: Tag) -> str:
    """Best-effort CSS selector for a tag."""
    name = tag.name or "unknown"
    if tag.get("id"):
        return f"#{tag['id']}"
    classes = tag.get("class") or []
    if classes:
        cls = ".".join(classes)
        return f"{name}.{cls}"
    # Use nth-of-type relative to parent.
    parent = tag.parent
    if parent is None:
        return name
    siblings = [c for c in parent.children if isinstance(c, Tag) and c.name == tag.name]
    try:
        idx = siblings.index(tag) + 1
    except ValueError:
        return name
    return f"{name}:nth-of-type({idx})"


def _tag_text(tag: Tag) -> str:
    """Visible text of a tag, with whitespace normalized."""
    text = tag.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _heading_level(tag: Tag) -> int | None:
    m = re.fullmatch(r"h([1-6])", tag.name or "")
    return int(m.group(1)) if m else None


def _detect_code_language(tag: Tag, text: str) -> str | None:
    """Best-effort language detection from class hints and content."""
    classes: list[str] = []
    for c in (tag.get("class") or []):
        classes.extend(c.split())
    for cl in classes:
        lc = cl.lower()
        for prefix in ("language-", "lang-", "highlight-"):
            if lc.startswith(prefix):
                lang = lc[len(prefix):]
                if lang:
                    return lang
        if lc in {
            "python", "py", "bash", "shell", "sh", "javascript", "js",
            "typescript", "ts", "c", "cpp", "c++", "go", "rust", "java",
            "ruby", "php", "sql", "json", "yaml", "toml", "ini", "xml",
            "html", "css", "http", "diff",
        }:
            return lc
    # Heuristic on content.
    if re.search(r"^\s*(GET|POST|PUT|DELETE|PATCH|HEAD) [^ ]+ HTTP/\d", text, re.MULTILINE):
        return "http"
    if re.search(r"^\s*[@+\\-][^\n]*\n", text):
        return "diff"
    if re.search(r"\bdef\s+\w+\s*\(", text) or "import " in text.split("\n")[0]:
        return "python"
    if text.startswith("$ ") or text.startswith("> ") or re.search(r"^\s*\$\s", text, re.MULTILINE):
        return "bash"
    return None


def _should_skip(tag: Tag) -> bool:
    if tag.name in _SKIP_TAGS or tag.name in _SKIP_TAGS_FOR_TEXT:
        return True
    classes = " ".join(tag.get("class") or []).lower()
    if "advertisement" in classes or "ad-slot" in classes:
        return True
    return False


def _iter_content_children(root: Tag) -> Iterable[Tag]:
    """Yield direct child tags of root that are content-bearing.

    If a child is a generic container (<div>) that wraps a single content
    element (e.g. <pre>), we yield the wrapped element instead so block
    classification works. This handles common patterns like:
        <div class="code-container"><button>Copy</button><pre>...</pre></div>
    """
    for child in root.children:
        if isinstance(child, NavigableString):
            continue
        if not isinstance(child, Tag):
            continue
        if _should_skip(child):
            continue
        if child.name == "div":
            # Find content-bearing descendants (pre, table, ul, ol, blockquote,
            # figure, img, h1-h6, p). If the div wraps exactly one such element
            # (plus optional buttons / spans), yield the wrapped element.
            content_descendants = child.find_all(
                ["pre", "table", "ul", "ol", "blockquote", "figure", "h1", "h2", "h3", "h4", "h5", "h6"]
            )
            if len(content_descendants) == 1:
                yield content_descendants[0]
                continue
            # If the div has no block-level descendant but has a <p>, yield the
            # first <p> to keep paragraph handling working.
            ps = child.find_all("p", recursive=True)
            if len(ps) == 1 and not content_descendants:
                yield ps[0]
                continue
            # Otherwise yield the div itself and let paragraph fallback handle it.
        yield child


def _classify_block_type(tag: Tag) -> BlockType:
    name = tag.name or ""
    if re.fullmatch(r"h[1-6]", name):
        return BlockType.HEADING
    if name in {"p"}:
        return BlockType.PARAGRAPH
    if name in {"pre"}:
        return BlockType.NATIVE_CODE
    if name in {"ul", "ol"}:
        return BlockType.LIST
    if name in {"blockquote"}:
        return BlockType.QUOTE
    if name in {"table"}:
        return BlockType.TABLE
    if name in {"hr"}:
        return BlockType.HORIZONTAL_RULE
    if name in {"figure", "img", "picture"}:
        return BlockType.VISUAL
    return BlockType.PARAGRAPH


def _list_items(tag: Tag) -> list[str]:
    items: list[str] = []
    for li in tag.find_all("li", recursive=False):
        items.append(_tag_text(li))
    return items


def _table_rows(tag: Tag) -> list[list[str]]:
    rows: list[list[str]] = []
    for tr in tag.find_all("tr"):
        cells = [
            _tag_text(c) if isinstance(c, Tag) else str(c)
            for c in tr.find_all(["td", "th"])
        ]
        if cells:
            rows.append(cells)
    return rows


def _extract_inline_images(tag: Tag) -> list[Tag]:
    """Return all <img> descendants of a tag."""
    return tag.find_all("img")


def _parse_srcset_first(srcset: str | None) -> str | None:
    """Return the first URL in a srcset attribute."""
    if not srcset:
        return None
    first = srcset.split(",", 1)[0].strip().split(" ", 1)[0].strip()
    return first or None


def _collect_images_in_subtree(tag: Tag, base_selector: str) -> list[DomImage]:
    out: list[DomImage] = []
    for img in _extract_inline_images(tag):
        src = img.get("src")
        data_src = img.get("data-src") or img.get("data-original") or img.get("data-lazy-src")
        srcset = img.get("srcset") or img.get("data-srcset")
        alt = (img.get("alt") or "").strip()
        title = img.get("title")
        # Picture/source handling: look for a <source> sibling if img is inside <picture>.
        picture_src: str | None = None
        parent = img.parent
        if parent is not None and getattr(parent, "name", None) == "picture":
            for source in parent.find_all("source"):
                s_srcset = source.get("srcset") or source.get("data-srcset")
                if s_srcset:
                    picture_src = _parse_srcset_first(s_srcset)
                    if picture_src:
                        break
        # CSS width / height from attributes.
        try:
            w = int(img.get("width") or 0) or None
        except (TypeError, ValueError):
            w = None
        try:
            h = int(img.get("height") or 0) or None
        except (TypeError, ValueError):
            h = None
        classes = []
        for c in (img.get("class") or []):
            classes.extend(c.split())
        out.append(
            DomImage(
                src=src,
                alt=alt,
                title=title,
                selector=base_selector + " " + _selector_for(img),
                data_src=data_src,
                srcset=srcset,
                picture_src=picture_src,
                width=w,
                height=h,
                classes=classes or None,
            )
        )
    return out


def _is_decorative(img: DomImage) -> tuple[bool, str | None]:
    """Classify an image as decorative. Returns (is_decorative, reason).

    Heuristics (TASK_10):
    - class hints: 'emoji', 'icon', 'avatar', 'logo', 'decoration', 'sprite', 'ad-*'
    - alt hints: 'icon', 'avatar', 'logo', 'decoration'
    - tiny dimensions: width <= 32 and height <= 32 (icons/avatars)
    - empty alt AND tiny dimensions: decorative
    """
    cls_list = (img.classes or [])
    cls_lower = " ".join(cls_list).lower()
    for hint in _DECORATIVE_CLASS_HINTS:
        if hint in cls_lower:
            return True, f"class hint {hint!r}"
    alt_lower = (img.alt or "").lower()
    for hint in _DECORATIVE_ALT_HINTS:
        if hint in alt_lower:
            return True, f"alt hint {hint!r}"
    w = img.width or 0
    h = img.height or 0
    if 0 < w <= _DECORATIVE_MAX_DIM and 0 < h <= _DECORATIVE_MAX_DIM:
        return True, f"tiny dimensions {w}x{h}"
    return False, None


def _extract_copy_button_payload(parent: Tag) -> str | None:
    """Look inside a tag for a copy-button / clipboard payload.

    Recognizes:
    - <button data-copy="..."> with a literal payload;
    - <button data-clipboard-text="..."> (clipboard.js convention);
    - <button data-code="..."> (custom convention used by some sites);
    - <button> with onclick="navigator.clipboard.writeText('...')"

    Returns the payload text or None.
    """
    for btn in parent.find_all("button"):
        for attr in ("data-copy", "data-clipboard-text", "data-code"):
            v = btn.get(attr)
            if isinstance(v, str) and v.strip():
                return v
        onclick = btn.get("onclick")
        if isinstance(onclick, str) and "clipboard" in onclick.lower():
            # Best-effort extract a string literal.
            m = re.search(r"writeText\(\s*['\"](.+?)['\"]\s*\)", onclick)
            if m:
                return m.group(1)
            m = re.search(r"['\"](.+?)['\"]\s*\)\s*$", onclick)
            if m:
                return m.group(1)
    return None


def _extract_hidden_accessible_code(parent: Tag) -> str | None:
    """Extract text from hidden accessible code siblings.

    Recognizes:
    - <code aria-hidden="true"> siblings that contain plain text;
    - <pre style="display:none"> with text content;
    - <code class="sr-only"> or similar visually-hidden classes;
    - <textarea readonly> with code content (common in code playgrounds).
    """
    # aria-hidden="true" code sibling.
    for node in parent.find_all(["code", "pre", "textarea"]):
        aria = node.get("aria-hidden")
        if aria and str(aria).lower() == "true":
            t = _tag_text(node)
            if t:
                return t
        style = (node.get("style") or "").lower()
        if "display:none" in style.replace(" ", "") or "display:none" in style:
            t = _tag_text(node)
            if t:
                return t
        classes = " ".join(node.get("class") or []).lower()
        if "sr-only" in classes or "visually-hidden" in classes or "sr_only" in classes:
            t = _tag_text(node)
            if t:
                return t
        # <textarea readonly> with non-empty content.
        ro = node.get("readonly")
        if node.name == "textarea" and (ro is not None or "readonly" in classes):
            t = _tag_text(node)
            if t:
                return t
    return None


def _has_native_code_ancestor_or_self(tag: Tag) -> bool:
    """Return True if tag is or is inside a <pre>/<code> block.

    Used to skip creating a visual block for the screenshot of a code block
    that already has DOM text. Per TASK_10 DOM priority rule.
    """
    if tag.name in ("pre", "code"):
        return True
    for parent in tag.parents:
        if isinstance(parent, Tag) and parent.name in ("pre", "code"):
            return True
    return False


def _normalize_text_for_dedup_dom(text: str) -> str:
    """Lowercase and collapse whitespace for DOM-side dedup comparisons."""
    return " ".join(text.lower().split())


# Alt-text patterns that suggest an image is a screenshot of an adjacent code
# block. Used by DOM-code-over-OCR cross-block priority.
_CODE_SCREENSHOT_ALT_HINTS: tuple[str, ...] = (
    "screenshot of the",
    "screenshot of",
    "code screenshot",
    "code block above",
    "code block",
    "screenshot above",
    "screenshot of code",
    "image of code",
    "screenshot of the code",
    "screenshot of the above",
    "screenshot of the previous",
)


def _image_looks_like_code_screenshot(img: DomImage) -> bool:
    """Heuristic: does this image's alt text suggest it's a screenshot of an
    adjacent code block?

    Used by DOM-code-over-OCR cross-block priority: when we recently emitted a
    NATIVE_CODE block AND this image looks like a screenshot of that block,
    we skip creating a visual block for it (DOM text is the source of truth).
    """
    if not img.alt:
        return False
    alt_lower = img.alt.lower().strip()
    for hint in _CODE_SCREENSHOT_ALT_HINTS:
        if hint in alt_lower:
            return True
    # Also match: alt ending with "above" or starting with "screenshot"
    if alt_lower.endswith("above") or alt_lower.startswith("screenshot"):
        return True
    return False


def extract_blocks_from_html(
    html: str,
    *,
    source_kind: str,
    source_ref: str,
    canonical_source: str,
    image_handler=None,
) -> tuple[list[Block], list[DomImage]]:
    """Extract ordered IR blocks from an HTML string.

    `image_handler` is optional: when provided, it is called once per content
    image and must return an `ExtractedAsset` (or None to skip). Without a
    handler, images are still recorded as unresolved visual blocks so the
    pipeline can decide what to do.
    """
    soup = parse_html(html)
    root = select_article_root(soup)

    blocks: list[Block] = []
    images: list[DomImage] = []
    counter = [0]

    def make_block(**kwargs) -> Block:
        idx = counter[0]
        counter[0] += 1
        kwargs.setdefault("block_id", next_block_id(idx))
        kwargs.setdefault("order", idx)
        kwargs.setdefault("provenance_source_ref", canonical_source)
        return Block(**kwargs)

    # Top-level title: prefer <title> tag, but only emit a synthetic title
    # heading if the article root does NOT already begin with an <h1>.
    page_title: str | None = None
    if soup.title and soup.title.string:
        page_title = soup.title.string.strip()
    if not page_title:
        first_h1 = root.find("h1")
        if first_h1:
            page_title = _tag_text(first_h1)
    article_starts_with_h1 = (
        isinstance(root.find("h1"), Tag)
    )
    if page_title and not article_starts_with_h1:
        blocks.append(
            make_block(
                type=BlockType.HEADING,
                text=page_title,
                heading_level=1,
            )
        )

    # Track the most recent NATIVE_CODE block we emitted so we can detect
    # "screenshot of the previous code block" images and apply DOM priority.
    last_native_code_block: Block | None = None
    last_native_code_text_norm: str | None = None

    for child in _iter_content_children(root):
        btype = _classify_block_type(child)
        sel = _selector_for(child)

        # TASK_10 DOM-code-over-OCR priority: if this child is a <pre> block
        # with usable text, we record the NATIVE_CODE block and SKIP creating
        # any visual block for its inline images (the DOM text IS the source).
        is_native_code_block = btype == BlockType.NATIVE_CODE
        native_code_text_for_priority: str | None = None
        if is_native_code_block:
            code_tag = child.find("code")
            # TASK_10 source priority for URL: copy-button > raw source > hidden
            # accessible text > visible <pre> text.
            # Look for a copy-button payload in the child's parent (siblings of
            # the <pre>).
            text_source: str | None = None
            text_source_origin = "pre"
            parent = child.parent
            if parent is not None:
                copy_payload = _extract_copy_button_payload(parent)
                if copy_payload:
                    text_source = copy_payload
                    text_source_origin = "copy_button"
            if text_source is None:
                hidden = _extract_hidden_accessible_code(child)
                if hidden:
                    text_source = hidden
                    text_source_origin = "hidden_accessible"
            if text_source is None:
                visible_text = _tag_text(code_tag if code_tag else child)
                if visible_text:
                    text_source = visible_text
                    text_source_origin = "pre"
            native_code_text_for_priority = text_source

        # Inline images inside this child become separate visual blocks —
        # UNLESS the child is a native code block (DOM priority rule).
        subtree_images: list[DomImage] = []
        if is_native_code_block and native_code_text_for_priority:
            # Skip image extraction: the DOM text is the source of truth.
            # Still record the images in the images list (for provenance
            # auditing) but DO NOT emit visual blocks.
            for img in _collect_images_in_subtree(child, sel):
                images.append(img)
        else:
            subtree_images = _collect_images_in_subtree(child, sel)
            for img in subtree_images:
                best_url = img.best_url()
                # DOM-code-over-OCR priority (cross-block): if there is a
                # recent native code block AND this image's alt-text suggests
                # it's a screenshot of that code, skip creating a visual
                # block (the DOM text is the source of truth).
                if (
                    last_native_code_text_norm
                    and _image_looks_like_code_screenshot(img)
                ):
                    # Record the image for provenance but do not emit a
                    # duplicate visual block.
                    images.append(img)
                    continue

                asset: ExtractedAsset | None = None
                if image_handler is not None and best_url:
                    try:
                        asset = image_handler(img)
                    except Exception:  # noqa: BLE001
                        asset = None
                images.append(img)
                # Decorative classification.
                is_deco, deco_reason = _is_decorative(img)
                ev = EvidenceRef(
                    kind=EvidenceKind.DOM_ELEMENT,
                    url=canonical_source if source_kind == "url" else None,
                    selector=img.selector,
                    asset_path=asset.asset_path if asset else "",
                    content_sha256=asset.content_sha256 if asset else None,
                    extra={
                        "alt": img.alt,
                        "title": img.title or "",
                        "src": img.src or "",
                        "data_src": img.data_src or "",
                        "srcset": img.srcset or "",
                        "picture_src": img.picture_src or "",
                        "best_url": best_url or "",
                    },
                )
                if is_deco:
                    vblock = make_block(
                        type=BlockType.VISUAL,
                        visual_type=VisualType.DECORATIVE,
                        visual_state=VisualBlockState.IGNORED_DECORATIVE,
                        evidence=[ev],
                        extra={
                            "alt": img.alt,
                            "title": img.title or "",
                            "src": img.src or "",
                            "decorative_reason": deco_reason,
                        },
                    )
                    apply_coverage_state(
                        vblock, "decorative_with_reason", deco_reason or "decorative"
                    )
                    blocks.append(vblock)
                else:
                    vblock = make_block(
                        type=BlockType.VISUAL,
                        visual_type=VisualType.UNKNOWN,
                        visual_state=VisualBlockState.REVIEW_REQUIRED,
                        evidence=[ev],
                        extra={
                            "alt": img.alt,
                            "title": img.title or "",
                            "src": img.src or "",
                        },
                    )
                    apply_coverage_state(
                        vblock, "review_required", "DOM image; not yet transcribed"
                    )
                    blocks.append(vblock)

        if btype == BlockType.HEADING:
            blocks.append(
                make_block(
                    type=BlockType.HEADING,
                    text=_tag_text(child),
                    heading_level=_heading_level(child) or 2,
                )
            )
            last_native_code_block = None
            last_native_code_text_norm = None
        elif btype == BlockType.PARAGRAPH:
            text = _tag_text(child)
            if text:
                blocks.append(make_block(type=BlockType.PARAGRAPH, text=text))
            # Keep last_native_code_* — code screenshot may appear after a
            # paragraph like "Here is a screenshot:".
        elif btype == BlockType.NATIVE_CODE:
            text = native_code_text_for_priority
            if text:
                block = make_block(
                    type=BlockType.NATIVE_CODE,
                    text=text,
                    language=_detect_code_language(code_tag or child, text),
                    extra={"text_source": text_source_origin} if text_source_origin != "pre" else {},
                )
                blocks.append(block)
                last_native_code_block = block
                last_native_code_text_norm = _normalize_text_for_dedup_dom(text)
            else:
                last_native_code_block = None
                last_native_code_text_norm = None
        elif btype == BlockType.LIST:
            items = _list_items(child)
            if items:
                blocks.append(make_block(type=BlockType.LIST, list_items=items))
            last_native_code_block = None
            last_native_code_text_norm = None
        elif btype == BlockType.QUOTE:
            text = _tag_text(child)
            if text:
                blocks.append(make_block(type=BlockType.QUOTE, text=text))
            last_native_code_block = None
            last_native_code_text_norm = None
        elif btype == BlockType.TABLE:
            rows = _table_rows(child)
            if rows:
                blocks.append(make_block(type=BlockType.TABLE, table_rows=rows))
            last_native_code_block = None
            last_native_code_text_norm = None
        elif btype == BlockType.HORIZONTAL_RULE:
            blocks.append(make_block(type=BlockType.HORIZONTAL_RULE))
        elif btype == BlockType.VISUAL:
            # Already handled by subtree_images above.
            pass
        else:
            text = _tag_text(child)
            if text:
                blocks.append(make_block(type=BlockType.PARAGRAPH, text=text))

    return blocks, images


def write_asset(document_dir: Path, subdir: str, content: bytes, *, ext: str = ".png") -> ExtractedAsset:
    """Write an asset to evidence/<subdir>/<sha>.<ext> and return a descriptor."""
    sha = hashlib.sha256(content).hexdigest()
    rel_dir = Path("evidence") / subdir
    out_dir = document_dir / rel_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    asset_name = f"{sha[:16]}{ext}"
    out_path = out_dir / asset_name
    if not out_path.exists():
        out_path.write_bytes(content)
    return ExtractedAsset(
        asset_path=str(rel_dir / asset_name),
        content_sha256=sha,
        extra={"bytes": len(content)},
    )
