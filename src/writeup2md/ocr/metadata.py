"""OCR backend metadata capture.

Records real-backend provenance: name, versions, device, load/inference
durations, input dimensions, preprocessing/retry flags, raw output path.
Used by doctor --smoke-ocr and by the Golden Set evaluator (TASK_09).

TASK_15 extends this with exact-model-identity fields: `model_repo`,
`model_revision`, `pipeline_version`, `full_pipeline`, `mock_used`,
`rapid_used_as_primary`, `fallback_used`. All new fields are additive
with defaults so existing callers keep working.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class OcrBackendInfo:
    """Metadata about a single OCR inference call.

    All duration fields are in seconds. `raw_output_path` points at the
    file storing the unnormalized model output for audit.

    TASK_15 identity fields:

    - `model_repo`: HuggingFace repo id (e.g. ``PaddlePaddle/PaddleOCR-VL``).
      Empty string when the backend does not load from HuggingFace.
    - `model_revision`: immutable commit SHA the backend actually loaded.
      Empty string when not verified.
    - `pipeline_version`: ``"full"`` (official PaddleOCR pipeline) or
      ``"element"`` (HF transformers element-mode) for PaddleOCR-VL;
      empty string for other backends.
    - `full_pipeline`: True when the backend wraps the official
      PaddleOCR v1 pipeline (layout + recognition + table/formula/chart).
      False for element-only VLM and for non-PaddleOCR-VL backends.
    - `mock_used`: True when the inference was served by the mock
      backend (should never be True for a real-backend run; surfaced
      here so doctor/eval can hard-fail on it).
    - `rapid_used_as_primary`: True when RapidOCR was used as the
      primary recognizer (i.e. the user asked for ``paddleocr-vl`` but
      the resolver silently substituted ``rapid``). Should always be
      False under ``require_exact_backend=True``.
    - `fallback_used`: human-readable description of any fallback
      chain that fired (e.g. ``"paddleocr-vl -> paddleocr-vl-element
      -> rapid"``). Empty string when no fallback.
    """

    backend: str
    backend_version: str
    model_name: str
    device: str
    engine_version: dict[str, str] = field(default_factory=dict)
    load_duration_s: float = 0.0
    inference_duration_s: float = 0.0
    input_dimensions: tuple[int, int] | None = None  # (width, height)
    preprocessing_used: list[str] = field(default_factory=list)
    retry_used: bool = False
    raw_output_path: str | None = None
    is_mock: bool = False
    # TASK_15 identity + fallback provenance.
    model_repo: str = ""
    model_revision: str = ""
    pipeline_version: str = ""  # "full" | "element" | ""
    full_pipeline: bool = False
    mock_used: bool = False
    rapid_used_as_primary: bool = False
    fallback_used: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Tuples are not JSON-serializable by default; convert.
        if d.get("input_dimensions") is not None:
            d["input_dimensions"] = list(d["input_dimensions"])
        return d
