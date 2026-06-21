from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from writeup2md.config import GeneralVlmConfig
from writeup2md.general_vlm import (
    DisabledGeneralVlmBackend,
    get_general_vlm_backend,
    persist_general_vlm_artifacts,
    should_route_to_general_vlm,
)


def test_disabled_general_vlm_returns_skipped(tmp_path: Path) -> None:
    image = tmp_path / "image.png"
    image.write_bytes(b"png")
    backend = DisabledGeneralVlmBackend()

    result = backend.analyze_visual(image, "diagram", "", "")

    assert result.metadata["endpoint_type"] == "disabled"
    assert result.uncertainties == ["general VLM disabled"]


def test_general_vlm_routing_policy() -> None:
    assert should_route_to_general_vlm("diagram")
    assert should_route_to_general_vlm("ui_screenshot")
    assert should_route_to_general_vlm("unknown")
    assert not should_route_to_general_vlm("code")
    assert not should_route_to_general_vlm("terminal")
    assert not should_route_to_general_vlm("diff")
    assert not should_route_to_general_vlm("diagram", decorative=True)


def test_mock_general_vlm_backend(tmp_path: Path) -> None:
    image = tmp_path / "image.png"
    image.write_bytes(b"abc")
    backend = get_general_vlm_backend(GeneralVlmConfig(backend="mock"))

    result = backend.analyze_visual(image, "diagram", "", "")

    assert result.metadata["endpoint_type"] == "mock"
    assert result.summary == "Mock analysis for diagram."
    assert result.visible_text


def test_openai_compatible_mock_endpoint(tmp_path: Path) -> None:
    server = _MockVlmServer()
    server.start()
    try:
        image = tmp_path / "image.png"
        image.write_bytes(b"abc")
        backend = get_general_vlm_backend(
            GeneralVlmConfig(
                backend="openai-compatible",
                base_url=server.url,
                api_key="secret-key",
                model="mock-vlm",
            )
        )

        result = backend.analyze_visual(image, "diagram", "before", "after")

        assert result.visual_type == "architecture_diagram"
        assert result.visible_text == ["web", "db"]
        assert result.summary == "web connects to db"
        assert result.metadata["model"] == "mock-vlm"
        assert result.metadata["status"] == 200
        assert server.last_auth == "Bearer secret-key"
    finally:
        server.stop()


def test_persist_general_vlm_artifacts_redacts_keys(tmp_path: Path) -> None:
    req, resp = persist_general_vlm_artifacts(
        document_dir=tmp_path,
        block_id="b_1",
        request_metadata={"api_key": "secret", "model": "x"},
        raw_response={"ok": True},
    )

    assert "secret" not in req.read_text(encoding="utf-8")
    assert json.loads(resp.read_text(encoding="utf-8")) == {"ok": True}


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        self.server.last_auth = self.headers.get("Authorization")  # type: ignore[attr-defined]
        _ = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        body = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "visual_type": "architecture_diagram",
                                "visible_text": ["web", "db"],
                                "summary": "web connects to db",
                                "relationships": [
                                    {"from": "web", "to": "db", "label": "SQL"}
                                ],
                                "uncertainties": [],
                            }
                        )
                    }
                }
            ],
            "usage": {"total_tokens": 12},
        }
        data = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):  # noqa: A002
        return


class _MockVlmServer:
    def __init__(self) -> None:
        self.httpd = HTTPServer(("127.0.0.1", 0), _Handler)
        self.httpd.last_auth = None  # type: ignore[attr-defined]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self.httpd.server_address
        return f"http://{host}:{port}/v1/chat/completions"

    @property
    def last_auth(self) -> str | None:
        return self.httpd.last_auth  # type: ignore[attr-defined]

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.httpd.shutdown()
        self.thread.join(timeout=2)
        self.httpd.server_close()
