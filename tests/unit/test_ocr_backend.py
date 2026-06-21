"""Unit tests for OCR backend interface and mock backend."""

from __future__ import annotations

import hashlib

from writeup2md.ocr.backend import (
    acquire_inference_lock,
    get_backend,
    reset_backend,
)
from writeup2md.ocr.mock import MockOcrBackend


def test_mock_backend_returns_registered_result():
    backend = MockOcrBackend()
    img = b"fake-image-bytes"
    text = "print('hello')"
    sha = backend.register_bytes(img, text, confidence=0.95)
    assert sha == hashlib.sha256(img).hexdigest()
    result = backend.recognize(img)
    assert result.joined_text == text
    assert result.model_confidence == 0.95
    assert result.backend == "mock"


def test_mock_backend_returns_empty_for_unregistered():
    backend = MockOcrBackend()
    result = backend.recognize(b"unregistered")
    assert result.joined_text == ""
    assert result.model_confidence == 0.0


def test_get_backend_reuses_instance():
    reset_backend()
    b1 = get_backend("mock")
    b2 = get_backend("mock")
    assert b1 is b2
    reset_backend()


def test_get_backend_unknown_name_raises():
    reset_backend()
    try:
        get_backend("nonexistent")
        assert False, "expected ValueError"
    except ValueError:
        pass
    finally:
        reset_backend()


def test_inference_lock_is_global():
    lock = acquire_inference_lock()
    assert lock is acquire_inference_lock()


def test_mock_backend_satisfies_protocol():
    backend = MockOcrBackend()
    assert hasattr(backend, "name")
    assert hasattr(backend, "version")
    assert hasattr(backend, "recognize")
    assert backend.name == "mock"
