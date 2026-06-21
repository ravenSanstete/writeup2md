"""Environment and dependency diagnostics for `writeup2md doctor`."""

from __future__ import annotations

import importlib
import os
import platform
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    required: bool = True


@dataclass
class DoctorReport:
    checks: list[Check] = field(default_factory=list)

    @property
    def all_required_ok(self) -> bool:
        return all(c.ok for c in self.checks if c.required)

    def to_dict(self) -> dict:
        return {
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
            "checks": [
                {
                    "name": c.name,
                    "ok": c.ok,
                    "required": c.required,
                    "detail": c.detail,
                }
                for c in self.checks
            ],
        }


def _try_import(name: str) -> tuple[bool, str]:
    try:
        mod = importlib.import_module(name)
        version = getattr(mod, "__version__", "")
        return True, version
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def run_doctor(output_root: Path | str | None = None) -> DoctorReport:
    """Run all environment checks and return a report."""
    report = DoctorReport()

    # Python version
    py_ok = sys.version_info >= (3, 11)
    report.checks.append(
        Check(
            name="python",
            ok=py_ok,
            detail=sys.version.split()[0],
        )
    )

    # Core deps
    for name in ("typer", "rich", "pydantic", "yaml"):
        ok, detail = _try_import(name)
        report.checks.append(
            Check(name=f"package:{name}", ok=ok, detail=detail, required=True)
        )

    # Optional but expected deps
    for name in ("fitz", "playwright", "streamlit"):
        ok, detail = _try_import(name)
        report.checks.append(
            Check(name=f"package:{name}", ok=ok, detail=detail, required=False)
        )

    # Real OCR backend availability (auto-selects the first real backend).
    from .ocr.backend import available_backends

    avail = available_backends()
    auto_detail = ",".join(avail) if avail else "none"
    report.checks.append(
        Check(
            name="ocr_backend:auto",
            ok=bool(avail),
            detail=auto_detail,
            required=False,
        )
    )

    # PaddleOCR-VL full pipeline (lazy, optional). TASK_15.
    paddle_full_ok = False
    paddle_full_detail = "not installed (optional; full official pipeline)"
    try:
        import paddleocr  # type: ignore  # noqa: F401

        if hasattr(paddleocr, "PaddleOCRVL"):
            paddle_full_ok = True
            paddle_full_detail = getattr(paddleocr, "__version__", "installed")
        else:
            paddle_full_detail = (
                f"paddleocr {getattr(paddleocr, '__version__', '?')} installed "
                "but PaddleOCRVL class missing — need paddleocr>=3.0"
            )
    except Exception:
        pass
    report.checks.append(
        Check(
            name="paddleocr_vl:full",
            ok=paddle_full_ok,
            detail=paddle_full_detail,
            required=False,
        )
    )

    # PaddleOCR-VL element mode (transformers + torch). TASK_15.
    paddle_element_ok = False
    paddle_element_detail = "not installed (optional; HF transformers element mode)"
    try:
        import torch  # type: ignore  # noqa: F401
        from transformers import AutoModelForImageTextToText  # type: ignore  # noqa: F401

        paddle_element_ok = True
        from importlib.metadata import version as _v

        paddle_element_detail = (
            f"torch={_v('torch')} transformers={_v('transformers')}"
        )
    except Exception:
        pass
    report.checks.append(
        Check(
            name="paddleocr_vl:element",
            ok=paddle_element_ok,
            detail=paddle_element_detail,
            required=False,
        )
    )

    # HuggingFace Hub (required for identity verification in TASK_15).
    hf_ok = False
    hf_detail = "not installed"
    try:
        from importlib.metadata import version

        hf_ok = True
        hf_detail = version("huggingface_hub")
    except Exception:
        pass
    report.checks.append(
        Check(name="huggingface_hub", ok=hf_ok, detail=hf_detail, required=False)
    )

    # RapidOCR backend (auxiliary only under `auto` post-TASK_15).
    rapid_ok = False
    rapid_detail = "not installed"
    try:
        from importlib.metadata import version

        rapid_ok = True
        rapid_detail = version("rapidocr-onnxruntime")
    except Exception:
        pass
    report.checks.append(
        Check(name="rapidocr", ok=rapid_ok, detail=rapid_detail, required=False)
    )

    # Playwright browser availability (best effort, do not fail hard)
    pw_browser_ok = False
    pw_browser_detail = "unknown"
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            # If the chromium executable exists, we consider it installed.
            exe = p.chromium.executable_path
            pw_browser_ok = bool(exe) and Path(exe).exists()
            pw_browser_detail = exe or "not found"
    except Exception as e:  # noqa: BLE001
        pw_browser_detail = f"{type(e).__name__}: {e}"
    report.checks.append(
        Check(name="playwright:chromium", ok=pw_browser_ok, detail=pw_browser_detail, required=False)
    )

    # Output directory writability
    out = Path(output_root) if output_root else Path.cwd() / "outputs"
    try:
        out.mkdir(parents=True, exist_ok=True)
        test_file = out / ".writeup2md_doctor_probe"
        test_file.write_bytes(b"ok")
        test_file.unlink()
        out_ok = True
        out_detail = str(out)
    except Exception as e:  # noqa: BLE001
        out_ok = False
        out_detail = f"{type(e).__name__}: {e}"
    report.checks.append(
        Check(name="output_dir_writable", ok=out_ok, detail=out_detail, required=True)
    )

    # CPU count sanity
    report.checks.append(
        Check(
            name="cpu_count",
            ok=True,
            detail=str(os.cpu_count() or "unknown"),
            required=False,
        )
    )

    return report


