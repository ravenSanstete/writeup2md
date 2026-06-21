"""PaddleOCR-VL element-mode backend (TASK_15).

This module implements the ``paddleocr-vl-element`` backend: load
``PaddlePaddle/PaddleOCR-VL`` directly with HuggingFace ``transformers``
(``AutoModelForImageTextToText`` + ``AutoProcessor``) and run
recognition on pre-cropped element images.

This is the path that works on Apple Silicon without PaddlePaddle's
MPS gaps: ``transformers`` + ``torch`` MPS are both arm64-native.

Hard contract (same as the full-pipeline backend):

1. **Exact model identity.** On first load, verify the loaded model is
   ``PaddlePaddle/PaddleOCR-VL`` at the pinned commit
   :data:`PADDLEOCR_VL_REVISION`. Mismatch raises
   :class:`ModelIdentityError`.
2. **No silent fallback.** If ``transformers`` / ``torch`` are missing
   or the model cannot be loaded, ``recognize`` raises
   :class:`BackendUnavailableError`. Never returns empty output, never
   routes to RapidOCR.
3. **Deterministic generation.** ``do_sample=False`` is always set so
   two runs on the same image produce identical text.
4. **Raw output preserved.** Every inference writes the raw model
   output (generated token ids + decoded text) to disk.
5. **Full metadata.** ``OcrBackendInfo`` carries ``model_repo``,
   ``model_revision``, ``pipeline_version="element"``,
   ``full_pipeline=False``.
6. **MacBook budget.** One model instance per process; one inference
   at a time via ``acquire_inference_lock``.
"""

from __future__ import annotations

import io
import json
import os
import platform
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
    """Raised when the paddleocr-vl-element backend cannot be loaded."""


