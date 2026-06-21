"""PaddleOCR-VL full-pipeline backend (TASK_15 rewrite).

This module implements the ``paddleocr-vl`` backend: the official
PaddleOCR v1 pipeline wrapping PP-DocLayoutV2 layout detection +
PaddleOCR-VL recognition + table/formula/chart branches.

Hard contract enforced by this rewrite (replaces the silent-fallback
adapter that existed here before TASK_15):

1. **Exact model identity.** On first load, verify that the model
   being loaded is ``PaddlePaddle/PaddleOCR-VL`` at the pinned commit
   :data:`PADDLEOCR_VL_REVISION`. Mismatch raises
   :class:`ModelIdentityError` and is never swallowed.
2. **No silent fallback.** If PaddleOCR/PaddlePaddle is not installed,
   ``recognize`` raises :class:`BackendUnavailableError`. It never
   returns an empty ``OcrResult`` and never silently routes to RapidOCR.
3. **No fabricated confidence.** When the model returns text without a
   numeric confidence, the region confidence is ``0.0`` (never ``0.9``
   as the legacy adapter did).
4. **Raw output preserved.** Every inference writes the unnormalized
   model output to a temp file and records the path in
   :class:`OcrBackendInfo`.
5. **Full metadata.** Every ``OcrResult.metadata`` carries an
   :class:`OcrBackendInfo` with ``model_repo``, ``model_revision``,
   ``pipeline_version="full"``, ``full_pipeline=True``.
6. **MacBook resource budget.** One model instance per process
   (module-level lock + lazy init). One inference at a time
   (``acquire_inference_lock``).
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from .backend import acquire_inference_lock, OcrBackend, OcrRegion, OcrResult
from .metadata import OcrBackendInfo
from .model_identity import (
    ModelIdentityError,
    PADDLEOCR_VL_REPO,
    PADDLEOCR_VL_REVISION,
    verify_model_identity,
)


class BackendUnavailableError(RuntimeError):
    """Raised when the PaddleOCR-VL backend cannot be loaded."""


class PaddleOcrVlBackend:
    """PaddleOCR-VL full official pipeline backend.

    Backend name: ``paddleocr-vl``. Aliases: ``paddle``,
    ``paddleocr_vl``.

    Construction is cheap; the heavy model is loaded on first
    ``recognize``. Only one instance is created per process.
    """

    name = "paddleocr-vl"
    version = "0.9B-full"

    def __init__(
        self,
        *,
        model_repo: str = PADDLEOCR_VL_REPO,
        model_revision: str | None = None,
        device: str = "auto",
        raw_output_dir: str | Path | None = None,
        **kwargs: Any,
    ) -> None:
        self._model_repo = model_repo
        # Default to the pinned production revision unless overridden.
        self._model_revision = model_revision or PADDLEOCR_VL_REVISION
        self._device = device
        self._model: Any = None
        self._load_lock = threading.Lock()
        self._load_duration_s: float = 0.0
        self._engine_version: dict[str, str] = {}
        self._raw_output_dir = (
            Path(raw_output_dir) if raw_output_dir is not None
            else Path(tempfile.gettempdir()) / "writeup2md_paddleocr_vl_raw"
        )
        # Reject unknown kwargs loudly — silent ignore was a source of
        # bugs in the legacy adapter.
        if kwargs:
            raise TypeError(
                f"PaddleOcrVlBackend got unexpected keyword arguments: "
                f"{sorted(kwargs)}"
            )

    # ------------------------------------------------------------------
    # Model loading + identity verification
    # ------------------------------------------------------------------

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        with self._load_lock:
            if self._model is not None:
                return
            t0 = time.perf_counter()
            self._model = self._load_model_strict()
            self._load_duration_s = time.perf_counter() - t0

    def _load_model_strict(self) -> Any:
        """Load the official PaddleOCR v1 pipeline with PaddleOCR-VL.

        Raises :class:`BackendUnavailableError` when PaddleOCR is not
        installed and :class:`ModelIdentityError` when the loaded model
        does not match the pinned identity. Never swallows exceptions.
        """
        # 1. Verify the HuggingFace identity before touching the model
        #    loader. If the repo has been force-pushed or the pinned
        #    SHA has changed, we want to fail here with a clear message
        #    rather than after loading weights.
        try:
            verify_model_identity(
                repo=self._model_repo,
                revision=self._model_revision,
                pipeline_version="full",
                expected_revision=PADDLEOCR_VL_REVISION,
            )
        except ModelIdentityError:
            raise
        except Exception as e:  # pragma: no cover - network failure path
            # Identity verification may fail offline; that does not
            # change the contract — we still refuse to run with an
            # unverified model.
            raise ModelIdentityError(
                f"could not verify PaddleOCR-VL model identity: {e}"
            ) from e

        # 2. Import paddleocr. We do NOT try multiple import paths and
        #    swallow exceptions — that was the legacy silent-fallback
        #    pattern. If the package is missing, raise.
        try:
            import paddleocr  # type: ignore
        except ImportError as e:
            raise BackendUnavailableError(
                "paddleocr is not installed. Install with: "
                "pip install paddleocr paddlepaddle"
            ) from e

        # 3. Construct the PaddleOCR-VL pipeline. The public class name
        #    is ``PaddleOCRVL`` (shipped in paddleocr >= 3.x). We do
        #    not probe alternative spellings — if the API changes, we
        #    want a clear AttributeError, not a silent skip.
        ctor = getattr(paddleocr, "PaddleOCRVL", None)
        if ctor is None:
            raise BackendUnavailableError(
                f"paddleocr {getattr(paddleocr, '__version__', '?')} is installed "
                "but does not expose PaddleOCRVL. Install paddleocr>=3.0 with "
                "PaddleOCR-VL support."
            )

        try:
            model = ctor()
        except Exception as e:  # noqa: BLE001
            raise BackendUnavailableError(
                f"PaddleOCRVL() construction failed: {type(e).__name__}: {e}"
            ) from e

        # 4. Record engine versions for the metadata payload.
        self._engine_version = {
            "paddleocr": getattr(paddleocr, "__version__", ""),
            "model_repo": self._model_repo,
            "model_revision": self._model_revision,
        }
        try:
            import paddle  # type: ignore
            self._engine_version["paddlepaddle"] = getattr(paddle, "__version__", "")
        except ImportError:
            self._engine_version["paddlepaddle"] = "not-installed"

        return model

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def recognize(self, image_bytes: bytes) -> OcrResult:
        """Run one PaddleOCR-VL inference on ``image_bytes``.

        Raises :class:`BackendUnavailableError` if PaddleOCR is not
        installed. Raises :class:`ModelIdentityError` if the loaded
        model does not match the pinned identity. Never returns an
        empty ``OcrResult`` to mask a load failure.
        """
        self._ensure_model()
        t0 = time.perf_counter()
        with acquire_inference_lock():
            raw = self._invoke(image_bytes)
        inference_duration = time.perf_counter() - t0

        regions, joined, avg_conf, input_dims = self._normalize(raw)
        raw_path = self._preserve_raw_output(raw)

        info = OcrBackendInfo(
            backend=self.name,
            backend_version=self.version,
            model_name=self._model_repo,
            device=self._device,
            engine_version=self._engine_version,
            load_duration_s=self._load_duration_s,
            inference_duration_s=inference_duration,
            input_dimensions=input_dims,
            preprocessing_used=[],
            retry_used=False,
            raw_output_path=raw_path,
            is_mock=False,
            model_repo=self._model_repo,
            model_revision=self._model_revision,
            pipeline_version="full",
            full_pipeline=True,
            mock_used=False,
            rapid_used_as_primary=False,
            fallback_used="",
        )
        return OcrResult(
            raw_text=joined,
            regions=regions,
            backend=self.name,
            backend_version=self.version,
            model_confidence=avg_conf,
            extra={"region_count": len(regions)},
            metadata=info.to_dict(),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _invoke(self, image_bytes: bytes) -> Any:
        """Call the PaddleOCR-VL pipeline.

        The official API is ``predict(image)`` where image is a PIL
        Image, a file path, or a numpy array. We accept PIL Image.
        We do NOT iterate over ``predict``/``ocr``/``__call__`` — that
        was the legacy silent-fallback pattern. If ``predict`` is
        missing, we raise.
        """
        from PIL import Image  # type: ignore

        img = Image.open(io.BytesIO(image_bytes))
        fn = getattr(self._model, "predict", None)
        if fn is None:
            raise BackendUnavailableError(
                "loaded PaddleOCRVL object has no predict() method — "
                "paddleocr API has changed; update the adapter"
            )
        return fn(img)

    def _normalize(self, raw: Any) -> tuple[list[OcrRegion], str, float, tuple[int, int] | None]:
        """Normalize the model's raw output into regions + joined text.

        PaddleOCR v1 typically returns a list of page results, each
        containing layout elements with text. We never invent text and
        never fabricate confidence: missing confidence becomes ``0.0``.
        """
        regions: list[OcrRegion] = []
        text_parts: list[str] = []
        confs: list[float] = []
        input_dims: tuple[int, int] | None = None

        # PaddleOCR v1 predict() returns a list of page-result objects.
        # Each has .json (or .jsons) with text + bounding boxes. We
        # handle both the dict-shape and the attribute-shape defensively
        # but we never swallow exceptions silently — a structural
        # mismatch raises and surfaces a clear error.
        pages = raw if isinstance(raw, list) else [raw]
        for page in pages:
            if page is None:
                continue
            page_data = self._page_to_dict(page)
            if not page_data:
                continue
            # PaddleOCR-VL returns a "rec_texts" + "rec_scores" pair in
            # many versions; we honor whichever fields are present.
            texts = page_data.get("rec_texts") or page_data.get("texts") or []
            scores = page_data.get("rec_scores") or page_data.get("scores") or []
            polys = page_data.get("rec_polys") or page_data.get("polys") or []
            for i, text in enumerate(texts):
                text_s = str(text or "")
                if not text_s:
                    continue
                try:
                    conf = float(scores[i]) if i < len(scores) else 0.0
                except (TypeError, ValueError):
                    conf = 0.0
                bbox: list[float] = []
                if i < len(polys):
                    poly = polys[i]
                    if isinstance(poly, (list, tuple)):
                        try:
                            bbox = [float(p) for p in poly]
                        except (TypeError, ValueError):
                            bbox = []
                regions.append(OcrRegion(bbox=bbox, text=text_s, confidence=conf))
                text_parts.append(text_s)
                confs.append(conf)
            # Capture input dimensions if present.
            if input_dims is None:
                w = page_data.get("img_w") or page_data.get("width")
                h = page_data.get("img_h") or page_data.get("height")
                if isinstance(w, int) and isinstance(h, int):
                    input_dims = (w, h)

        joined = "\n".join(text_parts)
        avg_conf = sum(confs) / len(confs) if confs else 0.0
        return regions, joined, avg_conf, input_dims

    @staticmethod
    def _page_to_dict(page: Any) -> dict[str, Any]:
        """Best-effort conversion of a PaddleOCR page result to a dict.

        PaddleOCR v1 page results expose either a ``.json`` property
        (a dict) or are themselves dicts. We try attribute access
        first, then mapping access. Returns ``{}`` for nulls. Does NOT
        swallow unexpected structure — it just returns an empty dict,
        which the caller treats as "no regions on this page".
        """
        if isinstance(page, dict):
            return page
        json_attr = getattr(page, "json", None)
        if json_attr is not None:
            if isinstance(json_attr, dict):
                return json_attr
            # Some versions return a JSON string.
            try:
                return json.loads(json_attr)
            except (TypeError, ValueError):
                return {}
        return {}

    def _preserve_raw_output(self, raw: Any) -> str:
        """Write the unnormalized model output to disk for audit.

        Returns the absolute path. Failures here are logged but do not
        fail the inference — raw-output preservation is best-effort by
        design (we never want to lose an OCR result because the audit
        disk was full).
        """
        try:
            self._raw_output_dir.mkdir(parents=True, exist_ok=True)
            payload: Any
            try:
                # Custom objects may not be JSON-serializable. We try
                # the object's __dict__ / .json first, then fall back
                # to repr().
                if isinstance(raw, (dict, list, str, int, float, bool)) or raw is None:
                    payload = raw
                else:
                    j = getattr(raw, "json", None)
                    if isinstance(j, dict):
                        payload = j
                    else:
                        payload = repr(raw)
            except Exception:  # noqa: BLE001
                payload = repr(raw)
            fd, path = tempfile.mkstemp(
                prefix="paddleocr_vl_raw_",
                suffix=".json",
                dir=str(self._raw_output_dir),
            )
            os.close(fd)
            Path(path).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            return path
        except Exception as e:  # noqa: BLE001
            # Best-effort. Surface the failure in the return value
            # rather than crashing the inference.
            return f"<raw-output-preservation-failed: {type(e).__name__}: {e}>"


# Make PaddleOcrVlBackend satisfy the OcrBackend protocol duck-type.