def smoke_ocr(
    image_path: Path | str,
    *,
    output_path: Path | str | None = None,
    backend_name: str = "auto",
    require_exact_backend: bool = False,
) -> dict:
    """Load an OCR backend and run one inference on `image_path`.

    Parameters
    ----------
    image_path:
        Image to OCR.
    output_path:
        Optional path to write the metadata JSON to.
    backend_name:
        Backend to use. Defaults to ``"auto"`` which prefers
        PaddleOCR-VL. Use ``"paddleocr-vl"`` or
        ``"paddleocr-vl-element"`` to smoke-test a specific
        PaddleOCR-VL runtime.
    require_exact_backend:
        When ``True``, forbids silent fallback. If the requested
        backend is not available, raises :class:`BackendIdentityError`
        instead of falling through to RapidOCR. Default ``False``
        preserves the legacy forgiving behavior.

    Returns a metadata dict and (when ``output_path`` is set) writes
    it to disk. Raises ``RuntimeError`` when no real backend is
    available OR when the selected backend is ``mock`` (we never allow
    mock to satisfy a smoke test).
    """
    import json
    import time

    from .ocr.backend import (
        available_backends,
        get_backend,
        reset_backend,
        BackendIdentityError,
    )

    avail = available_backends()
    if not avail:
        raise RuntimeError(
            "no real OCR backend is available. Install one of: "
            "paddleocr + paddlepaddle (PaddleOCR-VL full pipeline), "
            "transformers + torch (PaddleOCR-VL element mode), "
            "rapidocr-onnxruntime (auxiliary), mlx-vlm."
        )

    reset_backend()
    try:
        backend = get_backend(
            backend_name,
            require_exact_backend=require_exact_backend,
        )
    except BackendIdentityError:
        raise

    if getattr(backend, "name", "") == "mock":
        raise RuntimeError(
            "smoke_ocr refused to use the mock backend. "
            "Install a real OCR backend (paddleocr, transformers+torch, "
            "rapidocr-onnxruntime, mlx-vlm)."
        )

    img_p = Path(image_path)
    if not img_p.is_file():
        raise FileNotFoundError(f"smoke-ocr image not found: {image_path}")
    image_bytes = img_p.read_bytes()

    t0 = time.perf_counter()
    result = backend.recognize(image_bytes)
    total_elapsed = time.perf_counter() - t0

    meta = result.metadata
    out: dict = {
        "backend": result.backend,
        "backend_version": result.backend_version,
        "is_mock": meta.get("is_mock", False),
        "input_image": str(img_p),
        "input_dimensions": meta.get("input_dimensions"),
        "model_name": meta.get("model_name"),
        "model_repo": meta.get("model_repo", ""),
        "model_revision": meta.get("model_revision", ""),
        "pipeline_version": meta.get("pipeline_version", ""),
        "full_pipeline": meta.get("full_pipeline", False),
        "device": meta.get("device"),
        "engine_version": meta.get("engine_version", {}),
        "load_duration_s": meta.get("load_duration_s", 0.0),
        "inference_duration_s": meta.get("inference_duration_s", 0.0),
        "total_elapsed_s": total_elapsed,
        "region_count": len(result.regions),
        "model_confidence": result.model_confidence,
        "raw_text": result.raw_text,
        "raw_output_path": meta.get("raw_output_path"),
        "fallback_used": meta.get("fallback_used", ""),
        "mock_used": meta.get("mock_used", False),
        "rapid_used_as_primary": meta.get("rapid_used_as_primary", False),
        "regions": [
            {"text": r.text, "confidence": r.confidence, "bbox": r.bbox}
            for r in result.regions
        ],
    }

    if output_path is not None:
        op = Path(output_path)
        op.parent.mkdir(parents=True, exist_ok=True)
        op.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        out["raw_output_path"] = str(op)

    return out
