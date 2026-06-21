"""Prepare a real-source corpus for TASK_14 Round 2 release validation.

This script creates trimmed excerpts (first N pages) of the test_samples
PDFs, plus a curated URL manifest. The goal is to exercise the real
writeup2md pipeline on real content without violating the MacBook
resource budget (no full-book processing, no large-corpus benchmark).

Usage:
    python reports/ROUND_2_CORPUS/prepare_corpus.py

Outputs:
    reports/ROUND_2_CORPUS/pdfs/<slug>.pdf    — 15-page excerpts
    reports/ROUND_2_CORPUS/sources.jsonl      — batch manifest
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import fitz  # PyMuPDF


REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_SAMPLES = REPO_ROOT / "test_samples"
OUT_DIR = REPO_ROOT / "reports" / "ROUND_2_CORPUS"
PDFS_DIR = OUT_DIR / "pdfs"
PAGES_PER_EXCERPT = 15


def _slugify(name: str) -> str:
    # Strip parenthetical metadata, drop extension, slugify.
    name = re.sub(r"\([^)]*\)", "", name)
    name = re.sub(r"\.pdf$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower()
    return name[:60] or "doc"


def prepare_pdf_excerpts() -> list[dict]:
    """Create 15-page excerpts of each test_samples PDF."""
    PDFS_DIR.mkdir(parents=True, exist_ok=True)
    sources: list[dict] = []
    for pdf_path in sorted(TEST_SAMPLES.glob("*.pdf")):
        slug = _slugify(pdf_path.name)
        out_path = PDFS_DIR / f"{slug}.pdf"
        try:
            src = fitz.open(str(pdf_path))
            n_pages = src.page_count
            excerpt_pages = min(PAGES_PER_EXCERPT, n_pages)
            new = fitz.open()
            new.insert_pdf(src, from_page=0, to_page=excerpt_pages - 1)
            new.save(str(out_path))
            new.close()
            src.close()
            print(f"  {slug}: {excerpt_pages}/{n_pages} pages → {out_path.name}")
            sources.append({
                "source": str(out_path),
                "explicit_id": f"pdf_{slug}",
                "tags": ["round2_release", "pdf", "excerpt"],
            })
        except Exception as e:  # noqa: BLE001
            print(f"  ERR {pdf_path.name}: {e}", file=sys.stderr)
    return sources


def prepare_html_sources() -> list[dict]:
    """Use existing HTML fixtures as URL-equivalent sources."""
    fixtures = REPO_ROOT / "tests" / "fixtures" / "html"
    sources: list[dict] = []
    for html_path in sorted(fixtures.glob("*.html")):
        sources.append({
            "source": str(html_path),
            "explicit_id": f"html_{html_path.stem}",
            "tags": ["round2_release", "html", "fixture"],
        })
    return sources


def prepare_capture_corpus() -> list[dict]:
    """Include the capture corpus PDFs (TASK_10) — they exercise specific edge cases."""
    cap_dir = REPO_ROOT / "tests" / "fixtures" / "capture"
    sources: list[dict] = []
    for pdf_path in sorted(cap_dir.glob("*.pdf")):
        sources.append({
            "source": str(pdf_path),
            "explicit_id": f"cap_{pdf_path.stem}",
            "tags": ["round2_release", "capture_corpus", "pdf"],
        })
    for html_path in sorted(cap_dir.glob("*.html")):
        sources.append({
            "source": str(html_path),
            "explicit_id": f"cap_{html_path.stem}",
            "tags": ["round2_release", "capture_corpus", "html"],
        })
    return sources


def prepare_url_sources() -> list[dict]:
    """Curated URL list. Some may be unreachable — recorded as failures."""
    urls = [
        # The user-specified thread — may 502.
        "https://bbs.kanxue.com/thread-290219.htm",
        # Real technical documentation pages (publicly readable).
        "https://docs.python.org/3/tutorial/inputoutput.html",
        "https://docs.python.org/3/library/subprocess.html",
        "https://requests.readthedocs.io/en/latest/user/quickstart/",
        "https://flask.palletsprojects.com/en/stable/quickstart/",
        "https://fastapi.tiangolo.com/tutorial/first-steps/",
        "https://docs.docker.com/get-started/",
        "https://kubernetes.io/docs/concepts/overview/",
        "https://owasp.org/www-community/attacks/xss/",
        "https://owasp.org/www-community/attacks/Command_Injection",
        "https://portswigger.net/web-security/sql-injection",
        "https://portswigger.net/web-security/xss",
    ]
    return [
        {
            "source": u,
            "explicit_id": f"url_{i:02d}",
            "tags": ["round2_release", "url"],
        }
        for i, u in enumerate(urls)
    ]


def main() -> int:
    print("Preparing PDF excerpts...")
    pdf_sources = prepare_pdf_excerpts()
    print(f"\nPreparing HTML fixtures...")
    html_sources = prepare_html_sources()
    print(f"\nPreparing capture corpus...")
    cap_sources = prepare_capture_corpus()
    print(f"\nPreparing URL list...")
    url_sources = prepare_url_sources()

    all_sources = pdf_sources + html_sources + cap_sources + url_sources
    manifest = OUT_DIR / "sources.jsonl"
    with manifest.open("w", encoding="utf-8") as f:
        for s in all_sources:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")

    print(f"\nCorpus manifest: {manifest}")
    print(f"  PDF excerpts:    {len(pdf_sources)}")
    print(f"  HTML fixtures:   {len(html_sources)}")
    print(f"  Capture corpus:  {len(cap_sources)}")
    print(f"  URL sources:     {len(url_sources)}")
    print(f"  TOTAL:           {len(all_sources)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
