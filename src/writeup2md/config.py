"""Typed configuration models and built-in profiles for writeup2md."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any
import os

import yaml
from pydantic import BaseModel, Field, field_validator


class Profile(str, Enum):
    """Built-in execution profiles."""

    FAST = "fast"
    DEFAULT = "default"
    STRICT = "strict"
    MACBOOK = "macbook"


class Device(str, Enum):
    AUTO = "auto"
    CPU = "cpu"
    GPU = "gpu"


class PipelineConfig(BaseModel):
    profile: Profile = Profile.MACBOOK
    retain_raw_evidence: bool = True
    deterministic: bool = True
    resume: bool = True
    workers: int = 1
    max_workers: int = 2

    @field_validator("workers")
    @classmethod
    def _workers_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("workers must be >= 1")
        return v

    @field_validator("max_workers")
    @classmethod
    def _max_workers_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("max_workers must be >= 1")
        return v


class PdfConfig(BaseModel):
    initial_render_dpi: int = 300
    retry_render_dpi: int = 450
    page_batch_size: int = 1
    prefer_native_text: bool = True
    extract_embedded_images: bool = True
    retain_rendered_pages_in_memory: bool = False


class WebConfig(BaseModel):
    browser: str = "chromium"
    browser_instances: int = 1
    active_pages: int = 1
    auto_scroll: bool = True
    wait_for_lazy_images: bool = True
    prefer_dom_code: bool = True
    close_page_after_source: bool = True


class OcrConfig(BaseModel):
    backend: str = "auto"
    model: str = "PaddlePaddle/PaddleOCR-VL"
    device: Device = Device.AUTO
    model_instances: int = 1
    max_concurrent_inference: int = 1
    heavy_queue_capacity: int = 2
    auto_repair: bool = False

    @field_validator("model_instances")
    @classmethod
    def _single_instance(cls, v: int) -> int:
        if v != 1:
            raise ValueError("only one OCR model instance is supported on the MacBook profile")
        return v

    @field_validator("max_concurrent_inference")
    @classmethod
    def _single_inference(cls, v: int) -> int:
        if v != 1:
            raise ValueError("OCR inference must be serialized (max_concurrent_inference=1)")
        return v


class MarkdownConfig(BaseModel):
    pure_text: bool = True
    allow_images: bool = False


class UiConfig(BaseModel):
    lazy_load_documents: bool = True
    lazy_load_evidence: bool = True
    index_page_size: int = 50
    preload_thumbnails: bool = False


class QualityConfig(BaseModel):
    unresolved_important_visual_policy: str = "review"
    accepted_requires_zero_unresolved_visuals: bool = True
    # TASK_18: document mode surfaces uncertain transcriptions in the
    # Markdown with a textual notice. strict mode routes them to
    # review_required and may reject the document.
    mode: str = "document"  # "document" | "strict"


class RuntimeConfig(BaseModel):
    """Round 4 long-document runtime controls."""

    page_prefetch: int = 2
    native_text_workers: int = 4
    image_decode_workers: int = 2
    normalization_workers: int = 2
    pdf_render_concurrency: int = 2
    ocr_model_instances: int = 1
    ocr_concurrency: int = 1
    page_write_concurrency: int = 1
    heavy_queue_capacity: int = 4
    performance_interval_pages: int = 1

    @field_validator("ocr_model_instances")
    @classmethod
    def _one_model_instance(cls, v: int) -> int:
        if v != 1:
            raise ValueError("PaddleOCR-VL model_instances must remain 1")
        return v

    @field_validator("ocr_concurrency")
    @classmethod
    def _one_ocr_inference(cls, v: int) -> int:
        if v != 1:
            raise ValueError("PaddleOCR-VL OCR concurrency must remain 1")
        return v


class GeneralVlmConfig(BaseModel):
    """Optional non-code visual understanding endpoint."""

    backend: str = "disabled"  # disabled | openai-compatible | mock | auto
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    max_calls_per_document: int = 20
    max_retries_per_visual: int = 1
    request_timeout_s: float = 60.0
    rate_limit_per_minute: int = 30
    token_budget: int | None = None

    @classmethod
    def from_env(cls) -> "GeneralVlmConfig":
        base_url = os.getenv("WRITEUP2MD_VLM_BASE_URL")
        api_key = os.getenv("WRITEUP2MD_VLM_API_KEY")
        model = os.getenv("WRITEUP2MD_VLM_MODEL")
        if base_url or api_key or model:
            return cls(
                backend="openai-compatible",
                base_url=base_url,
                api_key=api_key,
                model=model,
            )
        return cls()


class WriteupConfig(BaseModel):
    """Top-level configuration."""

    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    pdf: PdfConfig = Field(default_factory=PdfConfig)
    web: WebConfig = Field(default_factory=WebConfig)
    ocr: OcrConfig = Field(default_factory=OcrConfig)
    markdown: MarkdownConfig = Field(default_factory=MarkdownConfig)
    ui: UiConfig = Field(default_factory=UiConfig)
    quality: QualityConfig = Field(default_factory=QualityConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    general_vlm: GeneralVlmConfig = Field(default_factory=GeneralVlmConfig.from_env)

    def config_sha256(self) -> str:
        """Stable hash of the configuration for deterministic skipping."""
        import hashlib
        import json

        canonical = json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


def _macbook_overrides() -> dict[str, Any]:
    return {
        "pipeline": {
            "profile": Profile.MACBOOK,
            "retain_raw_evidence": True,
            "deterministic": True,
            "resume": True,
            "workers": 1,
            "max_workers": 2,
        },
        "pdf": {
            "initial_render_dpi": 300,
            "retry_render_dpi": 450,
            "page_batch_size": 1,
            "prefer_native_text": True,
            "extract_embedded_images": True,
            "retain_rendered_pages_in_memory": False,
        },
        "web": {
            "browser": "chromium",
            "browser_instances": 1,
            "active_pages": 1,
            "auto_scroll": True,
            "wait_for_lazy_images": True,
            "prefer_dom_code": True,
            "close_page_after_source": True,
        },
        "ocr": {
            "backend": "auto",
            "model": "PaddlePaddle/PaddleOCR-VL",
            "device": Device.AUTO,
            "model_instances": 1,
            "max_concurrent_inference": 1,
            "heavy_queue_capacity": 2,
            "auto_repair": False,
        },
        "markdown": {"pure_text": True, "allow_images": False},
        "ui": {
            "lazy_load_documents": True,
            "lazy_load_evidence": True,
            "index_page_size": 50,
            "preload_thumbnails": False,
        },
        "quality": {
            "unresolved_important_visual_policy": "review",
            "accepted_requires_zero_unresolved_visuals": True,
            "mode": "document",
        },
        "runtime": {
            "page_prefetch": 2,
            "native_text_workers": 4,
            "image_decode_workers": 2,
            "normalization_workers": 2,
            "pdf_render_concurrency": 2,
            "ocr_model_instances": 1,
            "ocr_concurrency": 1,
            "page_write_concurrency": 1,
            "heavy_queue_capacity": 4,
            "performance_interval_pages": 1,
        },
        "general_vlm": GeneralVlmConfig.from_env().model_dump(mode="json"),
    }


def _strict_overrides() -> dict[str, Any]:
    base = _macbook_overrides()
    base["pipeline"]["profile"] = Profile.STRICT
    base["pipeline"]["max_workers"] = 1
    base["quality"]["mode"] = "strict"
    return base


def _default_overrides() -> dict[str, Any]:
    base = _macbook_overrides()
    base["pipeline"]["profile"] = Profile.DEFAULT
    return base


def _fast_overrides() -> dict[str, Any]:
    base = _macbook_overrides()
    base["pipeline"]["profile"] = Profile.FAST
    base["pipeline"]["retain_raw_evidence"] = False
    return base


_PROFILE_FACTORIES: dict[Profile, Any] = {
    Profile.MACBOOK: _macbook_overrides,
    Profile.STRICT: _strict_overrides,
    Profile.DEFAULT: _default_overrides,
    Profile.FAST: _fast_overrides,
}


def build_config(profile: Profile | str | None = None) -> WriteupConfig:
    """Return a WriteupConfig for the given profile name."""
    if profile is None:
        profile = Profile.MACBOOK
    if isinstance(profile, str):
        profile = Profile(profile)
    return WriteupConfig.model_validate(_PROFILE_FACTORIES[profile]())


def enforce_macbook_limits(config: WriteupConfig) -> WriteupConfig:
    """Reject unsafe worker counts for the MacBook profile."""
    if config.pipeline.profile == Profile.MACBOOK:
        if config.pipeline.workers > config.pipeline.max_workers:
            raise ValueError(
                f"workers={config.pipeline.workers} exceeds MacBook maximum "
                f"of {config.pipeline.max_workers}"
            )
        if config.pipeline.workers > 2:
            raise ValueError("MacBook profile hard maximum is 2 workers")
    return config


def load_config_file(path: Path | str) -> WriteupConfig:
    """Load a YAML configuration file."""
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return WriteupConfig.model_validate(data)
