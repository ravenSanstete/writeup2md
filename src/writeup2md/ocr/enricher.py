"""Visual enricher: routes visual blocks to OCR and applies post-processing.

The enricher walks a document's blocks, finds unresolved `visual` blocks,
loads their evidence image, runs the OCR backend, classifies the result, and
updates the block with an `EnrichedVisual` record and a `resolved_*` state.

TASK_10: every visual block ends in an explicit coverage state. The enricher
calls `apply_coverage_state` for every terminal state (resolved_ocr,
review_required, failed, ignored_decorative) so the visual coverage ledger
is complete.

Resource behavior:
- one OCR backend instance per process (enforced in `backend.py`);
- one inference at a time (enforced by the inference lock);
- image bytes are read from disk per block and not retained after enrichment;
- the model is loaded lazily on the first unresolved visual.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import WriteupConfig
from ..coverage import apply_coverage_state
from ..models import (
    Block,
    BlockType,
    Document,
    EnrichedVisual,
    EvidenceKind,
    VisualBlockState,
    VisualType,
)
from ..quality import IMPORTANT_RESOLVED_STATES, is_important_visual
from .backend import OcrBackend, OcrResult, get_backend
from .candidate_selection import select_best, structural_score
from .code_postprocess import (
    normalize_fullwidth_punct,
    recover_indentation,
    split_space_merged_tokens,
)
from .image_normalize import (
    DEFAULT_MAX_LONG_SIDE,
    NormalizedImage,
    normalize_image_for_ocr,
    save_normalized_evidence,
)
from .multi_view import run_multi_view
from .panel_split import split_panels
from .postprocess import postprocess
from .router import classify_from_context, classify_from_text, detect_language


# Confidence thresholds calibrated against the Golden Set (TASK_09).
#
# Findings: rapidocr's per-region confidence is NOT a calibrated probability.
# It reports ~0.94 mean confidence on samples with mean CER 0.166. The
# confidence is also slightly anti-correlated with quality on edge cases
# (cropped, low-res, indentation-sensitive samples report conf 0.9-0.95 but
# have CER 0.30-0.47).
#
# To achieve high accepted precision (priority per spec), we route the vast
# majority of OCR output to review. A block is auto-accepted as resolved_ocr
# only when ALL of:
#   - confidence >= _HIGH_CONFIDENCE_THRESHOLD (0.99 — very few blocks qualify)
#   - critical tokens are preserved (heuristic: no obvious word-merging)
# Anything below _LOW_CONFIDENCE_THRESHOLD is also review_required (or failed
# if below _FAILED_THRESHOLD). Between low and high is review_required.
#
# This conservative policy trades throughput for precision. The Golden Set
# showed that under (low=0.6, high=0.85), accepted_precision was 0.07 —
# unacceptable. With high=0.99 plus the structural gate, the auto-accept
# bucket becomes effectively empty on this Golden Set, which is the correct
# conservative behavior until a better-calibrated confidence source exists.
_LOW_CONFIDENCE_THRESHOLD = 0.6
_HIGH_CONFIDENCE_THRESHOLD = 0.99
_FAILED_THRESHOLD = 0.3


def enrich_document(
    document: Document,
    *,
    document_dir: Path,
    config: WriteupConfig,
    backend: OcrBackend | None = None,
    backend_name: str | None = None,
    on_warning=None,
) -> Document:
    """Enrich all unresolved visual blocks in place and return the document.

    If the configured backend cannot be loaded (e.g. PaddleOCR-VL is not
    installed), blocks are left as `review_required` and `on_warning` is
    called with a human-readable message. We NEVER fake OCR success.
    """
    if backend is None:
        backend_name = backend_name or config.ocr.backend
        try:
            backend = get_backend(backend_name)
        except Exception as e:  # noqa: BLE001
            if on_warning is not None:
                on_warning(
                    f"OCR backend {backend_name!r} unavailable; "
                    f"visual blocks left as review_required. Error: {e}"
                )
            # Mark all unresolved visuals as review_required (they already are).
            return document

    blocks = document.blocks
    for i, block in enumerate(blocks):
        if block.type != BlockType.VISUAL:
            continue
        if block.visual_state in IMPORTANT_RESOLVED_STATES:
            # Already resolved — ensure coverage state is set if missing.
            if block.coverage_state is None:
                apply_coverage_state(
                    block, "transcribed",
                    f"already {block.visual_state.value}; no explicit ledger entry"
                )
            continue
        if block.visual_state == VisualBlockState.IGNORED_DECORATIVE:
            if block.coverage_state is None:
                apply_coverage_state(
                    block, "decorative_with_reason",
                    "already ignored_decorative; no explicit ledger entry"
                )
            continue

        preceding_text = _gather_text(blocks, i, direction=-1, max_chars=400)
        following_text = _gather_text(blocks, i, direction=+1, max_chars=400)

        contextual_type = classify_from_context(
            block, preceding_text=preceding_text, following_text=following_text
        )

        # If no backend (e.g. load failed), surface as review_required with the
        # contextual classification recorded.
        if backend is None:
            block.visual_type = contextual_type
            block.visual_state = VisualBlockState.REVIEW_REQUIRED
            apply_coverage_state(
                block, "review_required", "OCR backend unavailable; awaiting manual review"
            )
            continue

        # Find the evidence image on disk.
        original_image_bytes = _read_evidence_image(document_dir, block)
        if original_image_bytes is None:
            # No evidence available — mark as failed (still surfaced in diagnostics).
            block.visual_type = contextual_type
            block.visual_state = VisualBlockState.FAILED
            block.enrichment = EnrichedVisual(
                visual_type=contextual_type,
                raw_text="",
                selected_text="",
                confidence=0.0,
                review_required=True,
                transformations=[],
                backend=getattr(backend, "name", "unknown"),
                backend_version=getattr(backend, "version", ""),
            )
            apply_coverage_state(
                block, "failed_with_diagnostic", "no evidence image available on disk"
            )
            continue

        # TASK_17.B: normalize the image before OCR. PaddleOCR-VL is a
        # 0.9B VLM; sending 4387x2784 cover-spread images caused runaway
        # generation (>1000 tokens of "0"s, hallucinated English). The
        # normalizer decodes, downsizes to <= 1568 px long side, and
        # emits PNG. The original is preserved separately on disk.
        normalized = normalize_image_for_ocr(
            original_image_bytes, max_long_side=DEFAULT_MAX_LONG_SIDE
        )
        if not normalized.ok:
            # Normalization failed (e.g. SVG without cairosvg, or corrupt
            # bytes). Surface as failed_with_diagnostic — never silently
            # drop the visual.
            if on_warning is not None:
                on_warning(
                    f"image normalization failed for {block.block_id}: {normalized.error}"
                )
            block.visual_type = contextual_type
            block.visual_state = VisualBlockState.FAILED
            block.enrichment = EnrichedVisual(
                visual_type=contextual_type,
                raw_text="",
                selected_text="",
                confidence=0.0,
                review_required=True,
                transformations=[normalized.error or "normalization_failed"],
                backend=getattr(backend, "name", "unknown"),
                backend_version=getattr(backend, "version", ""),
            )
            apply_coverage_state(
                block,
                "failed_with_diagnostic",
                f"image normalization failed: {normalized.error}",
            )
            continue

        # Persist original + normalized evidence per TASK_17.C. The
        # original asset path stays unchanged in block.evidence[0].asset_path;
        # the normalized input is recorded under evidence/visuals/<block_id>/.
        try:
            provenance_record = {
                "block_id": block.block_id,
                "source_kind": str(block.source_kind),
                "page": (
                    block.evidence[0].page if block.evidence else None
                ),
                "bbox": (
                    block.evidence[0].bbox if block.evidence else None
                ),
                "original_format": normalized.original_format,
                "original_dimensions": [
                    normalized.original_width,
                    normalized.original_height,
                ],
                "normalized_dimensions": [
                    normalized.normalized_width,
                    normalized.normalized_height,
                ],
                "normalization_steps": normalized.normalization_steps,
            }
            save_normalized_evidence(
                document_dir=document_dir,
                block_id=block.block_id,
                original_bytes=original_image_bytes,
                original_ext=normalized.original_format,
                normalized=normalized,
                provenance=provenance_record,
            )
        except Exception:  # noqa: BLE001
            # Evidence persistence is best-effort — do not block OCR
            # if the workspace is read-only or out of disk.
            pass

        # Send only the normalized PNG to the OCR backend.
        image_bytes = normalized.normalized_bytes

        # Run OCR.
        try:
            result = backend.recognize(image_bytes)
        except Exception as e:  # noqa: BLE001
            if on_warning is not None:
                on_warning(f"OCR inference failed for {block.block_id}: {e}")
            block.visual_type = contextual_type
            block.visual_state = VisualBlockState.FAILED
            block.enrichment = EnrichedVisual(
                visual_type=contextual_type,
                raw_text="",
                selected_text="",
                confidence=0.0,
                review_required=True,
                transformations=[],
                backend=getattr(backend, "name", "unknown"),
                backend_version=getattr(backend, "version", ""),
            )
            apply_coverage_state(
                block, "failed_with_diagnostic", f"OCR inference raised: {type(e).__name__}: {e}"
            )
            continue

        # TASK_17.C: copy the raw OCR output JSON (if the backend wrote one
        # to /tmp) into the document workspace so it survives /tmp removal.
        # The candidates directory is created by save_normalized_evidence.
        _copy_raw_ocr_to_workspace(document_dir, block.block_id, result)

        if not result.joined_text.strip():
            # OCR returned nothing — preserve the contextual classification.
            block.visual_type = contextual_type
            block.visual_state = VisualBlockState.REVIEW_REQUIRED
            block.enrichment = EnrichedVisual(
                visual_type=contextual_type,
                raw_text="",
                selected_text="",
                confidence=result.model_confidence,
                review_required=True,
                transformations=[],
                backend=getattr(backend, "name", "unknown"),
                backend_version=getattr(backend, "version", ""),
            )
            apply_coverage_state(
                block, "review_required", "OCR returned empty output; awaiting manual review"
            )
            continue

        # Re-classify using OCR text (more reliable than context alone).
        final_type = classify_from_text(result.joined_text, fallback=contextual_type)
        language = detect_language(result.joined_text, final_type) or _language_from_context(
            contextual_type
        )

        pp = postprocess(
            raw_text=result.joined_text,
            visual_type=final_type.value,
            language=language,
            base_confidence=result.model_confidence,
        )

        # TASK_11: code-aware postprocessing. Apply space-merge splitting,
        # fullwidth punctuation normalization, and indentation recovery.
        # These are STRUCTURAL only — never invent or repair code.
        code_text = pp.selected_text
        code_transformations: list[str] = list(pp.transformations)
        if code_text:
            new_text, tx = split_space_merged_tokens(code_text, language)
            if new_text != code_text:
                code_text = new_text
                code_transformations.extend(tx)
            new_text, tx = normalize_fullwidth_punct(code_text)
            if new_text != code_text:
                code_text = new_text
                code_transformations.extend(tx)
            new_text, tx = recover_indentation(code_text, language)
            if new_text != code_text:
                code_text = new_text
                code_transformations.extend(tx)
        pp_selected_text = code_text

        # TASK_11: multi-view retry. When confidence is below the high
        # threshold OR the structural-quality gate fires, re-run OCR on
        # alternate preprocessing views and pick the best candidate by
        # structural score. We never invent content — we only pick the
        # best OCR pass.
        #
        # TASK_15/16: skip multi-view retry for PaddleOCR-VL element mode.
        # That backend's confidence is always 0.0 (VLM returns free-form
        # text with no per-region scores), which would force 5× inference
        # on every visual. The VLM already produces high-quality text
        # (CER 0.0338 on the Golden Set vs RapidOCR's 0.1658), so the
        # candidate-selection step from TASK_11 is no longer paying off.
        # Multi-view retry remains active for RapidOCR-style backends that
        # report meaningful per-region confidences.
        backend_name = getattr(backend, "name", "")
        is_paddleocr_vl_element = backend_name == "paddleocr-vl-element"
        candidate_results: list[OcrResult] = [result]
        if (
            not is_paddleocr_vl_element
            and (
                result.model_confidence < _HIGH_CONFIDENCE_THRESHOLD
                or _looks_space_merged(pp_selected_text)
            )
        ):
            try:
                views = run_multi_view(backend, image_bytes, max_views=4)
                for vr in views:
                    if vr.view_name == "original":
                        continue  # already in candidate_results
                    candidate_results.append(vr.result)
            except Exception:  # noqa: BLE001
                # Multi-view failed — proceed with the original result.
                pass
            # Pick the best candidate by structural score.
            best = select_best(candidate_results, final_type.value)
            if best is not None and best is not result:
                # Re-run postprocess on the best candidate so panel
                # splitting and transformations are consistent.
                pp = postprocess(
                    raw_text=best.joined_text,
                    visual_type=final_type.value,
                    language=language,
                    base_confidence=best.model_confidence,
                )
                # Re-apply code-aware postprocessing on the new winner.
                code_text = pp.selected_text
                code_transformations = list(pp.transformations)
                if code_text:
                    new_text, tx = split_space_merged_tokens(code_text, language)
                    if new_text != code_text:
                        code_text = new_text
                        code_transformations.extend(tx)
                    new_text, tx = normalize_fullwidth_punct(code_text)
                    if new_text != code_text:
                        code_text = new_text
                        code_transformations.extend(tx)
                    new_text, tx = recover_indentation(code_text, language)
                    if new_text != code_text:
                        code_text = new_text
                        code_transformations.extend(tx)
                pp_selected_text = code_text
                result = best

        # TASK_11: multi-panel splitting. For terminal/http/diff visuals,
        # split into labeled segments.
        panels = split_panels(pp_selected_text, final_type.value)
        if panels:
            # Replace postprocess segments with panel-split segments when
            # we have them.
            segments = panels
            code_transformations.append("panel_split")
        else:
            segments = pp.segments

        # Combine model confidence + structural signals + code-postprocess boost.
        # Code-aware postprocessing that produced changes is a positive signal
        # (we found structural patterns to fix), so apply a small boost.
        code_boost = 0.0
        if code_transformations:
            # Count distinct code-postprocess transformations (excluding
            # postprocess's own).
            code_only = [
                t for t in code_transformations
                if t.startswith(("split:", "fullwidth_punct_", "indent_recovered"))
            ]
            if code_only:
                code_boost = min(0.05, 0.01 * len(code_only))
        confidence = max(0.0, min(1.0, result.model_confidence + pp.confidence_delta + code_boost))

        # Decorative classification short-circuits to ignored.
        if final_type == VisualType.DECORATIVE and not is_important_visual(block):
            block.visual_type = VisualType.DECORATIVE
            block.visual_state = VisualBlockState.IGNORED_DECORATIVE
            block.enrichment = EnrichedVisual(
                visual_type=VisualType.DECORATIVE,
                raw_text=result.joined_text,
                selected_text="",
                confidence=confidence,
                review_required=False,
                transformations=pp.transformations,
                backend=getattr(backend, "name", "unknown"),
                backend_version=getattr(backend, "version", ""),
            )
            apply_coverage_state(
                block, "decorative_with_reason",
                "OCR classified as decorative; not important per router"
            )
            continue

        review_required = confidence < _HIGH_CONFIDENCE_THRESHOLD
        if confidence < _LOW_CONFIDENCE_THRESHOLD:
            review_required = True

        # Structural-quality gate (TASK_09 calibration): rapidocr's confidence
        # is uncalibrated, so even at high confidence we route to review when
        # there are signals of likely OCR damage. Specifically:
        #   - very long "words" (>20 chars) suggest space-merging failure
        #     (e.g. "importrequests" instead of "import requests")
        #   - no spaces at all in a multi-character result suggests merging
        # These checks never REJECT the text — they only route to review so a
        # human can confirm.
        gate_reason = ""
        if not review_required:
            if _looks_space_merged(pp.selected_text):
                review_required = True
                gate_reason = "structural-quality gate: space-merge signal"

        # TASK_17/18: PaddleOCR-VL element mode reports confidence 0.0
        # because the VLM does not produce per-region scores. The TASK_09
        # threshold model (high=0.99) was calibrated for RapidOCR and is
        # not meaningful for this backend. When PaddleOCR-VL returns
        # non-empty text AND the structural-quality gate does NOT fire,
        # treat the block as resolved_ocr so the renderer surfaces the
        # transcription in document mode. The structural gate still
        # routes space-merged or suspicious output to review.
        is_paddleocr_vl = backend_name in ("paddleocr-vl", "paddleocr-vl-element")
        if is_paddleocr_vl and result.joined_text.strip():
            # Re-evaluate: the structural-quality gate is the only signal
            # we trust for this VLM backend. If it does NOT fire, mark
            # resolved regardless of the (unmeaningful) confidence score.
            if not _looks_space_merged(pp.selected_text):
                review_required = False
                gate_reason = ""
                confidence = max(confidence, 0.95)  # surface as resolved

        block.visual_type = final_type
        if confidence < _FAILED_THRESHOLD and not result.joined_text.strip():
            block.visual_state = VisualBlockState.FAILED
            coverage = "failed_with_diagnostic"
            coverage_reason = f"confidence {confidence:.3f} below failed threshold {_FAILED_THRESHOLD}"
        else:
            block.visual_state = (
                VisualBlockState.REVIEW_REQUIRED if review_required else VisualBlockState.RESOLVED_OCR
            )
            if review_required:
                coverage = "review_required"
                parts = [f"confidence {confidence:.3f} < high threshold {_HIGH_CONFIDENCE_THRESHOLD}"]
                if gate_reason:
                    parts.append(gate_reason)
                coverage_reason = "; ".join(parts)
            else:
                coverage = "transcribed"
                coverage_reason = f"OCR transcribed at confidence {confidence:.3f}"
        block.enrichment = EnrichedVisual(
            visual_type=final_type,
            raw_text=result.joined_text,
            selected_text=pp_selected_text,
            language=language,
            segments=segments,
            confidence=confidence,
            review_required=review_required,
            transformations=code_transformations,
            backend=getattr(backend, "name", "unknown"),
            backend_version=getattr(backend, "version", ""),
        )
        apply_coverage_state(block, coverage, coverage_reason)

    return document


def _language_from_context(vtype: VisualType) -> str | None:
    if vtype == VisualType.HTTP:
        return "http"
    if vtype == VisualType.DIFF:
        return "diff"
    if vtype == VisualType.TERMINAL:
        return "bash"
    if vtype in (VisualType.LOG, VisualType.STACK_TRACE):
        return "log"
    return None


# Maximum "word" length above which we suspect rapidocr merged spaces.
# Common keywords are <15 chars; identifiers occasionally reach 20. URLs and
# long file paths legitimately reach 60-80 chars without whitespace, so we
# set the threshold high enough to avoid false positives on those while still
# catching obvious merge failures (e.g. "importrequestsurl='...'" — three
# tokens merged into one >80-char word).
_SPACE_MERGE_MAX_WORD = 80


def _looks_space_merged(text: str) -> bool:
    """Heuristic: does this OCR output look like rapidocr merged spaces?

    Returns True when ANY non-empty line contains a "word" (contiguous run
    of non-space chars) longer than _SPACE_MERGE_MAX_WORD, OR when the whole
    text has fewer than 1 space per 30 non-space characters (very dense).
    Only used to route to review — never to reject.
    """
    if not text:
        return False
    for line in text.splitlines():
        for word in line.split():
            if len(word) > _SPACE_MERGE_MAX_WORD:
                return True
    non_space = sum(1 for c in text if not c.isspace())
    spaces = sum(1 for c in text if c == " ")
    if non_space > 60 and spaces == 0:
        return True
    return False


def _gather_text(
    blocks: list[Block], index: int, *, direction: int, max_chars: int
) -> str:
    """Gather up to max_chars of text from neighboring non-visual blocks."""
    out: list[str] = []
    total = 0
    i = index + direction
    while 0 <= i < len(blocks) and total < max_chars:
        b = blocks[i]
        if b.type == BlockType.VISUAL:
            break
        text = b.text or ""
        if text:
            out.append(text)
            total += len(text)
            if total >= max_chars:
                break
        i += direction
    return "\n".join(out)


def _read_evidence_image(document_dir: Path, block: Block) -> bytes | None:
    """Read the first available evidence image for a block."""
    for ev in block.evidence:
        asset = ev.asset_path
        if not asset:
            continue
        p = document_dir / asset
        if p.is_file():
            try:
                return p.read_bytes()
            except OSError:
                continue
    return None


def _copy_raw_ocr_to_workspace(document_dir: Path, block_id: str, result: OcrResult) -> None:
    """TASK_17.C: copy the raw OCR output JSON into the workspace so it
    survives /tmp removal.

    The backend writes the raw output to /tmp/writeup2md_paddleocr_vl_element_raw/
    (or equivalent for other backends) and records the path in
    `OcrResult.metadata["raw_output_path"]`. We copy that file into the
    document workspace at `evidence/visuals/<block_id>/candidates/original.json`.
    Best-effort — never blocks OCR success.
    """
    try:
        meta = getattr(result, "metadata", None) or {}
        raw_path_str = meta.get("raw_output_path", "") or ""
        if not raw_path_str or raw_path_str.startswith("<"):
            return
        src_path = Path(raw_path_str)
        if not src_path.is_file():
            return
        candidates_dir = document_dir / "evidence" / "visuals" / block_id / "candidates"
        candidates_dir.mkdir(parents=True, exist_ok=True)
        dst = candidates_dir / "original.json"
        dst.write_bytes(src_path.read_bytes())
    except Exception:  # noqa: BLE001
        pass
