"""Deterministic mock OCR backend for tests.

The mock backend looks up pre-registered results by image content hash. This
makes tests fully deterministic and avoids any model download.
"""

from __future__ import annotations

import hashlib
from typing import Any

from .backend import OcrBackend, OcrRegion, OcrResult


class MockOcrBackend:
    """In-memory OCR backend for tests.

    Register expected results with `register(sha256_hex, OcrResult)` or
    `register_text(sha256_hex, text, confidence)`. Unregistered images return
    an empty result with confidence 0.0.
    """

    name = "mock"
    version = "0.0.1"

    def __init__(self, **kwargs: Any) -> None:
        self._registry: dict[str, OcrResult] = {}
        self.default_confidence: float = float(kwargs.get("default_confidence", 0.9))

    def register(self, content_sha256: str, result: OcrResult) -> None:
        self._registry[content_sha256.lower()] = result

    def register_text(
        self,
        content_sha256: str,
        text: str,
        confidence: float = 0.95,
        regions: list[OcrRegion] | None = None,
    ) -> None:
        sha = content_sha256.lower()
        result = OcrResult(
            raw_text=text,
            regions=regions or [],
            backend=self.name,
            backend_version=self.version,
            model_confidence=confidence,
        )
        self._registry[sha] = result

    def register_bytes(self, image_bytes: bytes, text: str, confidence: float = 0.95) -> str:
        sha = hashlib.sha256(image_bytes).hexdigest()
        self.register_text(sha, text, confidence=confidence)
        return sha

    def recognize(self, image_bytes: bytes) -> OcrResult:
        sha = hashlib.sha256(image_bytes).hexdigest()
        result = self._registry.get(sha)
        if result is None:
            return OcrResult(
                raw_text="",
                regions=[],
                backend=self.name,
                backend_version=self.version,
                model_confidence=0.0,
            )
        return result


# Make MockOcrBackend satisfy the OcrBackend protocol duck-type.
def _is_backend(b: Any) -> bool:
    return hasattr(b, "name") and hasattr(b, "version") and hasattr(b, "recognize")
