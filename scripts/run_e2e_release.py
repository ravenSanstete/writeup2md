#!/usr/bin/env python3
"""Run the fixed pipeline against every PDF in test_samples/ using a
5-page slice per book, and collect per-sample outcomes into
reports/E2E_RELEASE_RESULTS.{json,md}.

This is the TASK_21 release runner. It does NOT modify test_samples/.
It uses paddleocr-vl-element with require_exact_backend=True — no
silent fallback to RapidOCR.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = ROOT / "test_samples"
OUT_ROOT = ROOT / "outputs" / "e2e_release"
REPORTS_DIR = ROOT / "reports"

RELEASE_PAGES = 5  # representative slice per book


def load_inventory() -> list[dict]:
    p = REPORTS_DIR / "TEST_SAMPLES_INVENTORY.json"
    return json.loads(p.read_text(encoding="utf-8"))["samples"]


def run_one(sample: dict) -> dict:
    """Run writeup2md convert on a single sample (5-page slice)."""
    sid = sample["sample_id"]
    src_path = ROOT / sample["path"]
    sample_out = OUT_ROOT / sid
    if sample_out.exists():
        shutil.rmtree(sample_out)
    sample_out.mkdir(parents=True, exist_ok=True)

    n_pages = sample.get("page_count") or 0
    stop = min(RELEASE_PAGES, n_pages) if n_pages else RELEASE_PAGES
    page_range = (0, stop)

    # Use the library API directly so we can pass page_range.
    cmd_code = (
        "import sys, time\n"
        "sys.path.insert(0, 'src')\n"
        "from writeup2md.config import Profile, build_config\n"
        "from writeup2md.pipeline import convert_source\n"
        "from pathlib import Path\n"
        f"src = {repr(str(src_path))}\n"
        f"out = Path({repr(str(sample_out))})\n"
        "cfg = build_config(Profile.MACBOOK)\n"
        "cfg.ocr.backend = 'paddleocr-vl-element'\n"
        "t0 = time.time()\n"
        "try:\n"
        f"    r = convert_source(source=src, output_root=out, config=cfg, force=True, page_range=(0, {stop}))\n"
        "    elapsed = time.time() - t0\n"
        "    print('STATUS=' + r.status.value)\n"
        "    print('DOC_DIR=' + str(r.document_dir))\n"
        "    print('ELAPSED=' + format(elapsed, '.2f'))\n"
        "except Exception as e:\n"
        "    elapsed = time.time() - t0\n"
        "    print('ERROR=' + repr(e))\n"
        "    print('ELAPSED=' + format(elapsed, '.2f'))\n"
    )

    t0 = time.time()
    proc = subprocess.run(
        [sys.executable, "-c", cmd_code],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=1800,  # 30 min hard cap per sample
    )
    elapsed = time.time() - t0

    stdout = proc.stdout
    status = "failed"
    doc_dir = None
    for ln in stdout.splitlines():
        if ln.startswith("STATUS="):
            status = ln.split("=", 1)[1]
        elif ln.startswith("DOC_DIR="):
            doc_dir = Path(ln.split("=", 1)[1])
        elif ln.startswith("ERROR="):
            status = "failed"

    record: dict = {
        "sample_id": sid,
        "source": sample["source"],
        "source_type": sample["source_type"],
        "page_range": [page_range[0], stop],
        "command": f"writeup2md convert {sample['source']} (page_range={page_range})",
        "exit_code": proc.returncode,
        "processing_time_s": round(elapsed, 2),
        "output_path": str(doc_dir) if doc_dir else None,
        "document_status": status,
    }

    # Parse diagnostics if present.
    if doc_dir and doc_dir.is_dir():
        diag_p = doc_dir / "diagnostics.json"
        if diag_p.is_file():
            try:
                diag = json.loads(diag_p.read_text(encoding="utf-8"))
                coverage = diag.get("visual_coverage", {})
                record.update({
                    "visual_block_count": coverage.get("total_visual_blocks", 0),
                    "transcribed_visual_count": coverage.get("by_state", {}).get("transcribed", 0),
                    "review_required_visual_count": coverage.get("by_state", {}).get("review_required", 0),
                    "decorative_visual_count": coverage.get("by_state", {}).get("decorative_with_reason", 0),
                    "failed_visual_count": coverage.get("by_state", {}).get("failed_with_diagnostic", 0),
                    "visuals_missing": coverage.get("missing", 0),
                })
            except Exception:  # noqa: BLE001
                pass
        # Markdown stats.
        md_p = doc_dir / "document.md"
        if md_p.is_file():
            md = md_p.read_text(encoding="utf-8")
            record["markdown_character_count"] = len(md)
            record["markdown_code_block_count"] = md.count("```") // 2
            record["html_comment_marker_count"] = md.count("<!-- writeup2md:")
            record["image_syntax_count"] = md.count("![")
        # Completeness invariants.
        comp_p = doc_dir / "completeness.json"
        if comp_p.is_file():
            try:
                comp = json.loads(comp_p.read_text(encoding="utf-8"))
                record["completeness_passed"] = comp.get("summary", {}).get("passed", 0)
                record["completeness_failed"] = comp.get("summary", {}).get("failed", 0)
                record["completeness_failed_invariants"] = comp.get("failed_invariants", [])
            except Exception:  # noqa: BLE001
                pass

    return record


def main() -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    samples = load_inventory()
    results = []
    for i, s in enumerate(samples, 1):
        print(f"[{i}/{len(samples)}] {s['sample_id']}...", flush=True)
        try:
            r = run_one(s)
        except subprocess.TimeoutExpired:
            r = {
                "sample_id": s["sample_id"],
                "source": s["source"],
                "document_status": "timeout",
                "processing_time_s": 1800,
                "error": "hard 1800s timeout exceeded",
            }
        results.append(r)
        print(f"  status={r.get('document_status')} elapsed={r.get('processing_time_s')}s", flush=True)

    # Write JSON.
    out_json = REPORTS_DIR / "E2E_RELEASE_RESULTS.json"
    out_json.write_text(
        json.dumps({"results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Write Markdown.
    out_md = REPORTS_DIR / "E2E_RELEASE_RESULTS.md"
    lines = [
        "# E2E Release Results (TASK_21)",
        "",
        f"Output root: `outputs/e2e_release`",
        f"Page-range slice per sample: first **{RELEASE_PAGES}** pages",
        "Backend: `paddleocr-vl-element` (require_exact_backend=true)",
        "",
        "| sample_id | status | pages | visuals | transcribed | review | decorative | md_chars | md_code_blocks | completeness | elapsed_s |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |",
    ]
    for r in results:
        sid = r["sample_id"]
        status = r.get("document_status", "unknown")
        pages = r.get("page_range", [0, 0])[1]
        visuals = r.get("visual_block_count", 0)
        transcribed = r.get("transcribed_visual_count", 0)
        review = r.get("review_required_visual_count", 0)
        decorative = r.get("decorative_visual_count", 0)
        md_chars = r.get("markdown_character_count", 0)
        md_code_blocks = r.get("markdown_code_block_count", 0)
        comp_passed = r.get("completeness_passed", "-")
        comp_failed = r.get("completeness_failed", "-")
        comp_str = f"{comp_passed}/{int(comp_passed) + int(comp_failed)}" if isinstance(comp_passed, int) else "-"
        elapsed = r.get("processing_time_s", 0)
        lines.append(
            f"| {sid} | {status} | {pages} | {visuals} | {transcribed} | {review} | {decorative} | {md_chars} | {md_code_blocks} | {comp_str} | {elapsed} |"
        )
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nWrote {out_json}")
    print(f"Wrote {out_md}")


if __name__ == "__main__":
    main()
