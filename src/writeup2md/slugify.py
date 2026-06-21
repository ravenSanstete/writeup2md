"""TASK_20 human-readable output directory names.

Converts source identifiers (PDF filenames, HTML filenames, URLs)
into filesystem-safe slugs. The output directory name is
``<slug>-<short_hash>`` where ``short_hash`` is the first 8 chars of
the content SHA-256. The full 16-char document ID is preserved in
``manifest.json.document_id`` for backward compatibility.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse


MAX_SLUG_LEN = 40
SHORT_HASH_LEN = 8


def slugify_source(source: str, source_type: str) -> str:
    """Build a filesystem-safe slug from a source identifier.

    For PDFs and HTML files, the slug is derived from the filename
    stem. For URLs, the slug combines the host and the last path
    segment. The result is lowercase, ASCII-only, words separated by
    single hyphens, truncated to ``MAX_SLUG_LEN`` chars.
    """
    if source_type.lower() in ("url", "web"):
        return _slugify_url(source)
    return _slugify_path(source)


def _slugify_path(source: str) -> str:
    """Slugify a local file path: use the filename stem."""
    p = Path(source)
    stem = p.stem
    return _normalize(stem)


def _slugify_url(source: str) -> str:
    """Slugify a URL: combine host and last path segment."""
    try:
        parsed = urlparse(source)
        host = parsed.netloc.replace("www.", "")
        last_segment = parsed.path.rstrip("/").rsplit("/", 1)[-1]
        if not last_segment:
            combined = host
        else:
            combined = f"{host}-{last_segment}"
    except Exception:  # noqa: BLE001
        combined = source
    return _normalize(combined)


def _normalize(text: str) -> str:
    """Lowercase, replace non-alphanumeric runs with single hyphens,
    collapse consecutive hyphens, strip leading/trailing hyphens,
    truncate to MAX_SLUG_LEN."""
    # Drop common file extensions.
    text = re.sub(r"\.(pdf|html?|htm)$", "", text, flags=re.IGNORECASE)
    # Replace any non-alphanumeric (ASCII) character with a space.
    text = re.sub(r"[^a-zA-Z0-9]+", " ", text)
    # Collapse whitespace, strip, lowercase.
    text = re.sub(r"\s+", " ", text).strip().lower()
    # Replace spaces with hyphens.
    slug = text.replace(" ", "-")
    # Truncate.
    if len(slug) > MAX_SLUG_LEN:
        slug = slug[:MAX_SLUG_LEN].rstrip("-")
    return slug or "doc"


def human_readable_dir_name(source: str, source_type: str, content_sha256: str) -> str:
    """Build the human-readable directory name: ``<slug>-<short_hash>``.

    ``content_sha256`` is the full SHA-256 hex string of the source
    content. The first ``SHORT_HASH_LEN`` chars are used.
    """
    slug = slugify_source(source, source_type)
    short = (content_sha256 or "")[:SHORT_HASH_LEN]
    if not short:
        short = "00000000"
    return f"{slug}-{short}"


def update_index_file(output_root: Path, dir_name: str, document_id: str, source: str) -> None:
    """Append/update a mapping in ``outputs/.index.json``.

    The index file maps human-readable dir names to full document IDs
    and source paths, for forensic lookup.
    """
    import json

    index_path = Path(output_root) / ".index.json"
    # Ensure parent exists (output_root may not have been created yet).
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index: dict[str, dict] = {}
    if index_path.is_file():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            index = {}
    index[dir_name] = {
        "document_id": document_id,
        "source": source,
    }
    index_path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
