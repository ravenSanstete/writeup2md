"""RapidOCR backend (rapidocr-onnxruntime).

This is the primary REAL OCR backend for writeup2md on Apple Silicon Macs.
`rapidocr-onnxruntime` ships the PaddleOCR PP-OCR detection+classification+
recognition pipeline as ONNX models, which run on the CPU through onnxruntime
and work without PaddlePaddle. The output shape is the familiar
`[bbox, text, confidence]` per region.

Resource behavior:
- one RapidOCR instance per process (module-level singleton + lock);
- one inference at a time (module-level _INFERENCE_LOCK shared with all
  backends);
- PIL images and rapidocr internal arrays are released after each call;
- model is loaded lazily on the first `recognize`.

We never invent text or confidence. If rapidocr returns no result, the
OcrResult has empty regions and model_confidence 0.0.
"""

from __future__ import annotations

import io
import threading
import time
from typing import Any

from .backend import acquire_inference_lock, OcrRegion, OcrResult
from .metadata import OcrBackendInfo


# Module-level singleton: one RapidOCR instance per process.
_INSTANCE_LOCK = threading.Lock()
_INSTANCE: Any = None
_INSTANCE_LOAD_DURATION: float = 0.0


def _engine_version_info() -> dict[str, str]:
    """Collect engine versions for metadata provenance."""
    info: dict[str, str] = {}
    try:
        from importlib.metadata import version

        info["rapidocr_onnxruntime"] = version("rapidocr-onnxruntime")
    except Exception:  # noqa: BLE001
        pass
    try:
        import onnxruntime  # type: ignore

        info["onnxruntime"] = onnxruntime.__version__
        info["onnxruntime_providers"] = ",".join(onnxruntime.get_available_providers())
    except Exception:  # noqa: BLE001
        pass
    return info


class RapidOcrBackend:
    """rapidocr-onnxruntime backend.

    Construction is cheap; the heavy model is loaded on first `recognize`.
    """

    name = "rapid"
    version = "rapidocr-onnxruntime"

    def __init__(self, *, device: str = "auto", **kwargs: Any) -> None:
        self._device = device
        self._load_lock = threading.Lock()
        self._extra_kwargs = kwargs
        # Filled in _ensure_model.
        self._engine: Any = None
        self._model_load_duration: float = 0.0

    def _ensure_model(self) -> None:
        """Lazily load the RapidOCR engine. One instance per process."""
        global _INSTANCE, _INSTANCE_LOAD_DURATION
        if self._engine is not None:
            return
        with _INSTANCE_LOCK:
            if _INSTANCE is not None:
                self._engine = _INSTANCE
                self._model_load_duration = _INSTANCE_LOAD_DURATION
                return
            with self._load_lock:
                if _INSTANCE is not None:
                    self._engine = _INSTANCE
                    self._model_load_duration = _INSTANCE_LOAD_DURATION
                    return
                try:
                    import rapidocr_onnxruntime as r  # type: ignore
                except ImportError as e:  # pragma: no cover - depends on env
                    raise RuntimeError(
                        "rapidocr-onnxruntime is not installed. "
                        "Install with: pip install rapidocr-onnxruntime"
                    ) from e
                t0 = time.perf_counter()
                engine = r.RapidOCR()
                load_duration = time.perf_counter() - t0
                _INSTANCE = engine
                _INSTANCE_LOAD_DURATION = load_duration
                self._engine = engine
                self._model_load_duration = load_duration

    def recognize(self, image_bytes: bytes) -> OcrResult:
        """Run OCR on a single image. Serialized across all callers."""
        self._ensure_model()
        # Read dimensions for metadata BEFORE inference (cheap PIL open).
        input_dims: tuple[int, int] | None = None
        try:
            from PIL import Image  # type: ignore

            with Image.open(io.BytesIO(image_bytes)) as im:
                input_dims = (im.width, im.height)
        except Exception:  # noqa: BLE001
            input_dims = None

        with acquire_inference_lock():
            t0 = time.perf_counter()
            raw_pages, elapse = self._call_engine(image_bytes)
            inference_duration = time.perf_counter() - t0

        return self._normalize(
            raw_pages=raw_pages,
            elapse=elapse,
            input_dims=input_dims,
            load_duration=self._model_load_duration,
            inference_duration=inference_duration,
        )

    def _call_engine(self, image_bytes: bytes) -> tuple[Any, Any]:
        """Call rapidocr with bytes input. Returns (result, elapse)."""
        # rapidocr accepts a path or bytes or numpy array. Bytes path is most
        # portable. We use a BytesIO via PIL to avoid writing temp files.
        try:
            from PIL import Image  # type: ignore
            import numpy as np  # type: ignore

            img = Image.open(io.BytesIO(image_bytes))
            arr = np.array(img.convert("RGB"))
            return self._engine(arr)
        except Exception:  # noqa: BLE001
            # Fall back to writing a temp file (rapidocr's preferred path).
            import tempfile

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
                tf.write(image_bytes)
                tmp_path = tf.name
            try:
                return self._engine(tmp_path)
            finally:
                try:
                    import os

                    os.unlink(tmp_path)
                except OSError:
                    pass

    def _normalize(
        self,
        *,
        raw_pages: Any,
        elapse: Any,
        input_dims: tuple[int, int] | None,
        load_duration: float,
        inference_duration: float,
    ) -> OcrResult:
        """Convert rapidocr's [bbox, text, conf] list into an OcrResult.

        We never invent text or confidence. Empty regions stay empty.
        """
        regions: list[OcrRegion] = []
        confs: list[float] = []

        items = raw_pages if isinstance(raw_pages, list) else []
        for item in items:
            try:
                if not isinstance(item, (list, tuple)) or len(item) < 3:
                    continue
                bbox_raw = item[0]
                text = str(item[1] or "")
                conf_raw = item[2]
                try:
                    conf = float(conf_raw)
                except (TypeError, ValueError):
                    conf = 0.0
                # bbox_raw from rapidocr is a 4-point polygon:
                # [[x0,y0],[x1,y1],[x2,y2],[x3,y3]]. Convert to [x0,y0,x1,y1].
                bbox: list[float] = []
                if isinstance(bbox_raw, (list, tuple)) and len(bbox_raw) >= 4:
                    xs = []
                    ys = []
                    for pt in bbox_raw:
                        if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                            xs.append(float(pt[0]))
                            ys.append(float(pt[1]))
                    if xs and ys:
                        bbox = [min(xs), min(ys), max(xs), max(ys)]
                if text:
                    regions.append(OcrRegion(bbox=bbox, text=text, confidence=conf))
                    confs.append(conf)
            except Exception:  # noqa: BLE001
                continue

        joined = "\n".join(r.text for r in regions)
        avg_conf = sum(confs) / len(confs) if confs else 0.0

        info = OcrBackendInfo(
            backend=self.name,
            backend_version=self.version,
            model_name="ch_ppocr_mobile_v2.0+rec",
            device="cpu",
            engine_version=_engine_version_info(),
            load_duration_s=load_duration,
            inference_duration_s=inference_duration,
            input_dimensions=input_dims,
            preprocessing_used=[],
            retry_used=False,
            raw_output_path=None,
            is_mock=False,
        )

        return OcrResult(
            raw_text=joined,
            regions=regions,
            backend=self.name,
            backend_version=self.version,
            model_confidence=avg_conf,
            extra={
                "region_count": len(regions),
                "elapse": list(elapse) if isinstance(elapse, (list, tuple)) else elapse,
            },
            metadata=info.to_dict(),
        )
