"""OCR backend interface and registry.

The backend interface is intentionally minimal so that PaddleOCR-VL can be
swapped for a remote service, a mock, or a future model version without
changing the IR or the CLI.

TASK_15 changes:

- ``auto`` now prefers PaddleOCR-VL (full pipeline, then element mode)
  over RapidOCR. RapidOCR is auxiliary only — it is never selected as
  the primary recognizer when PaddleOCR-VL is available.
- ``get_backend`` accepts ``require_exact_backend=True`` to forbid
  silent fallback. When set, a request for ``paddleocr-vl`` that
  cannot be honored raises :class:`BackendIdentityError` instead of
  falling through to ``rapid``.
- New backend names: ``paddleocr-vl`` (full official pipeline) and
  ``paddleocr-vl-element`` (HF transformers element mode). The legacy
  aliases ``paddle`` / ``paddleocr_vl`` still work and route to the
  full pipeline.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@dataclass
class OcrRegion:
    """A single recognized text region with bounding box and confidence."""

    bbox: list[float]  # [x0, y0, x1, y1] in image pixel coordinates
    text: str
    confidence: float


@dataclass
class OcrResult:
    """Raw OCR output for one image, before any post-processing."""

    raw_text: str
    regions: list[OcrRegion] = field(default_factory=list)
    backend: str = "unknown"
    backend_version: str = ""
    model_confidence: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)
    # Metadata added in TASK_08: provenance for real-backend runs.
    # `metadata` is additive; existing callers that ignore it still work.
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def joined_text(self) -> str:
        """Concatenated region text in reading order; falls back to raw_text."""
        if self.regions:
            return "\n".join(r.text for r in self.regions if r.text)
        return self.raw_text


@runtime_checkable
class OcrBackend(Protocol):
    """OCR backend protocol. Implementations must be safe to call sequentially."""

    name: str
    version: str

    def recognize(self, image_bytes: bytes) -> OcrResult:  # pragma: no cover - protocol
        ...


class BackendIdentityError(RuntimeError):
    """Raised when the resolved backend does not match the requested one.

    This is the TASK_15 mechanism for forbidding silent fallback: when
    the user asks for ``paddleocr-vl`` and PaddleOCR-VL is not
    available, ``get_backend(..., require_exact_backend=True)`` raises
    this instead of returning RapidOCR.
    """


# Module-level singleton lock and instance. We use a single global instance to
# honor the MacBook constraint of "one model instance per process, one
# inference at a time".
_INSTANCE_LOCK = threading.Lock()
_INSTANCE: OcrBackend | None = None
_INFERENCE_LOCK = threading.Lock()


# Canonical backend probe order for ``auto``. PaddleOCR-VL is preferred;
# RapidOCR is auxiliary only; MLX (paligemma) is the last resort.
# ``mock`` is never selected by ``auto``.
_AUTO_PROBE_ORDER: tuple[str, ...] = (
    "paddleocr-vl",          # full official pipeline (PaddlePaddle)
    "paddleocr-vl-element",  # HF transformers element mode (works on MPS)
    "rapid",                 # RapidOCR (auxiliary only under `auto`)
    "mlx",                   # MLX-VLM paligemma (last resort)
)


def get_backend(
    name: str | None = None,
    *,
    require_exact_backend: bool = False,
    **kwargs: Any,
) -> OcrBackend:
    """Return the named backend, instantiating lazily.

    Parameters
    ----------
    name:
        Backend name. ``None`` or ``"auto"`` resolves via
        :func:`_resolve_auto`. Supported explicit names: ``mock``,
        ``rapid``, ``paddleocr-vl`` (aliases ``paddle``,
        ``paddleocr_vl``), ``paddleocr-vl-element``, ``mlx``.
    require_exact_backend:
        When ``True``, the resolved backend must match the requested
        name exactly. If ``auto`` is requested, the resolved backend
        must be one of the PaddleOCR-VL backends (otherwise
        :class:`BackendIdentityError`). If a specific name is
        requested and cannot be honored (e.g. ``paddleocr-vl`` when
        PaddleOCR is not installed), raises
        :class:`BackendIdentityError` instead of falling through.
        Default ``False`` preserves the legacy forgiving behavior for
        callers that have not opted in.
    """
    global _INSTANCE
    requested_name = name
    if name is None or name == "auto":
        resolved = _resolve_auto()
        if require_exact_backend and not _is_paddleocr_vl(resolved):
            raise BackendIdentityError(
                f"auto resolved to {resolved!r}, which is not PaddleOCR-VL. "
                "Install PaddleOCR-VL (paddleocr + paddlepaddle, or "
                "transformers + torch) to use auto under "
                "require_exact_backend=True. RapidOCR is auxiliary only "
                "and is never selected as the primary recognizer under "
                "this contract."
            )
        name = resolved
    else:
        # Normalize aliases.
        canonical = _canonical_name(name)
        if canonical is None:
            raise ValueError(
                f"unknown OCR backend: {name!r}. "
                "Supported: mock, rapid, paddleocr-vl, "
                "paddleocr-vl-element, mlx, auto."
            )
        if require_exact_backend:
            # The requested backend must be loadable. We probe without
            # instantiating; if the probe fails, raise.
            if not _probe_backend(canonical):
                raise BackendIdentityError(
                    f"backend {canonical!r} is not available in this "
                    "environment and require_exact_backend=True forbids "
                    "silent fallback. Install the missing dependencies."
                )
        name = canonical

    with _INSTANCE_LOCK:
        if _INSTANCE is None or getattr(_INSTANCE, "name", None) != name:
            _INSTANCE = _instantiate(name, **kwargs)
        return _INSTANCE


def reset_backend() -> None:
    """Reset the cached backend. Used by tests."""
    global _INSTANCE
    with _INSTANCE_LOCK:
        _INSTANCE = None


def acquire_inference_lock() -> threading.Lock:
    """Return the global inference lock. Always held while OCR is running."""
    return _INFERENCE_LOCK


def available_backends() -> list[str]:
    """Return the list of real OCR backends that can be loaded in this process.

    Order: paddleocr-vl, paddleocr-vl-element, rapid, mlx. ``mock`` is
    excluded — it is not a real backend.
    """
    out: list[str] = []
    for name in _AUTO_PROBE_ORDER:
        if _probe_backend(name):
            out.append(name)
    return out


def _probe_backend(name: str) -> bool:
    """Cheaply check whether a backend's dependencies import."""
    try:
        if name == "rapid":
            import rapidocr_onnxruntime  # type: ignore  # noqa: F401

            return True
        if name in ("paddleocr-vl", "paddle", "paddleocr_vl"):
            # Full official pipeline requires paddleocr (which pulls in
            # paddlepaddle). We do NOT silently accept the case where
            # paddleocr_vl imports but paddleocr does not — that was a
            # legacy silent-fallback path.
            import paddleocr  # type: ignore  # noqa: F401

            # Also require that the PaddleOCRVL class is exposed.
            return hasattr(paddleocr, "PaddleOCRVL")
        if name == "paddleocr-vl-element":
            # Element mode requires transformers + torch. We do not
            # require paddleocr here — element mode works on Apple
            # Silicon via MPS without PaddlePaddle. The README
            # documents ``AutoModelForCausalLM`` (not
            # AutoModelForImageTextToText, which does not recognize
            # the custom PaddleOCRVLConfig class).
            import torch  # type: ignore  # noqa: F401
            import transformers  # type: ignore  # noqa: F401
            from transformers import AutoModelForCausalLM  # type: ignore  # noqa: F401

            return True
        if name == "mlx":
            import mlx_vlm  # type: ignore  # noqa: F401

            return True
    except Exception:  # noqa: BLE001
        return False
    return False


