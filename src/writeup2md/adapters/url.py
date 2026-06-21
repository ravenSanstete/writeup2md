"""URL adapter — Playwright capture + DOM extraction.

Resource behavior:
- one Chromium browser per process;
- one active page per source, closed in a `finally` block;
- downloads original image bytes (no large in-memory screenshots retained);
- stores rendered HTML and metadata before visual enrichment so OCR can
  resume without re-opening the page;
- no crawling of unrelated links.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

from ..config import WriteupConfig
from ..dom_extract import (
    DomImage,
    ExtractedAsset,
    extract_blocks_from_html,
    write_asset,
)
from ..models import (
    Document,
    DocumentStatus,
    Manifest,
    SourceRecord,
    SourceType,
    canonicalize_source,
    compute_document_id,
    content_sha256_text,
    now_iso_utc,
)
from ..persist import finalize_document
from ..pipeline import ConversionResult


def _build_manifest_and_source(
    *,
    source: str,
    html: str,
    config: WriteupConfig,
    explicit_id: str | None = None,
    tags: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> tuple[Manifest, SourceRecord, str]:
    canonical = canonicalize_source(source)
    content_sha = content_sha256_text(html)
    config_sha = config.config_sha256()
    doc_id = compute_document_id(
        source=source,
        canonical_source=canonical,
        content_sha256=content_sha,
        config_sha256=config_sha,
        explicit_id=explicit_id,
    )
    captured = now_iso_utc()
    manifest = Manifest(
        document_id=doc_id,
        source=source,
        source_type=SourceType.URL,
        canonical_source=canonical,
        captured_at=captured,
        content_sha256=content_sha,
        config_sha256=config_sha,
        status=DocumentStatus.REVIEW,  # provisional; finalize_document recomputes
        tags=tags or [],
        profile=config.pipeline.profile.value,
        extra=extra or {},
    )
    src = SourceRecord(
        source_type=SourceType.URL,
        source=source,
        canonical_source=canonical,
        captured_at=captured,
        content_sha256=content_sha,
        extra={"content_bytes": len(html)},
    )
    return manifest, src, doc_id


def _make_image_handler(document_dir: Path, page, base_url: str):
    """Return a closure that downloads image bytes via Playwright.

    TASK_10: uses `img.best_url()` to prefer current_src (Playwright-resolved),
    then data_src (lazy), then picture_src, then srcset first, then src.
    """

    def handler(img: DomImage) -> ExtractedAsset | None:
        url = img.best_url()
        if not url:
            return None
        # Resolve to absolute URL.
        if url.startswith("//"):
            url = "https:" + url
        elif url.startswith("/"):
            # derive origin from base_url
            from urllib.parse import urlsplit

            parts = urlsplit(base_url)
            url = f"{parts.scheme}://{parts.netloc}{url}"
        elif not url.startswith(("http://", "https://")):
            # relative path
            url = base_url.rstrip("/") + "/" + url.lstrip("/")
        # Skip data: URIs — they would write massive inline blobs and aren't
        # useful as evidence.
        if url.startswith("data:"):
            return None
        try:
            resp = page.request.get(url, timeout=15000)
            if resp.ok:
                body = resp.body()
                ext = ".png"
                low = url.lower().split("?", 1)[0]
                if low.endswith((".jpg", ".jpeg")):
                    ext = ".jpg"
                elif low.endswith(".gif"):
                    ext = ".gif"
                elif low.endswith(".webp"):
                    ext = ".webp"
                elif low.endswith(".svg"):
                    ext = ".svg"
                return write_asset(document_dir, "elements", body, ext=ext)
        except Exception:  # noqa: BLE001
            return None
        return None

    return handler


def convert_url(
    *,
    source: str,
    output_root: Path,
    config: WriteupConfig,
    force: bool = False,
    keep_evidence: bool = True,
    device: str | None = None,
    explicit_id: str | None = None,
    tags: list[str] | None = None,
    extra: dict[str, Any] | None = None,
    html_override: str | None = None,
    base_url_override: str | None = None,
) -> ConversionResult:
    """Convert a URL to a document directory."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "playwright is required for URL conversion; "
            "install with: pip install playwright && playwright install chromium"
        ) from e

    if html_override is not None:
        html = html_override
        base_url = base_url_override or source
        # Skip Playwright entirely — used by tests for stable local-HTML fixtures.
        return _convert_html_string(
            html=html,
            base_url=base_url,
            source=source,
            output_root=output_root,
            config=config,
            force=force,
            keep_evidence=keep_evidence,
            explicit_id=explicit_id,
            tags=tags,
            extra=extra,
        )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            resp = page.goto(source, wait_until="domcontentloaded", timeout=30000)
            # Conservative lazy-load handling: scroll once, wait briefly.
            if config.web.auto_scroll:
                try:
                    page.evaluate(
                        "() => window.scrollTo(0, document.body.scrollHeight / 2)"
                    )
                except Exception:  # noqa: BLE001
                    pass
            if config.web.wait_for_lazy_images:
                try:
                    page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:  # noqa: BLE001
                    pass
            html = page.content()
            base_url = source
            # TASK_12: capture HTTP freshness signals (ETag, Last-Modified)
            # for resume freshness checks. These are stored in the manifest's
            # `extra` field so the batch runner can compare on the next run.
            etag: str | None = None
            last_modified: str | None = None
            try:
                if resp is not None:
                    headers = resp.headers if hasattr(resp, "headers") else {}
                    etag = headers.get("etag") or headers.get("ETag")
                    last_modified = headers.get("last-modified") or headers.get("Last-Modified")
            except Exception:  # noqa: BLE001
                pass
            extra_with_freshness = dict(extra or {})
            if etag or last_modified:
                extra_with_freshness["http_freshness"] = {
                    "etag": etag,
                    "last_modified": last_modified,
                }
            # Persist raw HTML immediately so resume is possible without re-rendering.
            manifest, src_record, doc_id = _build_manifest_and_source(
                source=source,
                html=html,
                config=config,
                explicit_id=explicit_id,
                tags=tags,
                extra=extra_with_freshness,
            )
            document_dir = output_root / doc_id
            document_dir.mkdir(parents=True, exist_ok=True)
            (document_dir / "raw").mkdir(parents=True, exist_ok=True)
            (document_dir / "raw" / "page.html").write_text(html, encoding="utf-8")
            (document_dir / "raw" / "metadata.json").write_text(
                __import__("json").dumps(
                    {
                        "url": source,
                        "final_url": page.url,
                        "status": resp.status if resp else None,
                        "captured_at": src_record.captured_at,
                        "title": page.title() if hasattr(page, "title") else None,
                        "etag": etag,
                        "last_modified": last_modified,
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            handler = _make_image_handler(document_dir, page, base_url)
            blocks, _images = extract_blocks_from_html(
                html=html,
                source_kind="url",
                source_ref=source,
                canonical_source=src_record.canonical_source,
                image_handler=handler,
            )

            doc = finalize_document(
                document_dir=document_dir,
                manifest=manifest,
                source=src_record,
                blocks=blocks,
                config=config,
                raw_assets=None,
                warnings=[],
                errors=[],
                force=force,
                keep_evidence=keep_evidence,
            )
            return ConversionResult(
                document_id=doc_id,
                document_dir=document_dir,
                status=doc.manifest.status,
                document=doc,
            )
        finally:
            try:
                page.close()
            except Exception:  # noqa: BLE001
                pass
            browser.close()


def _convert_html_string(
    *,
    html: str,
    base_url: str,
    source: str,
    output_root: Path,
    config: WriteupConfig,
    force: bool,
    keep_evidence: bool,
    explicit_id: str | None,
    tags: list[str] | None,
    extra: dict[str, Any] | None,
) -> ConversionResult:
    """Convert a pre-fetched HTML string (no Playwright)."""
    manifest, src_record, doc_id = _build_manifest_and_source(
        source=source,
        html=html,
        config=config,
        explicit_id=explicit_id,
        tags=tags,
        extra=extra or {"base_url": base_url},
    )
    document_dir = output_root / doc_id
    document_dir.mkdir(parents=True, exist_ok=True)
    (document_dir / "raw").mkdir(parents=True, exist_ok=True)
    (document_dir / "raw" / "page.html").write_text(html, encoding="utf-8")

    # TASK_20: human-readable directory name (<slug>-<short_hash>).
    # We rename the directory from the opaque doc_id to the slug-based
    # name. The full document_id is preserved in manifest.json.
    from ..slugify import human_readable_dir_name, update_index_file

    content_sha = content_sha256_text(html)
    dir_name = human_readable_dir_name(source, "url", content_sha)
    new_dir = output_root / dir_name
    if new_dir != document_dir and not new_dir.exists():
        try:
            document_dir.rename(new_dir)
            document_dir = new_dir
        except OSError:
            pass  # fall back to opaque hash
    update_index_file(output_root, dir_name, doc_id, source)

    blocks, _images = extract_blocks_from_html(
        html=html,
        source_kind="url",
        source_ref=source,
        canonical_source=src_record.canonical_source,
        image_handler=None,
    )

    doc = finalize_document(
        document_dir=document_dir,
        manifest=manifest,
        source=src_record,
        blocks=blocks,
        config=config,
        raw_assets={"page.html": html.encode("utf-8")},
        warnings=[],
        errors=[],
        force=force,
        keep_evidence=keep_evidence,
    )
    return ConversionResult(
        document_id=doc_id,
        document_dir=document_dir,
        status=doc.manifest.status,
        document=doc,
    )
