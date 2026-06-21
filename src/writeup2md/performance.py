"""Round 4 lightweight performance instrumentation."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PerformanceRecorder:
    """Append long-document runtime metrics without owning pipeline logic."""

    report_jsonl: Path = Path("reports/FULL_BOOK_PERFORMANCE.jsonl")
    report_md: Path = Path("reports/FULL_BOOK_PERFORMANCE.md")
    started_at: float = field(default_factory=time.monotonic)
    ocr_calls: int = 0
    ocr_latency_total_s: float = 0.0
    model_loads: int = 0
    retries: int = 0
    peak_rss_bytes: int = 0

    def record_page(
        self,
        *,
        document_dir: Path,
        current_page: int,
        pages_total: int,
        active_page_buffers: int,
        page_ocr_calls: int,
        page_ocr_latency_s: float,
        retries: int = 0,
    ) -> dict[str, Any]:
        self.ocr_calls += page_ocr_calls
        self.ocr_latency_total_s += page_ocr_latency_s
        self.retries += retries
        rss = _rss_bytes()
        self.peak_rss_bytes = max(self.peak_rss_bytes, rss)
        elapsed = max(0.001, time.monotonic() - self.started_at)
        pages_per_minute = current_page / elapsed * 60.0
        remaining = max(0, pages_total - current_page)
        estimated_remaining_s = remaining / max(0.001, pages_per_minute / 60.0)
        record = {
            "document_dir": str(document_dir),
            "elapsed_s": elapsed,
            "current_page": current_page,
            "pages_total": pages_total,
            "pages_per_minute": pages_per_minute,
            "estimated_remaining_s": estimated_remaining_s,
            "process_rss_bytes": rss,
            "peak_rss_bytes": self.peak_rss_bytes,
            "ocr_calls": self.ocr_calls,
            "ocr_latency_total_s": self.ocr_latency_total_s,
            "ocr_latency_last_page_s": page_ocr_latency_s,
            "active_page_buffers": active_page_buffers,
            "temporary_disk_bytes": _safe_dir_size(document_dir / "pages"),
            "evidence_disk_bytes": _safe_dir_size(document_dir / "evidence")
            + _safe_dir_size(document_dir / "pages"),
            "model_loads": self.model_loads,
            "retries": self.retries,
        }
        _append_jsonl(self.report_jsonl, record)
        self._write_markdown_summary(record)
        return record

    def _write_markdown_summary(self, latest: dict[str, Any]) -> None:
        self.report_md.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# Full Book Performance",
            "",
            f"- document_dir: {latest['document_dir']}",
            f"- current_page: {latest['current_page']} / {latest['pages_total']}",
            f"- elapsed_s: {latest['elapsed_s']:.2f}",
            f"- pages_per_minute: {latest['pages_per_minute']:.2f}",
            f"- estimated_remaining_s: {latest['estimated_remaining_s']:.2f}",
            f"- process_rss_bytes: {latest['process_rss_bytes']}",
            f"- peak_rss_bytes: {latest['peak_rss_bytes']}",
            f"- ocr_calls: {latest['ocr_calls']}",
            f"- ocr_latency_total_s: {latest['ocr_latency_total_s']:.2f}",
            f"- active_page_buffers: {latest['active_page_buffers']}",
            f"- temporary_disk_bytes: {latest['temporary_disk_bytes']}",
            f"- evidence_disk_bytes: {latest['evidence_disk_bytes']}",
            f"- model_loads: {latest['model_loads']}",
            f"- retries: {latest['retries']}",
        ]
        self.report_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
        f.flush()


def _rss_bytes() -> int:
    try:
        import psutil  # type: ignore

        return int(psutil.Process(os.getpid()).memory_info().rss)
    except Exception:  # noqa: BLE001
        try:
            import resource

            rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
            # macOS reports bytes; Linux reports KiB. The exact platform is
            # less important than monotonic leak detection, but normalize Linux.
            if rss < 10_000_000:
                rss *= 1024
            return rss
        except Exception:  # noqa: BLE001
            return 0


def _safe_dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    try:
        for child in path.rglob("*"):
            if child.is_file():
                total += child.stat().st_size
    except Exception:  # noqa: BLE001
        return total
    return total
