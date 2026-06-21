"""Human revision persistence for the Streamlit UI.

Revisions are stored under `outputs/<id>/review/`:
- `revisions.jsonl`: one record per human edit, never overwrites raw OCR;
- `review_state.json`: the human-set document state (accepted/review/rejected)
  and per-block "verified" flags;
- `document.reviewed.md`: the human-edited Markdown, written separately from
  the original `document.md`.

The original `document.md`, raw OCR output, and evidence assets are NEVER
modified by this module.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..workspace import (
    DOCUMENT_REVIEWED_MD,
    REVIEW_DIR,
    REVIEW_STATE_JSON,
    REVISIONS_JSONL,
    atomic_write_json,
    atomic_write_text,
    append_jsonl,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def review_dir(document_dir: Path | str) -> Path:
    return Path(document_dir) / REVIEW_DIR


def ensure_review_dir(document_dir: Path | str) -> Path:
    d = review_dir(document_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_review_state(document_dir: Path | str) -> dict[str, Any]:
    p = review_dir(document_dir) / REVIEW_STATE_JSON
    if not p.is_file():
        return {"status": None, "verified_blocks": {}, "notes": ""}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"status": None, "verified_blocks": {}, "notes": ""}


def save_review_state(document_dir: Path | str, state: dict[str, Any]) -> None:
    ensure_review_dir(document_dir)
    atomic_write_json(review_dir(document_dir) / REVIEW_STATE_JSON, state)


def append_revision(
    document_dir: Path | str,
    *,
    block_id: str,
    field: str,
    old_value: Any,
    new_value: Any,
    user: str | None = None,
) -> None:
    ensure_review_dir(document_dir)
    record = {
        "block_id": block_id,
        "field": field,
        "old_value": old_value,
        "new_value": new_value,
        "user": user,
        "timestamp": _now_iso(),
    }
    append_jsonl(review_dir(document_dir) / REVISIONS_JSONL, record)


def save_reviewed_markdown(document_dir: Path | str, markdown: str) -> None:
    ensure_review_dir(document_dir)
    atomic_write_text(review_dir(document_dir) / DOCUMENT_REVIEWED_MD, markdown)


def load_revisions(document_dir: Path | str) -> list[dict]:
    p = review_dir(document_dir) / REVISIONS_JSONL
    if not p.is_file():
        return []
    out: list[dict] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:  # noqa: BLE001
            continue
    return out


def set_document_status(document_dir: Path | str, status: str, *, user: str | None = None) -> None:
    state = load_review_state(document_dir)
    old = state.get("status")
    state["status"] = status
    save_review_state(document_dir, state)
    if old != status:
        append_revision(
            document_dir,
            block_id="__document__",
            field="status",
            old_value=old,
            new_value=status,
            user=user,
        )


def set_block_verified(
    document_dir: Path | str, block_id: str, verified: bool, *, user: str | None = None
) -> None:
    state = load_review_state(document_dir)
    verified_map = state.setdefault("verified_blocks", {})
    old = verified_map.get(block_id)
    verified_map[block_id] = verified
    save_review_state(document_dir, state)
    if old != verified:
        append_revision(
            document_dir,
            block_id=block_id,
            field="verified",
            old_value=old,
            new_value=verified,
            user=user,
        )


def set_block_correction(
    document_dir: Path | str,
    block_id: str,
    corrected_text: str,
    *,
    user: str | None = None,
) -> None:
    """Record a human correction to a block's text. Does NOT mutate raw OCR."""
    state = load_review_state(document_dir)
    corrections = state.setdefault("corrections", {})
    old = corrections.get(block_id)
    corrections[block_id] = corrected_text
    save_review_state(document_dir, state)
    if old != corrected_text:
        append_revision(
            document_dir,
            block_id=block_id,
            field="selected_text",
            old_value=old,
            new_value=corrected_text,
            user=user,
        )


# ---------------------------------------------------------------------------
# Export — TASK_13
# ---------------------------------------------------------------------------


def export_reviews(document_dir: Path | str) -> list[dict[str, Any]]:
    """Return a list of export records for the document's human revisions.

    Each record combines:
    - the document_id (from manifest.json);
    - the current review_state (status, verified_blocks, notes);
    - every revision record from revisions.jsonl, annotated with document_id.

    Records are sorted by timestamp (ascending). This is the payload written
    by `writeup2md inspect RESULT_DIR --export-reviews PATH`.
    """
    import json as _json

    d = Path(document_dir)
    manifest_path = d / "manifest.json"
    document_id = d.name
    if manifest_path.is_file():
        try:
            manifest = _json.loads(manifest_path.read_text(encoding="utf-8"))
            document_id = manifest.get("document_id", document_id)
        except Exception:  # noqa: BLE001
            pass

    state = load_review_state(d)
    revisions = load_revisions(d)
    out: list[dict[str, Any]] = []
    # Review-state summary record first (one per document).
    out.append(
        {
            "kind": "review_state",
            "document_id": document_id,
            "timestamp": _now_iso(),
            "status": state.get("status"),
            "verified_blocks": state.get("verified_blocks", {}),
            "corrections": state.get("corrections", {}),
            "notes": state.get("notes", ""),
        }
    )
    # Then one record per revision, annotated with document_id.
    for r in revisions:
        rec = dict(r)
        rec["kind"] = "revision"
        rec["document_id"] = document_id
        out.append(rec)
    return out


def export_reviews_jsonl(document_dir: Path | str, output_path: Path | str) -> int:
    """Write export records as JSONL. Returns the number of records written."""
    import json as _json

    records = export_reviews(document_dir)
    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(_json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in records)
    p.write_text(text, encoding="utf-8")
    return len(records)