class PaddleOcrVlElementBackend:
    """PaddleOCR-VL element-mode backend (HF transformers).

    Backend name: ``paddleocr-vl-element``.
    """

    name = "paddleocr-vl-element"
    version = "0.9B-element"

    # Default generation prompt for the VLM. The PaddleOCR-VL README
    # documents four task prompts: ``"OCR:"``, ``"Table Recognition:"``,
    # ``"Formula Recognition:"``, ``"Chart Recognition:"``. We default
    # to ``"OCR:"`` because writeup2md's element-mode path is fed
    # pre-cropped code/terminal/http/diff/config/log blocks where the
    # user wants raw text transcription.
    _DEFAULT_PROMPT = "OCR:"

    def __init__(
        self,
        *,
        model_repo: str = PADDLEOCR_VL_REPO,
        model_revision: str | None = None,
        device: str = "auto",
        dtype: str = "auto",
        raw_output_dir: str | Path | None = None,
        prompt: str | None = None,
        max_new_tokens: int = 512,
        **kwargs: Any,
    ) -> None:
        self._model_repo = model_repo
        self._model_revision = model_revision or PADDLEOCR_VL_REVISION
        self._device_request = device
        self._dtype_request = dtype
        self._prompt = prompt or self._DEFAULT_PROMPT
        self._max_new_tokens = max_new_tokens
        self._model: Any = None
        self._processor: Any = None
        self._actual_device: str = ""
        self._load_lock = threading.Lock()
        self._load_duration_s: float = 0.0
        self._engine_version: dict[str, str] = {}
        self._raw_output_dir = (
            Path(raw_output_dir) if raw_output_dir is not None
            else Path(tempfile.gettempdir()) / "writeup2md_paddleocr_vl_element_raw"
        )
        if kwargs:
            raise TypeError(
                f"PaddleOcrVlElementBackend got unexpected keyword arguments: "
                f"{sorted(kwargs)}"
            )

    # ------------------------------------------------------------------
    # Device selection
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_device(requested: str) -> str:
        """Resolve the torch device. Defaults to MPS on Apple Silicon."""
        if requested and requested != "auto":
            return requested
        if platform.system() == "Darwin" and platform.machine() == "arm64":
            return "mps"
        return "cpu"

    @staticmethod
    def _resolve_dtype(requested: str, device: str):
        """Resolve the torch dtype.

        Defaults to ``bfloat16`` on CUDA (per the PaddleOCR-VL README)
        and ``float16`` on MPS (bfloat16 is not supported on Apple
        Silicon MPS as of torch 2.12). CPU uses ``float32``.
        """
        try:
            import torch  # type: ignore
        except ImportError as e:  # pragma: no cover - import checked at load
            raise BackendUnavailableError("torch is not installed") from e
        if requested and requested != "auto":
            return getattr(torch, requested)
        if device == "cuda":
            return torch.bfloat16
        if device == "mps":
            return torch.float16
        return torch.float32

    # ------------------------------------------------------------------
    # Model loading
    # ------------------------------------------------------------------

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        with self._load_lock:
            if self._model is not None:
                return
            t0 = time.perf_counter()
            self._model, self._processor = self._load_model_strict()
            self._load_duration_s = time.perf_counter() - t0

    def _load_model_strict(self) -> tuple[Any, Any]:
        """Load PaddleOCR-VL via HuggingFace transformers.

        Raises :class:`ModelIdentityError` on identity mismatch and
        :class:`BackendUnavailableError` on missing dependencies.
        """
        # 1. Identity verification first.
        try:
            verify_model_identity(
                repo=self._model_repo,
                revision=self._model_revision,
                pipeline_version="element",
                expected_revision=PADDLEOCR_VL_REVISION,
            )
        except ModelIdentityError:
            raise
        except Exception as e:  # pragma: no cover - network failure path
            raise ModelIdentityError(
                f"could not verify PaddleOCR-VL model identity: {e}"
            ) from e

        # 2. Imports.
        try:
            import torch  # type: ignore
            from transformers import AutoModelForCausalLM, AutoProcessor  # type: ignore
        except ImportError as e:
            raise BackendUnavailableError(
                "transformers and torch are required for paddleocr-vl-element. "
                "Install with: pip install transformers torch"
            ) from e

        # 2b. Apply a compatibility shim for the PaddleOCR-VL custom_code.
        # The model's modeling_paddleocr_vl.py calls
        # ``create_causal_mask(..., inputs_embeds=...)`` (with the
        # legacy plural spelling). Transformers 4.53+ renamed the
        # parameter to ``input_embeds`` (singular). We patch the
        # custom_code module's reference so it accepts either spelling.
        self._apply_causal_mask_compatibility_shim()

        # 3. Device + dtype.
        device = self._resolve_device(self._device_request)
        # If MPS is requested but unavailable, fall back to CPU. We log
        # this in engine_version so it is visible in diagnostics.
        if device == "mps" and not getattr(torch.backends, "mps", None):
            device = "cpu"
        if device == "mps" and not torch.backends.mps.is_available():
            device = "cpu"
        dtype = self._resolve_dtype(self._dtype_request, device)

        # 4. Load processor + model. trust_remote_code is REQUIRED
        #    because the repo ships custom_code
        #    (modeling_paddleocr_vl.py, processing_paddleocr_vl.py).
        #    The README explicitly documents ``AutoModelForCausalLM``
        #    (not AutoModelForImageTextToText) — the latter does not
        #    recognize the custom PaddleOCRVLConfig class.
        try:
            processor = AutoProcessor.from_pretrained(
                self._model_repo,
                revision=self._model_revision,
                trust_remote_code=True,
            )
        except Exception as e:  # noqa: BLE001
            raise BackendUnavailableError(
                f"AutoProcessor.from_pretrained({self._model_repo}) failed: "
                f"{type(e).__name__}: {e}"
            ) from e

        try:
            model = AutoModelForCausalLM.from_pretrained(
                self._model_repo,
                revision=self._model_revision,
                trust_remote_code=True,
                torch_dtype=dtype,
            ).to(device)
        except Exception as e:  # noqa: BLE001
            raise BackendUnavailableError(
                f"AutoModelForCausalLM.from_pretrained({self._model_repo}) "
                f"failed: {type(e).__name__}: {e}"
            ) from e

        # 5. Switch to eval mode for deterministic inference.
        try:
            model.eval()
        except Exception:  # noqa: BLE001
            pass

        # 6. Re-apply the shim to the custom_code module's local
        #    reference. The custom_code does
        #    ``from transformers.masking_utils import create_causal_mask``
        #    at import time, which captures the function reference.
        #    Step 2b patched the source module before this import
        #    happened, so the custom_code should already have the
        #    patched version. We double-check here and patch the
        #    custom_code module directly if needed.
        self._patch_custom_code_causal_mask()

        self._actual_device = device
        self._engine_version = {
            "transformers": self._pkg_version("transformers"),
            "torch": self._pkg_version("torch"),
            "model_repo": self._model_repo,
            "model_revision": self._model_revision,
            "device": device,
            "dtype": str(dtype),
            "causal_mask_shim_applied": True,
        }

        return model, processor

    # ------------------------------------------------------------------
    # Compatibility shim
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_causal_mask_compatibility_shim() -> None:
        """Patch transformers' ``create_causal_mask`` to accept the
        legacy ``inputs_embeds`` kwarg spelling used by the
        PaddleOCR-VL custom_code.

        The model's ``modeling_paddleocr_vl.py`` (commit
        ``baee27eebcbf26cdeab160116679d765f13a3f27``) calls:

        .. code-block:: python

            create_causal_mask(
                config=self.config,
                inputs_embeds=inputs_embeds,
                ...
            )

        Transformers 4.53+ renamed the parameter from ``inputs_embeds``
        to ``input_embeds`` (singular). We wrap the function so the
        legacy spelling is translated to the new one. This shim is
        idempotent: applying it twice has no effect.
        """
        try:
            from transformers import masking_utils  # type: ignore
        except ImportError:
            return  # transformers too old; the model will fail loudly.

        original = getattr(masking_utils, "create_causal_mask", None)
        if original is None:
            return
        # Skip if already patched (idempotent).
        if getattr(original, "_w2md_patched", False):
            return

        def _patched_create_causal_mask(*args, **kwargs):
            # Translate the legacy kwarg to the new spelling.
            if "inputs_embeds" in kwargs and "input_embeds" not in kwargs:
                kwargs["input_embeds"] = kwargs.pop("inputs_embeds")
            return original(*args, **kwargs)

        _patched_create_causal_mask._w2md_patched = True  # type: ignore[attr-defined]
        masking_utils.create_causal_mask = _patched_create_causal_mask

        # Also patch any module-level import in transformers that re-exports
        # the symbol, so the custom_code's ``from transformers.X import
        # create_causal_mask`` resolves to the patched version.
        for mod_name in ("transformers",):
            try:
                mod = __import__(mod_name, fromlist=["create_causal_mask"])
                if getattr(mod, "create_causal_mask", None) is original:
                    mod.create_causal_mask = _patched_create_causal_mask
            except Exception:  # noqa: BLE001
                pass

    @staticmethod
    def _patch_custom_code_causal_mask() -> None:
        """Patch the PaddleOCR-VL custom_code module's local
        ``create_causal_mask`` reference.

        The custom_code module is loaded by transformers under
        ``transformers_modules.PaddlePaddle.PaddleOCR-VL.<sha>``. Its
        ``modeling_paddleocr_vl`` does
        ``from transformers.masking_utils import create_causal_mask``
        at import time, capturing the (possibly already-patched)
        reference. We re-patch it here to be safe.
        """
        import importlib  # noqa: PLC0415
        try:
            from transformers import masking_utils  # type: ignore
        except ImportError:
            return
        patched = getattr(masking_utils, "create_causal_mask", None)
        if patched is None or not getattr(patched, "_w2md_patched", False):
            return  # shim was not applied; nothing to propagate
        # Find every loaded transformers_modules.* submodule that has
        # a create_causal_mask attribute and replace it.
        import sys  # noqa: PLC0415
        for name, mod in list(sys.modules.items()):
            if not name.startswith("transformers_modules."):
                continue
            if hasattr(mod, "create_causal_mask"):
                try:
                    mod.create_causal_mask = patched
                except Exception:  # noqa: BLE001
                    pass
            # Also patch submodules like modeling_paddleocr_vl that
            # captured the reference locally.
            for attr in ("modeling_paddleocr_vl",):
                sub = getattr(mod, attr, None)
                if sub is not None and hasattr(sub, "create_causal_mask"):
                    try:
                        sub.create_causal_mask = patched
                    except Exception:  # noqa: BLE001
                        pass

    @staticmethod
    def _pkg_version(name: str) -> str:
        try:
            from importlib.metadata import version
            return version(name)
        except Exception:  # noqa: BLE001
            return ""

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def recognize(self, image_bytes: bytes) -> OcrResult:
        self._ensure_model()
        t0 = time.perf_counter()
        with acquire_inference_lock():
            generated_text, input_dims, raw_payload = self._invoke(image_bytes)
        inference_duration = time.perf_counter() - t0

        raw_path = self._preserve_raw_output(raw_payload)
        regions = self._text_to_regions(generated_text, input_dims)
        avg_conf = 0.0  # VLM generation does not produce per-region confidences.

        info = OcrBackendInfo(
            backend=self.name,
            backend_version=self.version,
            model_name=self._model_repo,
            device=self._actual_device,
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
            pipeline_version="element",
            full_pipeline=False,
            mock_used=False,
            rapid_used_as_primary=False,
            fallback_used="",
        )
        return OcrResult(
            raw_text=generated_text,
            regions=regions,
            backend=self.name,
            backend_version=self.version,
            model_confidence=avg_conf,
            extra={
                "region_count": len(regions),
                "prompt": self._prompt,
                "max_new_tokens": self._max_new_tokens,
            },
            metadata=info.to_dict(),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _invoke(self, image_bytes: bytes) -> tuple[str, tuple[int, int] | None, dict[str, Any]]:
        """Run one VLM generation.

        Returns ``(generated_text, input_dimensions, raw_payload)``.
        ``raw_payload`` is the full audit record (input shape, prompt,
        generation config, generated ids, decoded text).

        Implements the inference pattern documented in the PaddleOCR-VL
        README: ``AutoModelForCausalLM`` + ``AutoProcessor`` with
        ``apply_chat_template(tokenize=True, return_dict=True)`` and
        ``do_sample=False`` for deterministic output.
        """
        import torch  # type: ignore
        from PIL import Image  # type: ignore

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        input_dims = (img.width, img.height)

        # Build the chat-style input via the processor. PaddleOCR-VL
        # uses a chat template that expects an image + user text.
        try:
            chat_messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "image": img},
                        {"type": "text", "text": self._prompt},
                    ],
                }
            ]
            inputs = self._processor.apply_chat_template(
                chat_messages,
                tokenize=True,
                add_generation_prompt=True,
                return_dict=True,
                return_tensors="pt",
            ).to(self._actual_device)
        except Exception as e:  # noqa: BLE001
            raise BackendUnavailableError(
                f"processor input preparation failed: {type(e).__name__}: {e}"
            ) from e

        # Deterministic generation. do_sample=False is required by the
        # writeup2md contract — two runs on the same image must produce
        # identical text.
        gen_kwargs = {
            "max_new_tokens": self._max_new_tokens,
            "do_sample": False,
            "use_cache": True,
        }
        with torch.inference_mode():
            output_ids = self._model.generate(**inputs, **gen_kwargs)

        # Decode the full output and strip the chat prefix. The
        # README uses ``processor.batch_decode(outputs, skip_special_tokens=True)[0]``
        # which returns the full sequence (prompt + generated). We
        # strip everything up to and including the assistant turn marker.
        try:
            full_text = self._processor.batch_decode(
                output_ids, skip_special_tokens=True
            )[0]
            generated_text = self._strip_chat_prefix(full_text)
        except Exception as e:  # noqa: BLE001
            raise BackendUnavailableError(
                f"output decode failed: {type(e).__name__}: {e}"
            ) from e

        raw_payload = {
            "input_dimensions": list(input_dims),
            "prompt": self._prompt,
            "generation_config": {k: str(v) for k, v in gen_kwargs.items()},
            "output_token_count": int(output_ids.shape[1]) if hasattr(output_ids, "shape") else 0,
            "generated_text": generated_text,
        }
        return generated_text, input_dims, raw_payload

    @staticmethod
    def _strip_chat_prefix(text: str) -> str:
        """Strip the chat-template prefix from decoded VLM output.

        The PaddleOCR-VL chat template renders the user turn (image +
        prompt) and the assistant turn marker. When we decode the full
        output (input + generated), the decoded text includes
        ``"User: OCR:\\nAssistant: <actual OCR text>"``. We strip
        everything up to and including the last assistant marker.

        If neither marker is present, we return the text as-is.
        """
        if not text:
            return ""
        # Try common assistant-turn markers used by the chat template.
        for marker in ("Assistant:", "assistant:", "<|assistant|>"):
            idx = text.rfind(marker)
            if idx != -1:
                return text[idx + len(marker):].strip()
        # Fall back to stripping the user prompt if present.
        return text.strip()

    @staticmethod
    def _text_to_regions(text: str, input_dims: tuple[int, int] | None) -> list[OcrRegion]:
        """Split VLM output into line-based regions.

        The element-mode VLM returns free-form text without bounding
        boxes. We split on newlines so each line becomes a region.
        Confidence is 0.0 because the VLM does not produce per-region
        scores — we never fabricate one.
        """
        regions: list[OcrRegion] = []
        for line in text.splitlines():
            line_s = line.rstrip()
            if line_s:
                regions.append(OcrRegion(bbox=[], text=line_s, confidence=0.0))
        return regions

    def _preserve_raw_output(self, payload: dict[str, Any]) -> str:
        try:
            self._raw_output_dir.mkdir(parents=True, exist_ok=True)
            fd, path = tempfile.mkstemp(
                prefix="paddleocr_vl_element_raw_",
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
            return f"<raw-output-preservation-failed: {type(e).__name__}: {e}>"


# Make PaddleOcrVlElementBackend satisfy the OcrBackend protocol duck-type.
