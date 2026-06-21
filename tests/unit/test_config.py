"""Tests for configuration profiles and limits."""

from __future__ import annotations

import pytest

from writeup2md.config import (
    Profile,
    WriteupConfig,
    build_config,
    enforce_macbook_limits,
)


def test_macbook_profile_defaults():
    cfg = build_config(Profile.MACBOOK)
    assert cfg.pipeline.profile == Profile.MACBOOK
    assert cfg.pipeline.workers == 1
    assert cfg.pipeline.max_workers == 2
    assert cfg.ocr.model_instances == 1
    assert cfg.ocr.max_concurrent_inference == 1
    assert cfg.ocr.heavy_queue_capacity == 2
    assert cfg.pdf.initial_render_dpi == 300
    assert cfg.markdown.allow_images is False


def test_strict_profile_limits_workers_to_one():
    cfg = build_config(Profile.STRICT)
    assert cfg.pipeline.profile == Profile.STRICT
    assert cfg.pipeline.max_workers == 1


def test_fast_profile_does_not_retain_evidence():
    cfg = build_config(Profile.FAST)
    assert cfg.pipeline.retain_raw_evidence is False


def test_default_profile_uses_macbook_limits():
    cfg = build_config(Profile.DEFAULT)
    assert cfg.pipeline.workers == 1
    assert cfg.ocr.model_instances == 1


def test_enforce_macbook_rejects_over_max_workers():
    cfg = build_config(Profile.MACBOOK)
    cfg.pipeline.workers = 3
    with pytest.raises(ValueError):
        enforce_macbook_limits(cfg)


def test_enforce_macbook_allows_two_workers():
    cfg = build_config(Profile.MACBOOK)
    cfg.pipeline.workers = 2
    # should not raise
    enforce_macbook_limits(cfg)


def test_ocr_model_instances_locked_to_one():
    cfg = build_config(Profile.MACBOOK)
    cfg.ocr.model_instances = 2
    with pytest.raises(Exception):
        cfg.ocr.model_validate(cfg.ocr.model_dump(mode="json") | {"model_instances": 2})


def test_config_sha256_is_stable():
    cfg1 = build_config(Profile.MACBOOK)
    cfg2 = build_config(Profile.MACBOOK)
    assert cfg1.config_sha256() == cfg2.config_sha256()
    cfg2.pipeline.workers = 2
    assert cfg1.config_sha256() != cfg2.config_sha256()


def test_build_config_accepts_string_profile():
    cfg = build_config("macbook")
    assert cfg.pipeline.profile == Profile.MACBOOK
