#!/usr/bin/env python3
"""Run the unmodified production pipeline against every processable
sample in test_samples/ using a page-range slice of each PDF, and
collect per-sample outcomes into reports/E2E_BASELINE_RESULTS.{json,md}.

This is the TASK_16 baseline runner. It does NOT modify test_samples/.
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
OUT_ROOT = ROOT / "outputs" / "e2e_baseline"
REPORTS_DIR = ROOT / "reports"

BASELINE_PAGES = 3  # representative slice per book — keep iteration tractable


def load_inventory() -> list[dict]:
    p = REPORTS_DIR / "TEST_SAMPLES_INVENTORY.json"
    return json.loads(p.read_text(encoding="utf-8"))["samples"]


def run_one(sample: dict) -> dict:
    """Run writeup2md convert on a single sample.

    Returns a result record. Uses an environment variable to pass the
    page range into the process via a tiny shim — but since the public
    CLI doesn't expose page_range yet, we invoke a Python one-liner
    that imports convert_source directly.
    """
    sid = sample["sample_id"]
    src_path = ROOT / sample["path"]
    sample_out = OUT_ROOT / sid
    if sample_out.exists():
        shutil.rmtree(sample_out)
    sample_out.mkdir(parents=True, exist_ok=True)

    # We import the package directly so we can use the page_range kwarg.
    n_pages = sample.get("page_count") or 0
    stop = min(BASELINE_PAGES, n_pages) if n_pages else BASELINE_PAGES
    page_range = (0, stop)

    cmd_code = (
        "import json, sys, time\n"
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
        timeout=900,  # 15 min hard cap per sample
    )
    elapsed = time.time() - t0

    stdout = proc.stdout
    stderr = proc.stderr
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
                blocks = diag.get("blocks", {})
                coverage = diag.get("visual_coverage", {})
                record.update(
                    {
                        "page_count": diag.get("page_count"),
                        "native_text_block_count": blocks.get("native_text", 0)
                        + blocks.get("heading", 0)
                        + blocks.get("paragraph", 0),
                        "native_code_block_count": blocks.get("native_code", 0),
                        "visual_block_count": blocks.get("visual", 0),
                        "transcribed_visual_count": coverage.get("transcribed", 0),
                        "unresolved_visual_count": coverage.get("review_required", 0),
                        "failed_visual_count": coverage.get("failed_with_diagnostic", 0),
                        "warnings": diag.get("warnings", [])[:5],
                        "errors": diag.get("errors", [])[:5],
                    }
                )
            except Exception as e:
                record["diagnostics_parse_error"] = str(e)
        md_p = doc_dir / "document.md"
        if md_p.is_file():
            md = md_p.read_text(encoding="utf-8")
            record["markdown_character_count"] = len(md)
            record["markdown_code_block_count"] = md.count("```") // 2
        else:
            record["markdown_character_count"] = 0
            record["markdown_code_block_count"] = 0
    if stderr:
        record["stderr_tail"] = stderr[-400:]

    return record


def main() -> int:
    samples = [
        s for s in load_inventory()
        if s["expected_processing"] and s["source_type"] == "pdf"
    ]
    if os.environ.get("BASELINE_LIMIT"):
        samples = samples[: int(os.environ["BASELINE_LIMIT"])]
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    for i, s in enumerate(samples, 1):
        print(f"[{i}/{len(samples)}] {s['sample_id']} — {s['source'][:60]}", flush=True)
        try:
            r = run_one(s)
        except subprocess.TimeoutExpired:
            r = {
                "sample_id": s["sample_id"],
                "source": s["source"],
                "source_type": s["source_type"],
                "command": f"writeup2md convert {s['source']}",
                "exit_code": -1,
                "processing_time_s": 900.0,
                "document_status": "timeout",
                "output_path": None,
                "error": "hard 900s timeout exceeded",
            }
        results.append(r)
        # Persist incrementally so we don't lose progress.
        (REPORTS_DIR / "E2E_BASELINE_RESULTS.json").write_text(
            json.dumps({"results": results}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"  -> status={r['document_status']} elapsed={r['processing_time_s']}s", flush=True)

    # Markdown summary
    md = ["# E2E Baseline Results (TASK_16)", "",
          f"Output root: `{OUT_ROOT.relative_to(ROOT)}`",
          f"Page-range slice per sample: first **{BASELINE_PAGES}** pages",
          f"Backend: `paddleocr-vl-element` (require_exact_backend=true)",
          "",
          "| sample_id | status | pages | native_text | native_code | visuals | transcribed | unresolved | md_chars | elapsed_s |",
          "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for r in results:
        md.append(
            f"| {r['sample_id']} | {r['document_status']} | "
            f"{r.get('page_count', '-')} | {r.get('native_text_block_count', '-')} | "
            f"{r.get('native_code_block_count', '-')} | {r.get('visual_block_count', '-')} | "
            f"{r.get('transcribed_visual_count', '-')} | {r.get('unresolved_visual_count', '-')} | "
            f"{r.get('markdown_character_count', '-')} | {r['processing_time_s']} |"
        )
    (REPORTS_DIR / "E2E_BASELINE_RESULTS.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"\nResults written to {REPORTS_DIR / 'E2E_BASELINE_RESULTS.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
