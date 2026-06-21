from __future__ import annotations

import json
from pathlib import Path

from writeup2md.performance import PerformanceRecorder


def test_performance_recorder_writes_jsonl_and_markdown(tmp_path: Path) -> None:
    recorder = PerformanceRecorder(
        report_jsonl=tmp_path / "perf.jsonl",
        report_md=tmp_path / "perf.md",
    )
    doc_dir = tmp_path / "doc"
    (doc_dir / "pages" / "000001").mkdir(parents=True)
    (doc_dir / "pages" / "000001" / "page.md").write_text("hello", encoding="utf-8")

    record = recorder.record_page(
        document_dir=doc_dir,
        current_page=1,
        pages_total=2,
        active_page_buffers=1,
        page_ocr_calls=0,
        page_ocr_latency_s=0.0,
    )

    assert record["current_page"] == 1
    assert record["pages_total"] == 2
    assert record["active_page_buffers"] == 1
    lines = (tmp_path / "perf.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["current_page"] == 1
    assert "Full Book Performance" in (tmp_path / "perf.md").read_text(encoding="utf-8")
