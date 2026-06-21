"""Exact model identity verification for PaddleOCR-VL (TASK_15).

Resolves and pins an immutable HuggingFace commit SHA for the
``PaddlePaddle/PaddleOCR-VL`` model. The SHA is the source of truth
for "the real model actually ran" — every inference must record it
in :class:`OcrBackendInfo.model_revision`.

This module never silently falls back. If the repo cannot be reached
or the resolved SHA does not match the expected one, it raises
:class:`ModelIdentityError`.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

# Canonical identity for the production model. Hard-coded so that the
# production threshold cannot drift with a typo. Verified live against
# HuggingFace on 2026-06-20.
PADDLEOCR_VL_REPO = "PaddlePaddle/PaddleOCR-VL"
PADDLEOCR_VL_REVISION = "baee27eebcbf26cdeab160116679d765f13a3f27"


class ModelIdentityError(RuntimeError):
    """Raised when the resolved model identity does not match the expected one."""


@dataclass(frozen=True)
class ModelIdentity:
    """Immutable record of a verified model identity."""

    repo: str
    revision: str  # commit SHA
    pipeline_version: str  # "full" | "element" | ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_repo": self.repo,
            "model_revision": self.revision,
            "pipeline_version": self.pipeline_version,
        }


# Process-local cache so we do not hit HuggingFace on every inference.
_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, ModelIdentity] = {}


def verify_model_identity(
    repo: str = PADDLEOCR_VL_REPO,
    revision: str | None = None,
    *,
    pipeline_version: str = "",
    expected_revision: str | None = None,
    offline: bool = False,
) -> ModelIdentity:
    """Resolve and verify the identity of a HuggingFace model.

    Parameters
    ----------
    repo:
        HuggingFace repo id. Defaults to the production PaddleOCR-VL repo.
    revision:
        Optional pinned revision (commit SHA or tag). If provided, the
        resolved SHA must match exactly. If ``None``, the current ``main``
        branch HEAD is resolved and cached.
    pipeline_version:
        Recorded on the returned :class:`ModelIdentity`. ``"full"`` for
        the official PaddleOCR pipeline, ``"element"`` for HF transformers
        element-mode, ``""`` for other backends.
    expected_revision:
        Optional hard expectation. When set, the resolved SHA must equal
        this value or :class:`ModelIdentityError` is raised. Useful for
        enforcing the production pin (``PADDLEOCR_VL_REVISION``).
    offline:
        When ``True``, skip the network call and return the cached
        identity if present, otherwise raise :class:`ModelIdentityError`.
        Used by tests that must not touch the network.
    """
    cache_key = f"{repo}@{revision or 'main'}"
    with _CACHE_LOCK:
        cached = _CACHE.get(cache_key)
        if cached is not None:
            if expected_revision is not None and cached.revision != expected_revision:
                raise ModelIdentityError(
                    f"cached model identity for {repo} does not match expected: "
                    f"cached={cached.revision} expected={expected_revision}"
                )
            return cached
        if offline:
            raise ModelIdentityError(
                f"offline mode requested but no cached identity for {cache_key!r}"
            )

    # Resolve the immutable commit SHA via huggingface_hub. We use
    # model_info() first because it is cheaper than snapshot_download().
    try:
        from huggingface_hub import HfApi  # type: ignore
    except ImportError as e:  # pragma: no cover - exercised in tests via offline
        raise ModelIdentityError(
            "huggingface_hub is required for model identity verification. "
            "Install with: pip install huggingface_hub"
        ) from e

    api = HfApi()
    try:
        info = api.model_info(repo, revision=revision)
    except Exception as e:  # noqa: BLE001
        raise ModelIdentityError(
            f"failed to resolve model info for {repo}@{revision or 'main'}: "
            f"{type(e).__name__}: {e}"
        ) from e

    resolved_sha = getattr(info, "sha", "") or ""
    if not resolved_sha:
        raise ModelIdentityError(
            f"model_info for {repo} returned no commit SHA"
        )

    if expected_revision is not None and resolved_sha != expected_revision:
        raise ModelIdentityError(
            f"resolved model revision for {repo} does not match the production pin. "
            f"resolved={resolved_sha} expected={expected_revision}. "
            "Refusing to run with a different model. Update the pin in "
            "src/writeup2md/ocr/model_identity.py if this is intentional."
        )

    identity = ModelIdentity(
        repo=repo,
        revision=resolved_sha,
        pipeline_version=pipeline_version,
    )
    with _CACHE_LOCK:
        _CACHE[cache_key] = identity
    return identity


def cached_identity(repo: str = PADDLEOCR_VL_REPO) -> ModelIdentity | None:
    """Return the cached identity for ``repo`` if present, else None."""
    with _CACHE_LOCK:
        for key, identity in _CACHE.items():
            if key.startswith(f"{repo}@"):
                return identity
    return None


def clear_cache() -> None:
    """Clear the in-process identity cache. Used by tests."""
    with _CACHE_LOCK:
        _CACHE.clear()