def _resolve_auto() -> str:
    """Pick the first available real backend. Raise if none available."""
    avail = available_backends()
    if avail:
        return avail[0]
    raise RuntimeError(
        "no real OCR backend is available. Install one of: "
        "paddleocr + paddlepaddle (PaddleOCR-VL full pipeline), "
        "transformers + torch (PaddleOCR-VL element mode), "
        "rapidocr-onnxruntime (auxiliary only), or mlx-vlm. "
        "The `mock` backend is for deterministic tests only and is never "
        "selected by `auto`."
    )


def _canonical_name(name: str) -> str | None:
    """Normalize a backend name, resolving aliases. Returns None if unknown."""
    alias_map = {
        "mock": "mock",
        "rapid": "rapid",
        "paddleocr-vl": "paddleocr-vl",
        "paddleocr_vl": "paddleocr-vl",
        "paddle": "paddleocr-vl",
        "paddleocr-vl-element": "paddleocr-vl-element",
        "paddleocr_vl_element": "paddleocr-vl-element",
        "mlx": "mlx",
    }
    return alias_map.get(name)


def _is_paddleocr_vl(name: str) -> bool:
    """Return True if `name` is one of the PaddleOCR-VL backend names."""
    return name in ("paddleocr-vl", "paddleocr-vl-element")


def _instantiate(name: str, **kwargs: Any) -> OcrBackend:
    if name == "mock":
        from .mock import MockOcrBackend

        return MockOcrBackend(**kwargs)
    if name == "rapid":
        from .rapid import RapidOcrBackend

        return RapidOcrBackend(**kwargs)
    if name == "paddleocr-vl":
        from .paddleocr_vl import PaddleOcrVlBackend

        return PaddleOcrVlBackend(**kwargs)
    if name == "paddleocr-vl-element":
        from .paddleocr_vl_element import PaddleOcrVlElementBackend

        return PaddleOcrVlElementBackend(**kwargs)
    if name == "mlx":
        from .mlx_backend import MlxOcrBackend

        return MlxOcrBackend(**kwargs)
    raise ValueError(
        f"unknown OCR backend: {name!r}. "
        "Supported: mock, rapid, paddleocr-vl, paddleocr-vl-element, mlx, auto."
    )
