"""Optional generic multimodal VLM interface for non-code visuals."""

from __future__ import annotations

import base64
import hashlib
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .config import GeneralVlmConfig
from .models import VisualType


@dataclass
class GeneralVlmResult:
    visual_type: str
    visible_text: list[str] = field(default_factory=list)
    summary: str = ""
    relationships: list[dict[str, Any]] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)
    raw_response_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class GeneralVlmBackend(Protocol):
    def analyze_visual(
        self,
        image_path: Path,
        visual_type: str,
        context_before: str,
        context_after: str,
    ) -> GeneralVlmResult:
        ...


class DisabledGeneralVlmBackend:
    name = "disabled"

    def analyze_visual(
        self,
        image_path: Path,
        visual_type: str,
        context_before: str,
        context_after: str,
    ) -> GeneralVlmResult:
        return GeneralVlmResult(
            visual_type=visual_type,
            uncertainties=["general VLM disabled"],
            metadata={"endpoint_type": "disabled", "status": "skipped"},
        )


class MockGeneralVlmBackend:
    name = "mock"

    def analyze_visual(
        self,
        image_path: Path,
        visual_type: str,
        context_before: str,
        context_after: str,
    ) -> GeneralVlmResult:
        digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
        return GeneralVlmResult(
            visual_type=visual_type,
            visible_text=[digest[:12]],
            summary=f"Mock analysis for {visual_type}.",
            uncertainties=[],
            metadata={
                "endpoint_type": "mock",
                "model": "mock",
                "request_hash": digest,
                "latency_s": 0.0,
                "status": "ok",
            },
        )


class OpenAICompatibleGeneralVlmBackend:
    name = "openai-compatible"

    def __init__(self, config: GeneralVlmConfig) -> None:
        if not config.base_url:
            raise ValueError("WRITEUP2MD_VLM_BASE_URL or config.general_vlm.base_url is required")
        if not config.model:
            raise ValueError("WRITEUP2MD_VLM_MODEL or config.general_vlm.model is required")
        self.config = config

    def analyze_visual(
        self,
        image_path: Path,
        visual_type: str,
        context_before: str,
        context_after: str,
    ) -> GeneralVlmResult:
        image_bytes = image_path.read_bytes()
        request_payload = _build_request_payload(
            image_bytes=image_bytes,
            model=self.config.model or "",
            visual_type=visual_type,
            context_before=context_before,
            context_after=context_after,
        )
        request_hash = hashlib.sha256(
            json.dumps(request_payload, sort_keys=True).encode("utf-8")
        ).hexdigest()
        started = time.monotonic()
        data = json.dumps(request_payload).encode("utf-8")
        req = urllib.request.Request(
            self.config.base_url or "",
            data=data,
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {self.config.api_key}"} if self.config.api_key else {}),
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.config.request_timeout_s) as resp:
                body = resp.read()
                status = getattr(resp, "status", 200)
        except urllib.error.HTTPError as e:
            body = e.read()
            status = e.code
        latency = time.monotonic() - started
        parsed = _parse_response(body)
        parsed.metadata.update(
            {
                "endpoint_type": "openai-compatible",
                "model": self.config.model,
                "request_hash": request_hash,
                "latency_s": latency,
                "status": status,
                "token_usage": parsed.metadata.get("token_usage"),
            }
        )
        return parsed


def get_general_vlm_backend(config: GeneralVlmConfig | None = None) -> GeneralVlmBackend:
    cfg = config or GeneralVlmConfig.from_env()
    backend = "disabled" if cfg.backend == "auto" and not cfg.base_url else cfg.backend
    if backend == "disabled":
        return DisabledGeneralVlmBackend()
    if backend == "mock":
        return MockGeneralVlmBackend()
    if backend == "openai-compatible":
        return OpenAICompatibleGeneralVlmBackend(cfg)
    raise ValueError(f"unknown general VLM backend: {cfg.backend!r}")


def should_route_to_general_vlm(visual_type: str | VisualType, *, decorative: bool = False) -> bool:
    if decorative:
        return False
    value = visual_type.value if isinstance(visual_type, VisualType) else str(visual_type)
    return value in {
        "diagram",
        "ui_screenshot",
        "unknown",
        "architecture_diagram",
        "flowchart",
        "chart",
        "multi_panel_instructional_image",
    }


def persist_general_vlm_artifacts(
    *,
    document_dir: Path,
    block_id: str,
    request_metadata: dict[str, Any],
    raw_response: dict[str, Any],
) -> tuple[Path, Path]:
    safe_metadata = {k: v for k, v in request_metadata.items() if "key" not in k.lower()}
    out_dir = document_dir / "evidence" / "general_vlm" / block_id
    out_dir.mkdir(parents=True, exist_ok=True)
    req_path = out_dir / "request_metadata.json"
    resp_path = out_dir / "response.json"
    req_path.write_text(json.dumps(safe_metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    resp_path.write_text(json.dumps(raw_response, indent=2, ensure_ascii=False), encoding="utf-8")
    return req_path, resp_path


def _build_request_payload(
    *,
    image_bytes: bytes,
    model: str,
    visual_type: str,
    context_before: str,
    context_after: str,
) -> dict[str, Any]:
    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    prompt = (
        "Analyze only visible content. Do not invent missing labels, code, or "
        "relationships. Return concise JSON with visual_type, visible_text, "
        "summary, relationships, and uncertainties. Preserve labels and "
        "directions exactly when visible."
    )
    return {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "text", "text": f"visual_type={visual_type}"},
                    {"type": "text", "text": f"context_before={context_before[-1000:]}"},
                    {"type": "text", "text": f"context_after={context_after[:1000]}"},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                    },
                ],
            }
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }


def _parse_response(body: bytes) -> GeneralVlmResult:
    try:
        obj = json.loads(body.decode("utf-8"))
    except Exception:  # noqa: BLE001
        return GeneralVlmResult(
            visual_type="unknown",
            uncertainties=["endpoint returned non-JSON response"],
            metadata={"status": "parse_error"},
        )
    token_usage = obj.get("usage")
    content = obj
    try:
        content_text = obj["choices"][0]["message"]["content"]
        content = json.loads(content_text)
    except Exception:  # noqa: BLE001
        pass
    if not isinstance(content, dict):
        content = {}
    return GeneralVlmResult(
        visual_type=str(content.get("visual_type", "unknown")),
        visible_text=list(content.get("visible_text", []) or []),
        summary=str(content.get("summary", "")),
        relationships=list(content.get("relationships", []) or []),
        uncertainties=list(content.get("uncertainties", []) or []),
        metadata={"token_usage": token_usage},
    )
