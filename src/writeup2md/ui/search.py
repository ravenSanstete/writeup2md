"""Full-text search across documents in a result root.

Resource behavior:
- builds an in-memory inverted index of (document_id -> token list) from each
  document's `document.md` and `document.json` blocks.text / enrichment.selected_text;
- index is cached via `@st.cache_data` keyed by the result-root signature
  (same approach as `index.py`);
- search returns matching document_ids ranked by simple TF scoring (no BM25
  needed at this scale);
- no external index files; rebuilt on cache miss only.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .index import index_signature


_TOKEN_RE = re.compile(r"[A-Za-z0-9_\-]+")


def _tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokenization. Skips CJK characters as whole runs."""
    if not text:
        return []
    # Split CJK runs on whitespace boundaries — we keep them as-is so that
    # CJK substrings can be matched literally (case where the regex below
    # would yield nothing useful).
    tokens: list[str] = []
    for chunk in text.split():
        toks = _TOKEN_RE.findall(chunk.lower())
        if not toks:
            # chunk is non-ASCII (e.g. CJK) — keep the whole chunk as one token.
            tokens.append(chunk.lower())
        else:
            tokens.extend(toks)
    return tokens


@dataclass
class SearchDoc:
    document_id: str
    document_dir: str
    title: str
    tokens: list[str] = field(default_factory=list)


@dataclass
class SearchResult:
    document_id: str
    document_dir: str
    title: str
    score: float


def _extract_search_text(document_dir: Path) -> tuple[str, str]:
    """Return (title, full_text) for indexing."""
    parts: list[str] = []
    title = document_dir.name
    md_path = document_dir / "document.md"
    if md_path.is_file():
        try:
            md_text = md_path.read_text(encoding="utf-8")
            parts.append(md_text)
            for line in md_text.splitlines():
                s = line.strip()
                if s.startswith("# "):
                    title = s[2:].strip()[:200]
                    break
                if s and not s.startswith("```"):
                    title = s[:200]
                    break
        except Exception:  # noqa: BLE001
            pass
    doc_path = document_dir / "document.json"
    if doc_path.is_file():
        try:
            doc = json.loads(doc_path.read_text(encoding="utf-8"))
            for b in doc.get("blocks", []):
                t = b.get("text")
                if t:
                    parts.append(t)
                enrich = b.get("enrichment") or {}
                if enrich.get("selected_text"):
                    parts.append(enrich["selected_text"])
                if enrich.get("raw_text"):
                    parts.append(enrich["raw_text"])
        except Exception:  # noqa: BLE001
            pass
    manifest_path = document_dir / "manifest.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            parts.append(manifest.get("source", ""))
            parts.append(manifest.get("canonical_source", ""))
            parts.append(manifest.get("document_id", ""))
        except Exception:  # noqa: BLE001
            pass
    return title, "\n".join(parts)


def build_search_index(result_root: Path) -> list[SearchDoc]:
    """Build a list of SearchDoc entries, one per document in result_root."""
    entries: list[SearchDoc] = []
    if not result_root.is_dir():
        return entries
    for child in sorted(result_root.iterdir()):
        if not child.is_dir():
            continue
        if child.name in {"accepted", "review", "rejected", "failed"}:
            continue
        if not (child / "manifest.json").is_file():
            continue
        title, text = _extract_search_text(child)
        entries.append(
            SearchDoc(
                document_id=child.name,
                document_dir=str(child),
                title=title,
                tokens=_tokenize(text),
            )
        )
    return entries


def search_documents(
    index: list[SearchDoc], query: str, limit: int = 100
) -> list[SearchResult]:
    """Return matching documents ranked by simple TF score.

    Query is tokenized the same way as the index. Documents matching any
    token are returned; score is the sum of per-token frequencies. If the
    query contains no tokens (e.g. only whitespace), returns an empty list.
    """
    q_tokens = _tokenize(query)
    if not q_tokens:
        return []
    # Also support quoted-phrase search: if the query is wrapped in quotes,
    # match the literal substring (case-insensitive) in the original text.
    # We do this by re-reading each candidate's text once.
    phrase: str | None = None
    stripped = query.strip()
    if len(stripped) >= 2 and stripped[0] == '"' and stripped[-1] == '"':
        phrase = stripped[1:-1].lower()

    results: list[SearchResult] = []
    for doc in index:
        if phrase:
            # Need to re-read text for phrase match. Tokens alone won't
            # preserve adjacency, so we fall back to file re-read.
            text = _extract_search_text(Path(doc.document_dir))[1].lower()
            if phrase not in text:
                continue
            score = float(text.count(phrase))
        else:
            score = 0.0
            for qt in q_tokens:
                score += doc.tokens.count(qt)
            if score == 0.0:
                continue
        results.append(
            SearchResult(
                document_id=doc.document_id,
                document_dir=doc.document_dir,
                title=doc.title,
                score=score,
            )
        )
    results.sort(key=lambda r: (-r.score, r.document_id))
    return results[:limit]


def search_index_signature(result_root: Path) -> tuple:
    """Cache signature — reuses index.py's mtime-based signature."""
    return index_signature(result_root)


def cached_search_index(result_root: Path) -> list[dict[str, Any]]:
    """Build and return the search index as plain dicts (Streamlit-cacheable)."""
    return [
        {
            "document_id": d.document_id,
            "document_dir": d.document_dir,
            "title": d.title,
            "tokens": d.tokens,
        }
        for d in build_search_index(result_root)
    ]
