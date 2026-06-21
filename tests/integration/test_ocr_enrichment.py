"""Integration tests for OCR enrichment with the mock backend.

These tests construct a document with visual blocks whose evidence points at
the golden PNG fixtures, register expected OCR text with the mock backend, and
verify the enricher resolves the blocks correctly.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from writeup2md.config import Profile, build_config
from writeup2md.models import (
    Block,
    BlockType,
    Document,
    DocumentStatus,
    EvidenceKind,
    EvidenceRef,
    Manifest,
    SourceRecord,
    SourceType,
    VisualBlockState,
    VisualType,
    canonicalize_source,
    compute_document_id,
    content_sha256_text,
    next_block_id,
    now_iso_utc,
)
from writeup2md.ocr.backend import reset_backend
from writeup2md.ocr.enricher import enrich_document
from writeup2md.ocr.mock import MockOcrBackend
from writeup2md.render import render_markdown


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "ocr"


@pytest.fixture(autouse=True)
def _reset_ocr_backend():
    reset_backend()
    yield
    reset_backend()


def _load_fixture(name: str) -> bytes:
    return (FIXTURE_DIR / name).read_bytes()


def _make_document_with_visuals(
    tmp_path: Path,
    visuals: list[tuple[str, str, str]],
    *,
    contextual_text: str = "",
) -> tuple[Document, Path, dict[str, bytes]]:
    """Build a document with visual blocks pointing at copied evidence files.

    `visuals` is a list of (fixture_name, expected_ocr_text, contextual_block_text).
    Returns (document, document_dir, image_bytes_by_block_id).
    """
    document_dir = tmp_path / "doc"
    document_dir.mkdir(parents=True, exist_ok=True)
    (document_dir / "evidence" / "elements").mkdir(parents=True, exist_ok=True)
    (document_dir / "evidence" / "regions").mkdir(parents=True, exist_ok=True)

    cfg = build_config(Profile.MACBOOK)
    content_sha = content_sha256_text("test content")
    doc_id = compute_document_id(
        source="test",
        canonical_source="test",
        content_sha256=content_sha,
        config_sha256=cfg.config_sha256(),
    )
    manifest = Manifest(
        document_id=doc_id,
        source="test",
        source_type=SourceType.HTML,
        canonical_source="test",
        captured_at=now_iso_utc(),
        content_sha256=content_sha,
        config_sha256=cfg.config_sha256(),
        status=DocumentStatus.REVIEW,
    )
    src = SourceRecord(
        source_type=SourceType.HTML,
        source="test",
        canonical_source="test",
        captured_at=now_iso_utc(),
        content_sha256=content_sha,
    )

    blocks: list[Block] = []
    counter = [0]
    images: dict[str, bytes] = {}

    def make(**kwargs) -> Block:
        idx = counter[0]
        counter[0] += 1
        kwargs.setdefault("block_id", next_block_id(idx))
        kwargs.setdefault("order", idx)
        return Block(**kwargs)

    if contextual_text:
        blocks.append(make(type=BlockType.HEADING, text="Test Document", heading_level=1))
        blocks.append(make(type=BlockType.PARAGRAPH, text=contextual_text))

    for fixture_name, _expected_text, ctx_text in visuals:
        # Write the fixture bytes to evidence/elements/.
        data = _load_fixture(fixture_name)
        sha = hashlib.sha256(data).hexdigest()
        asset_rel = f"evidence/elements/{sha[:16]}.png"
        (document_dir / asset_rel).write_bytes(data)
        ev = EvidenceRef(
            kind=EvidenceKind.DOM_ELEMENT,
            selector="img",
            asset_path=asset_rel,
            content_sha256=sha,
        )
        bid = f"b_{len(blocks):06d}"
        images[bid] = data
        blocks.append(
            make(
                type=BlockType.VISUAL,
                visual_type=VisualType.UNKNOWN,
                visual_state=VisualBlockState.REVIEW_REQUIRED,
                evidence=[ev],
                extra={"alt": ctx_text, "src": fixture_name},
            )
        )

    return Document(manifest=manifest, source=src, blocks=blocks), document_dir, images


def _register_mock(images: dict[str, bytes], expected: dict[str, str]) -> MockOcrBackend:
    backend = MockOcrBackend()
    for fixture_name, text in expected.items():
        data = _load_fixture(fixture_name)
        # Use confidence 1.0 so the calibrated high threshold (0.99) admits
        # these blocks to resolved_ocr. Real rapidocr confidences (~0.94)
        # would route to review under the calibrated policy.
        backend.register_bytes(data, text, confidence=1.0)
    return backend


def test_enrich_code_screenshot_becomes_resolved_code_block(tmp_path: Path):
    expected_text = (
        "1  import requests\n"
        "2  url = 'https://vuln.example.com/login'\n"
        "3  resp = requests.post(url)\n"
        "4  print(resp.status_code)"
    )
    doc, doc_dir, images = _make_document_with_visuals(
        tmp_path,
        [("code_python.png", expected_text, "code screenshot")],
    )
    backend = _register_mock(images, {"code_python.png": expected_text})
    cfg = build_config(Profile.MACBOOK)

    enriched = enrich_document(doc, document_dir=doc_dir, config=cfg, backend=backend)

    visual_block = [b for b in enriched.blocks if b.type == BlockType.VISUAL][0]
    assert visual_block.visual_state == VisualBlockState.RESOLVED_OCR
    assert visual_block.visual_type == VisualType.CODE
    assert visual_block.enrichment is not None
    assert "import requests" in visual_block.enrichment.selected_text
    # Editor line numbers stripped.
    assert "removed_editor_line_numbers" in visual_block.enrichment.transformations
    # Line numbers gone from selected text.
    assert not any(
        line.startswith(("1 ", "2 ", "3 ", "4 "))
        for line in visual_block.enrichment.selected_text.split("\n")
    )


def test_enrich_terminal_splits_commands_and_outputs(tmp_path: Path):
    expected_text = (
        "$ python exploit.py\n"
        "[+] payload injected\n"
        "[+] session cookie obtained\n"
        "[+] done"
    )
    doc, doc_dir, _ = _make_document_with_visuals(
        tmp_path,
        [("terminal_bash.png", expected_text, "terminal output")],
    )
    backend = _register_mock({"terminal_bash.png": expected_text}, {})
    # _register_mock signature mismatch fix:
    backend = MockOcrBackend()
    backend.register_bytes(_load_fixture("terminal_bash.png"), expected_text, confidence=1.0)
    cfg = build_config(Profile.MACBOOK)

    enriched = enrich_document(doc, document_dir=doc_dir, config=cfg, backend=backend)
    vb = [b for b in enriched.blocks if b.type == BlockType.VISUAL][0]
    assert vb.visual_type == VisualType.TERMINAL
    assert vb.enrichment.language == "bash"
    assert "terminal_command_output_split" in vb.enrichment.transformations
    assert any(s["role"] == "command" for s in vb.enrichment.segments)
    assert any(s["role"] == "output" for s in vb.enrichment.segments)


def test_enrich_http_preserves_request_verbatim(tmp_path: Path):
    expected_text = (
        "POST /login HTTP/1.1\n"
        "Host: vuln.example.com\n"
        "Content-Type: application/x-www-form-urlencoded\n"
        "\n"
        "user=admin&pass=' OR 1=1 --"
    )
    doc, doc_dir, _ = _make_document_with_visuals(
        tmp_path,
        [("http_request.png", expected_text, "HTTP request screenshot")],
    )
    backend = MockOcrBackend()
    backend.register_bytes(_load_fixture("http_request.png"), expected_text, confidence=1.0)
    cfg = build_config(Profile.MACBOOK)

    enriched = enrich_document(doc, document_dir=doc_dir, config=cfg, backend=backend)
    vb = [b for b in enriched.blocks if b.type == BlockType.VISUAL][0]
    assert vb.visual_type == VisualType.HTTP
    assert vb.enrichment.language == "http"
    assert "POST /login HTTP/1.1" in vb.enrichment.selected_text
    assert "user=admin&pass=' OR 1=1 --" in vb.enrichment.selected_text


def test_enrich_diff_preserves_markers(tmp_path: Path):
    expected_text = (
        "--- a/auth.py\n"
        "+++ b/auth.py\n"
        "@@ -10,3 +10,3 @@\n"
        "-if user.password == payload:\n"
        "+if user.check_password(payload):\n"
        "     return True"
    )
    doc, doc_dir, _ = _make_document_with_visuals(
        tmp_path,
        [("diff_patch.png", expected_text, "git diff patch")],
    )
    backend = MockOcrBackend()
    backend.register_bytes(_load_fixture("diff_patch.png"), expected_text, confidence=1.0)
    cfg = build_config(Profile.MACBOOK)

    enriched = enrich_document(doc, document_dir=doc_dir, config=cfg, backend=backend)
    vb = [b for b in enriched.blocks if b.type == BlockType.VISUAL][0]
    assert vb.visual_type == VisualType.DIFF
    assert vb.enrichment.language == "diff"
    assert "-if user.password == payload:" in vb.enrichment.selected_text
    assert "+if user.check_password(payload):" in vb.enrichment.selected_text


def test_enrich_low_confidence_marks_review_required(tmp_path: Path):
    expected_text = "garbled text"
    doc, doc_dir, _ = _make_document_with_visuals(
        tmp_path,
        [("code_python.png", expected_text, "code")],
    )
    backend = MockOcrBackend()
    backend.register_bytes(_load_fixture("code_python.png"), expected_text, confidence=0.3)
    cfg = build_config(Profile.MACBOOK)

    enriched = enrich_document(doc, document_dir=doc_dir, config=cfg, backend=backend)
    vb = [b for b in enriched.blocks if b.type == BlockType.VISUAL][0]
    assert vb.visual_state == VisualBlockState.REVIEW_REQUIRED
    assert vb.enrichment.review_required is True


def test_enrich_markdown_has_no_images_after_enrichment(tmp_path: Path):
    expected_text = "import requests\nresp = requests.get('https://x')"
    doc, doc_dir, _ = _make_document_with_visuals(
        tmp_path,
        [("code_python.png", expected_text, "code")],
    )
    backend = MockOcrBackend()
    # Use confidence 1.0 to clear the calibrated high threshold (0.99).
    backend.register_bytes(_load_fixture("code_python.png"), expected_text, confidence=1.0)
    cfg = build_config(Profile.MACBOOK)

    enriched = enrich_document(doc, document_dir=doc_dir, config=cfg, backend=backend)
    md = render_markdown(enriched)
    assert "![" not in md
    assert "<img" not in md
    assert "```python" in md
    assert "import requests" in md


def test_enrich_routes_to_review_under_calibrated_threshold(tmp_path: Path):
    """Under the calibrated high threshold (0.99), a 0.95-confidence block
    must route to review_required (never silently auto-accept). This reflects
    the Golden Set finding that rapidocr's ~0.95 confidence corresponds to
    ~17% CER — unacceptable for auto-acceptance."""
    expected_text = "import requests\nresp = requests.get('https://x')"
    doc, doc_dir, _ = _make_document_with_visuals(
        tmp_path,
        [("code_python.png", expected_text, "code")],
    )
    backend = MockOcrBackend()
    backend.register_bytes(_load_fixture("code_python.png"), expected_text, confidence=0.95)
    cfg = build_config(Profile.MACBOOK)

    enriched = enrich_document(doc, document_dir=doc_dir, config=cfg, backend=backend)
    vb = [b for b in enriched.blocks if b.type == BlockType.VISUAL][0]
    assert vb.visual_state == VisualBlockState.REVIEW_REQUIRED
    assert vb.enrichment.review_required is True
    # The OCR text is preserved in enrichment, even though not rendered to
    # markdown until a human verifies.
    assert "import requests" in vb.enrichment.selected_text


def test_enrich_failed_when_no_evidence_image(tmp_path: Path):
    """Visual block with empty asset_path is marked FAILED, not silently dropped."""
    doc, doc_dir, _ = _make_document_with_visuals(
        tmp_path,
        [("code_python.png", "x", "code")],
    )
    # Remove the evidence files to simulate a missing asset.
    for f in (doc_dir / "evidence" / "elements").iterdir():
        f.unlink()

    backend = MockOcrBackend()
    cfg = build_config(Profile.MACBOOK)
    enriched = enrich_document(doc, document_dir=doc_dir, config=cfg, backend=backend)
    vb = [b for b in enriched.blocks if b.type == BlockType.VISUAL][0]
    assert vb.visual_state == VisualBlockState.FAILED


def test_enrich_does_not_auto_repair_code(tmp_path: Path):
    """The enricher must NOT alter code beyond line-number stripping and whitespace."""
    expected_text = (
        "1  def f(x):\n"
        "2      return x +"  # deliberately incomplete — must NOT be repaired
    )
    doc, doc_dir, _ = _make_document_with_visuals(
        tmp_path,
        [("code_python.png", expected_text, "code")],
    )
    backend = MockOcrBackend()
    backend.register_bytes(_load_fixture("code_python.png"), expected_text, confidence=1.0)
    cfg = build_config(Profile.MACBOOK)

    enriched = enrich_document(doc, document_dir=doc_dir, config=cfg, backend=backend)
    vb = [b for b in enriched.blocks if b.type == BlockType.VISUAL][0]
    # The incomplete line must be preserved verbatim (minus line number).
    assert "return x +" in vb.enrichment.selected_text


def test_enrich_serializes_through_one_backend_instance(tmp_path: Path):
    """Multiple visual blocks share one backend instance — the MacBook constraint."""
    expected_text = "import os"
    doc, doc_dir, _ = _make_document_with_visuals(
        tmp_path,
        [
            ("code_python.png", expected_text, "code 1"),
            ("terminal_bash.png", "$ ls", "terminal 1"),
        ],
    )
    backend = MockOcrBackend()
    backend.register_bytes(_load_fixture("code_python.png"), expected_text, confidence=1.0)
    backend.register_bytes(_load_fixture("terminal_bash.png"), "$ ls\nfile.txt", confidence=1.0)
    cfg = build_config(Profile.MACBOOK)

    # Pass the same backend instance; enricher should reuse it.
    enriched = enrich_document(doc, document_dir=doc_dir, config=cfg, backend=backend)
    visuals = [b for b in enriched.blocks if b.type == BlockType.VISUAL]
    assert len(visuals) == 2
    assert all(vb.enrichment is not None for vb in visuals)


# ---------------------------------------------------------------------------
# TASK_17: PaddleOCR-VL element mode reports confidence=0.0 (the VLM returns
# free-form text with no per-region scores). The TASK_09 threshold model
# (high=0.99, calibrated for RapidOCR) would mark every transcription
# review_required. The enricher bypasses the threshold for PaddleOCR-VL
# backends: when the structural-quality gate does NOT fire, the block is
# marked resolved_ocr regardless of the unmeaningful confidence score.
# ---------------------------------------------------------------------------


class _PaddleOcrVlElementMock(MockOcrBackend):
    """Mock that reports as `paddleocr-vl-element` and always returns
    confidence=0.0 (matching the real VLM behavior)."""

    name = "paddleocr-vl-element"
    version = "0.9B-element"

    def register_bytes(self, image_bytes: bytes, text: str, confidence: float = 0.95) -> str:
        # Override to force confidence=0.0 — the real VLM signature.
        return super().register_bytes(image_bytes, text, confidence=0.0)


def test_enrich_paddleocr_vl_zero_confidence_non_empty_text_resolves(tmp_path: Path):
    """TASK_17/D1: PaddleOCR-VL element mode returns confidence=0.0 but the
    text is good. The structural-quality gate does not fire on normal text,
    so the block should resolve to RESOLVED_OCR (not REVIEW_REQUIRED)."""
    expected_text = "import requests\nresp = requests.get('https://x')"
    doc, doc_dir, _ = _make_document_with_visuals(
        tmp_path,
        [("code_python.png", expected_text, "code screenshot")],
    )
    backend = _PaddleOcrVlElementMock()
    backend.register_bytes(_load_fixture("code_python.png"), expected_text)
    cfg = build_config(Profile.MACBOOK)

    enriched = enrich_document(doc, document_dir=doc_dir, config=cfg, backend=backend)
    vb = [b for b in enriched.blocks if b.type == BlockType.VISUAL][0]
    assert vb.visual_state == VisualBlockState.RESOLVED_OCR
    assert vb.enrichment.review_required is False
    assert vb.enrichment.selected_text == expected_text
    # Evidence layout per TASK_17.C: original/normalized/candidates exist.
    ev_dir = doc_dir / "evidence" / "visuals" / vb.block_id
    assert (ev_dir / "original").is_dir()
    assert (ev_dir / "normalized").is_dir()
    assert (ev_dir / "candidates").is_dir()
    assert (ev_dir / "provenance.json").is_file()


def test_enrich_paddleocr_vl_space_merged_still_routes_to_review(tmp_path: Path):
    """TASK_17: even with PaddleOCR-VL, the structural-quality gate still
    routes suspicious output to review. We don't blindly trust 0.0
    confidence — we trust the structural signal."""
    # Build a "space-merged" string: one very long word (>80 chars).
    expected_text = "importrequestsurl='https://vuln.example.com/login'resp=requests.post(url)print(resp.status_code)"
    doc, doc_dir, _ = _make_document_with_visuals(
        tmp_path,
        [("code_python.png", expected_text, "code screenshot")],
    )
    backend = _PaddleOcrVlElementMock()
    backend.register_bytes(_load_fixture("code_python.png"), expected_text)
    cfg = build_config(Profile.MACBOOK)

    enriched = enrich_document(doc, document_dir=doc_dir, config=cfg, backend=backend)
    vb = [b for b in enriched.blocks if b.type == BlockType.VISUAL][0]
    assert vb.visual_state == VisualBlockState.REVIEW_REQUIRED
    assert vb.enrichment.review_required is True
    # The text is preserved in enrichment for the review UI.
    assert expected_text in vb.enrichment.selected_text


def test_enrich_paddleocr_vl_persists_normalized_evidence(tmp_path: Path):
    """TASK_17.B/C: normalized image and provenance are written under
    evidence/visuals/<block_id>/. The normalized image must be a PNG no
    larger than 1568 px on its longest side."""
    expected_text = "import os"
    doc, doc_dir, _ = _make_document_with_visuals(
        tmp_path,
        [("code_python.png", expected_text, "code screenshot")],
    )
    backend = _PaddleOcrVlElementMock()
    backend.register_bytes(_load_fixture("code_python.png"), expected_text)
    cfg = build_config(Profile.MACBOOK)

    enriched = enrich_document(doc, document_dir=doc_dir, config=cfg, backend=backend)
    vb = [b for b in enriched.blocks if b.type == BlockType.VISUAL][0]
    ev_dir = doc_dir / "evidence" / "visuals" / vb.block_id
    # Normalized PNG exists.
    norm = ev_dir / "normalized" / "input.png"
    assert norm.is_file()
    # Original asset exists (extension preserved).
    orig_files = list((ev_dir / "original").iterdir())
    assert len(orig_files) == 1
    # Provenance records dimensions and normalization steps.
    prov = json.loads((ev_dir / "provenance.json").read_text(encoding="utf-8"))
    assert "original_dimensions" in prov
    assert "normalized_dimensions" in prov
    assert "normalization_steps" in prov
    # Normalized image longest side <= 1568 px (verified via PIL).
    from PIL import Image
    with Image.open(norm) as img:
        longest = max(img.size)
    assert longest <= 1568
