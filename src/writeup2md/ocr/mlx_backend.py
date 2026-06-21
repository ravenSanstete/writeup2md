"""MLX-based OCR backend (experimental).

mlx-vlm provides vision-language model inference on Apple Silicon via MLX.
This backend is EXPERIMENTAL: at the time of writing, mlx-vlm does not ship
a PaddleOCR-equivalent code-screenshot OCR model by default. We attempt to
load a small vision-language model that can transcribe images. If no usable
model is available locally, `recognize` raises a clear actionable error.

We NEVER fabricate OCR output. If the model cannot be loaded or cannot
produce text, the backend raises — it does not return fake text.
"""

from __future__ import annotations

import io
import threading
import time
from typing import Any

from .backend import acquire_inference_lock, OcrRegion, OcrResult
from .metadata import OcrBackendInfo


_INSTANCE_LOCK = threading.Lock()
_INSTANCE: Any = None
_INSTANCE_LOAD_DURATION: float = 0.0


def _engine_version_info() -> dict[str, str]:
    info: dict[str, str] = {}
    for pkg in ("mlx", "mlx-vlm", "mlx-vlm"):
        try:
            from importlib.metadata import version

            info[pkg.replace("-", "_")] = version(pkg)
        except Exception:  # noqa: BLE001
            pass
    try:
        import mlx  # type: ignore

        info["mlx"] = getattr(mlx, "__version__", "installed")
    except Exception:  # noqa: BLE001
        pass
    return info


class MlxOcrBackend:
    """mlx-vlm backed OCR. EXPERIMENTAL.

    Construction is cheap; the heavy model is loaded on first `recognize`.
    """

    name = "mlx"
    version = "mlx-vlm"

    def __init__(self, *, model_name: str | None = None, device: str = "auto", **kwargs: Any) -> None:
        # Default model is a small VLM that can transcribe images. If the user
        # has not downloaded one, the backend raises on first recognize.
        self._model_name = model_name or "mlx-community/paligemma-3b-mix-224-8bit"
        self._device = device
        self._load_lock = threading.Lock()
        self._model: Any = None
        self._processor: Any = None
        self._model_load_duration: float = 0.0

    def _ensure_model(self) -> None:
        global _INSTANCE
        if self._model is not None:
            return
        with _INSTANCE_LOCK:
            if _INSTANCE is not None:
                # Reuse the loaded model+processor pair.
                self._model, self._processor, self._model_load_duration = _INSTANCE
                return
            with self._load_lock:
                if _INSTANCE is not None:
                    self._model, self._processor, self._model_load_duration = _INSTANCE
                    return
                try:
                    from mlx_vlm import load, generate  # type: ignore  # noqa: F401
                    from mlx_vlm.prompt_utils import apply_chat_template  # type: ignore  # noqa: F401
                    from mlx_vlm.utils import load_config  # type: ignore  # noqa: F401
                except ImportError as e:
                    raise RuntimeError(
                        "mlx-vlm is not installed. Install with: pip install mlx-vlm"
                    ) from e
                t0 = time.perf_counter()
                try:
                    model, processor = load(self._model_name)
                except Exception as e:  # noqa: BLE001
                    raise RuntimeError(
                        f"failed to load mlx-vlm model {self._model_name!r}: {e}. "
                        "Download a model first or specify a model_name that is "
                        "available locally."
                    ) from e
                load_duration = time.perf_counter() - t0
                _INSTANCE = (model, processor, load_duration)
                self._model = model
                self._processor = processor
                self._model_load_duration = load_duration

    def recognize(self, image_bytes: bytes) -> OcrResult:
        """Run OCR via mlx-vlm. Serialized across all callers."""
        self._ensure_model()
        input_dims: tuple[int, int] | None = None
        try:
            from PIL import Image  # type: ignore

            with Image.open(io.BytesIO(image_bytes)) as im:
                input_dims = (im.width, im.height)
        except Exception:  # noqa: BLE001
            input_dims = None

        with acquire_inference_lock():
            t0 = time.perf_counter()
            text = self._invoke_model(image_bytes)
            inference_duration = time.perf_counter() - t0

        info = OcrBackendInfo(
            backend=self.name,
            backend_version=self.version,
            model_name=self._model_name,
            device="mps",
            engine_version=_engine_version_info(),
            load_duration_s=self._model_load_duration,
            inference_duration_s=inference_duration,
            input_dimensions=input_dims,
            preprocessing_used=[],
            retry_used=False,
            raw_output_path=None,
            is_mock=False,
        )

        # mlx-vlm returns a single text blob; we put it in one region.
        regions: list[OcrRegion] = []
        if text.strip():
            regions.append(OcrRegion(bbox=[], text=text.strip(), confidence=0.0))
        return OcrResult(
            raw_text=text,
            regions=regions,
            backend=self.name,
            backend_version=self.version,
            # mlx-vlm does not return per-token confidence in a portable way.
            # We record 0.0 so downstream logic treats this as uncalibrated.
            model_confidence=0.0,
            extra={"region_count": len(regions)},
            metadata=info.to_dict(),
        )

    def _invoke_model(self, image_bytes: bytes) -> str:
        """Invoke the VLM with a transcription prompt."""
        import tempfile
        from pathlib import Path

        from PIL import Image  # type: ignore

        # mlx-vlm expects a file path for the image in most versions.
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
            tf.write(image_bytes)
            tmp_path = tf.name
        try:
            try:
                from mlx_vlm import generate  # type: ignore
                from mlx_vlm.prompt_utils import apply_chat_template  # type: ignore
                from mlx_vlm.utils import load_config  # type: ignore

                config = load_config(self._model_name)
                prompt = "Transcribe the text in this image verbatim, preserving line breaks and indentation."
                formatted = apply_chat_template(
                    self._processor, config, prompt, num_images=1
                )
                output = generate(
                    self._model,
                    self._processor,
                    formatted,
                    tmp_path,
                    max_tokens=512,
                    verbose=False,
                )
                if isinstance(output, tuple):
                    text = output[0]
                else:
                    text = output
                return str(text or "")
            except Exception as e:  # noqa: BLE001
                raise RuntimeError(
                    f"mlx-vlm inference failed: {e}. The model may not support "
                    "image transcription or the image format may be unsupported."
                ) from e
        finally:
            try:
                import os

                os.unlink(tmp_path)
            except OSError:
                pass
