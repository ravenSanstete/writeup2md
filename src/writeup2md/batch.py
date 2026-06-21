"""Batch processing with durable, resumable state.

Resource behavior (per docs/08_MACBOOK_EXECUTION.md):
- default workers: 1, hard max: 2 in the MacBook profile (enforced by caller);
- one source processed at a time when workers=1;
- state persisted after each source so an interrupted batch resumes;
- deterministic skip when content_sha256 + config_sha256 match an existing
  completed output;
- OCR concurrency remains 1 regardless of worker count.

TASK_12 enhancements:
- source freshness check: detect when a file or URL has changed since the
  cached conversion;
- partial-state recovery: detect and recover from interrupted batch runs
  that left a partial document directory;
- `--force-refresh` and `--max-age SECONDS` flags on the batch command.

Input formats supported:
- directory: every .pdf, .html, .htm file (optionally recursive);
- newline-delimited URL list (.txt or .urls): one URL per line;
- JSONL manifest: one JSON object per line, each with a "source" key and
  optional "id", "tags", "profile".
- mixed JSONL: local paths and URLs.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from .config import Profile, WriteupConfig, build_config, enforce_macbook_limits
from .pipeline import ConversionResult, convert_source


@dataclass
class BatchSourceItem:
    source: str
    explicit_id: str | None = None
    tags: list[str] = field(default_factory=list)
    profile_override: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class BatchSourceResult:
    item: BatchSourceItem
    status: str  # accepted | review | rejected | failed | skipped
    document_id: str | None = None
    document_dir: Path | None = None
    error: str | None = None
    skipped: bool = False


@dataclass
class BatchSummary:
    total: int = 0
    accepted: int = 0
    review: int = 0
    rejected: int = 0
    failed: int = 0
    skipped: int = 0
    results: list[BatchSourceResult] = field(default_factory=list)


def parse_batch_input(
    input_path: Path,
    *,
    recursive: bool = False,
    include: str | None = None,
    exclude: str | None = None,
) -> list[BatchSourceItem]:
    """Parse a batch input (directory, URL list, or JSONL manifest)."""
    if not input_path.exists():
        raise FileNotFoundError(f"batch input not found: {input_path}")

    if input_path.is_dir():
        return _parse_directory(input_path, recursive=recursive, include=include, exclude=exclude)
    if input_path.is_file():
        suffix = input_path.suffix.lower()
        text = input_path.read_text(encoding="utf-8")
        if suffix in (".jsonl", ".json"):
            return _parse_jsonl(text)
        if suffix in (".txt", ".urls", ".list") or _looks_like_url_list(text):
            return _parse_url_list(text)
        # Heuristic: if the first non-blank line starts with {, treat as JSONL.
        for line in text.splitlines():
            if line.strip():
                if line.strip().startswith("{"):
                    return _parse_jsonl(text)
                break
        return _parse_url_list(text)
    raise ValueError(f"unsupported batch input: {input_path}")


def _looks_like_url_list(text: str) -> bool:
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith(("http://", "https://")):
            return True
        return False
    return False


def _parse_url_list(text: str) -> list[BatchSourceItem]:
    items: list[BatchSourceItem] = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        items.append(BatchSourceItem(source=s))
    return items


def _parse_jsonl(text: str) -> list[BatchSourceItem]:
    items: list[BatchSourceItem] = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        try:
            obj = json.loads(s)
        except json.JSONDecodeError as e:
            raise ValueError(f"invalid JSONL line: {s!r}: {e}") from e
        if not isinstance(obj, dict) or "source" not in obj:
            raise ValueError(f"JSONL entry missing 'source' field: {s!r}")
        items.append(
            BatchSourceItem(
                source=str(obj["source"]),
                explicit_id=obj.get("id"),
                tags=list(obj.get("tags", []) or []),
                profile_override=obj.get("profile"),
                extra={k: v for k, v in obj.items() if k not in {"source", "id", "tags", "profile"}},
            )
        )
    return items


def _parse_directory(
    directory: Path,
    *,
    recursive: bool,
    include: str | None,
    exclude: str | None,
) -> list[BatchSourceItem]:
    import fnmatch

    items: list[BatchSourceItem] = []
    iterator: Iterator[Path]
    if recursive:
        iterator = sorted(directory.rglob("*"))
    else:
        iterator = sorted(directory.glob("*"))
    for p in iterator:
        if not p.is_file():
            continue
        suffix = p.suffix.lower()
        if suffix not in (".pdf", ".html", ".htm"):
            continue
        name = p.name
        if include and not fnmatch.fnmatch(name, include):
            continue
        if exclude and fnmatch.fnmatch(name, exclude):
            continue
        items.append(BatchSourceItem(source=str(p)))
    return items


# ---------------------------------------------------------------------------
# Batch state persistence
# ---------------------------------------------------------------------------


def _batch_state_path(output_root: Path) -> Path:
    return output_root / "batch_state.json"


def _batch_manifest_path(output_root: Path) -> Path:
    return output_root / "batch_manifest.jsonl"


def _batch_summary_path(output_root: Path) -> Path:
    return output_root / "batch_summary.json"


def _batch_failures_path(output_root: Path) -> Path:
    return output_root / "batch_failures.jsonl"


def load_batch_state(output_root: Path) -> dict[str, dict]:
    """Load existing batch state (source -> {status, document_id, content_sha, config_sha})."""
    p = _batch_state_path(output_root)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save_batch_state(output_root: Path, state: dict[str, dict]) -> None:
    """Atomically write batch state."""
    from .workspace import atomic_write_json

    atomic_write_json(_batch_state_path(output_root), state)


def _append_batch_manifest(output_root: Path, record: dict) -> None:
    from .workspace import append_jsonl

    append_jsonl(_batch_manifest_path(output_root), record)


def _append_failure(output_root: Path, record: dict) -> None:
    from .workspace import append_jsonl

    append_jsonl(_batch_failures_path(output_root), record)


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------


def run_batch(
    *,
    input_path: Path,
    output_root: Path,
    config: WriteupConfig,
    recursive: bool = False,
    include: str | None = None,
    exclude: str | None = None,
    retry: int = 0,
    workers: int | None = None,
    force_refresh: bool = False,
    max_age: int | None = None,
) -> BatchSummary:
    """Run a batch. Returns a BatchSummary.

    TASK_12:
    - `force_refresh=True` bypasses cache freshness checks.
    - `max_age=SECONDS` treats cached results as fresh if younger than SECONDS.
    """
    if workers is not None:
        config.pipeline.workers = workers
    enforce_macbook_limits(config)
    if config.pipeline.workers > 2:
        raise ValueError(
            f"workers={config.pipeline.workers} exceeds MacBook maximum of 2"
        )

    output_root.mkdir(parents=True, exist_ok=True)
    items = parse_batch_input(
        input_path, recursive=recursive, include=include, exclude=exclude
    )

    state = load_batch_state(output_root) if config.pipeline.resume else {}
    summary = BatchSummary(total=len(items))

    # Status routing directories (we use the manifest to track; subdirs are
    # optional convenience). We create the subdirs so the layout matches the
    # spec but we do NOT move outputs (they stay under <document_id>).
    for sub in ("accepted", "review", "rejected", "failed"):
        (output_root / sub).mkdir(exist_ok=True)

    # Sequential processing (workers default = 1).
    if config.pipeline.workers == 1:
        for item in items:
            result = _process_one(
                item=item,
                output_root=output_root,
                config=config,
                state=state,
                retry=retry,
                force_refresh=force_refresh,
                max_age=max_age,
            )
            summary.results.append(result)
            if result.skipped:
                summary.skipped += 1
            elif result.status == "accepted":
                summary.accepted += 1
            elif result.status == "review":
                summary.review += 1
            elif result.status == "rejected":
                summary.rejected += 1
            else:
                summary.failed += 1
            _save_batch_state(output_root, state)
    else:
        # workers == 2: use threads for I/O-bound source orchestration only.
        # OCR concurrency remains 1 (enforced by the inference lock).
        from concurrent.futures import ThreadPoolExecutor, as_completed

        max_workers = config.pipeline.workers
        state_lock = threading.Lock()
        results_by_index: dict[int, BatchSourceResult] = {}

        def _do(idx_item: tuple[int, BatchSourceItem]) -> BatchSourceResult:
            idx, item = idx_item
            with state_lock:
                local_state = dict(state)
            r = _process_one(
                item=item,
                output_root=output_root,
                config=config,
                state=local_state,
                retry=retry,
                force_refresh=force_refresh,
                max_age=max_age,
            )
            return idx, r, local_state

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [pool.submit(_do, (i, it)) for i, it in enumerate(items)]
            for fut in as_completed(futures):
                idx, r, local_state = fut.result()
                results_by_index[idx] = r
                with state_lock:
                    state.update(local_state)
                    _save_batch_state(output_root, state)
        for i in range(len(items)):
            r = results_by_index[i]
            summary.results.append(r)
            if r.skipped:
                summary.skipped += 1
            elif r.status == "accepted":
                summary.accepted += 1
            elif r.status == "review":
                summary.review += 1
            elif r.status == "rejected":
                summary.rejected += 1
            else:
                summary.failed += 1

    # Write final summary.
    from .workspace import atomic_write_json

    atomic_write_json(
        _batch_summary_path(output_root),
        {
            "total": summary.total,
            "accepted": summary.accepted,
            "review": summary.review,
            "rejected": summary.rejected,
            "failed": summary.failed,
            "skipped": summary.skipped,
            "results": [
                {
                    "source": r.item.source,
                    "status": r.status,
                    "document_id": r.document_id,
                    "document_dir": str(r.document_dir) if r.document_dir else None,
                    "error": r.error,
                    "skipped": r.skipped,
                }
                for r in summary.results
            ],
        },
    )
    return summary


def _process_one(
    *,
    item: BatchSourceItem,
    output_root: Path,
    config: WriteupConfig,
    state: dict[str, dict],
    retry: int,
    force_refresh: bool = False,
    max_age: int | None = None,
) -> BatchSourceResult:
    """Process one source. Updates `state` in place.

    TASK_12:
    - `force_refresh=True` bypasses cache freshness checks.
    - `max_age=SECONDS` treats cached results as fresh if younger than SECONDS.
    - Detects and recovers partial state from interrupted batch runs.
    """
    # Determine effective config (profile override).
    eff_config = config
    if item.profile_override:
        try:
            prof = Profile(item.profile_override)
        except ValueError:
            return BatchSourceResult(
                item=item, status="failed", error=f"unknown profile: {item.profile_override}"
            )
        eff_config = build_config(prof)
        eff_config.pipeline.workers = config.pipeline.workers
        eff_config.pipeline.resume = config.pipeline.resume
        enforce_macbook_limits(eff_config)

    # Compute deterministic key for skip check.
    canonical_key = _canonical_key(item.source)
    existing = state.get(canonical_key)

    # TASK_12: freshness check. If the cached result is still fresh, skip.
    # If the cached result is stale (file edited, URL changed, --force-refresh),
    # we re-process. If a partial state exists (interrupted mid-write), we
    # recover before re-processing.
    if existing and existing.get("status") in ("accepted", "review", "rejected") and not force_refresh:
        if (
            existing.get("content_sha256") and
            existing.get("config_sha256") == eff_config.config_sha256()
        ):
            doc_id = existing.get("document_id")
            # TASK_20: directory name is now <slug>-<short_hash>, not the
            # full doc_id. Look it up via the .index.json mapping.
            doc_dir_path = _resolve_document_dir(output_root, doc_id, item.source)
            if doc_id and doc_dir_path and (doc_dir_path / "manifest.json").is_file():
                # Check freshness.
                fresh = check_source_freshness(
                    item.source,
                    existing,
                    max_age=max_age,
                )
                if fresh:
                    return BatchSourceResult(
                        item=item,
                        status=existing["status"],
                        document_id=doc_id,
                        document_dir=doc_dir_path,
                        skipped=True,
                    )
                # Stale: fall through to re-process. Clean up partial state
                # if any (the existing dir is complete, so we just remove it
                # to avoid duplicate IDs).
                # Actually, the document_id is deterministic, so re-processing
                # will overwrite. No cleanup needed.
            else:
                # Partial state: manifest.json missing. Recover.
                if doc_dir_path:
                    _recover_partial_state(doc_dir_path)

    # Also recover partial state for any document_id we're about to (re)create.
    # We don't know the doc_id ahead of time (it's derived from content hash),
    # but if `existing` had one and it's partial, recover it.
    if existing and existing.get("document_id"):
        doc_dir_path = _resolve_document_dir(output_root, existing["document_id"], item.source)
        if doc_dir_path and doc_dir_path.is_dir() and not (doc_dir_path / "manifest.json").is_file():
            _recover_partial_state(doc_dir_path)

    # Retry loop.
    last_error: str | None = None
    attempts = max(1, retry + 1)
    for attempt in range(attempts):
        try:
            result: ConversionResult = convert_source(
                source=item.source,
                output_root=output_root,
                config=eff_config,
                force=force_refresh,  # TASK_12: propagate force_refresh
                keep_evidence=eff_config.pipeline.retain_raw_evidence,
            )
        except FileNotFoundError as e:
            last_error = str(e)
            # Don't retry missing files.
            break
        except Exception as e:  # noqa: BLE001
            last_error = f"{type(e).__name__}: {e}"
            continue

        status = result.status.value
        state[canonical_key] = {
            "status": status,
            "document_id": result.document_id,
            "document_dir": str(result.document_dir),
            "content_sha256": _extract_content_sha(result),
            "config_sha256": eff_config.config_sha256(),
            "source": item.source,
            "attempts": attempt + 1,
            # TASK_12: record capture time for max_age checks.
            "captured_at": _extract_captured_at(result),
        }
        _append_batch_manifest(
            output_root,
            {
                "source": item.source,
                "status": status,
                "document_id": result.document_id,
                "document_dir": str(result.document_dir),
                "attempt": attempt + 1,
            },
        )
        return BatchSourceResult(
            item=item,
            status=status,
            document_id=result.document_id,
            document_dir=result.document_dir,
        )

    # All attempts failed.
    state[canonical_key] = {
        "status": "failed",
        "document_id": None,
        "source": item.source,
        "config_sha256": eff_config.config_sha256(),
        "error": last_error,
    }
    _append_failure(
        output_root,
        {"source": item.source, "error": last_error, "attempts": attempts},
    )
    _append_batch_manifest(
        output_root,
        {"source": item.source, "status": "failed", "error": last_error},
    )
    return BatchSourceResult(item=item, status="failed", error=last_error)


# ---------------------------------------------------------------------------
# TASK_12: freshness + partial-recovery helpers
# ---------------------------------------------------------------------------


def check_source_freshness(
    source: str,
    cached_state: dict[str, Any],
    *,
    max_age: int | None = None,
) -> bool:
    """Return True if the cached result is still fresh.

    Rules:
    - If `max_age` is set and the cached `captured_at` is younger than
      `max_age` seconds, return True.
    - For local files: re-hash the file and compare to `cached_state["content_sha256"]`.
    - For URLs: return True (we don't HEAD-check by default to avoid network
      calls; users can use `--force-refresh` to force re-processing).
    - On any error (file missing, etc.), return False (conservative — re-process).
    """
    # max_age check first.
    if max_age is not None:
        captured_at = cached_state.get("captured_at")
        if captured_at:
            try:
                from datetime import datetime, timezone

                # Parse ISO 8601 with optional Z suffix.
                ts = captured_at.replace("Z", "+00:00")
                dt = datetime.fromisoformat(ts)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                age_s = (datetime.now(timezone.utc) - dt).total_seconds()
                if age_s < max_age:
                    return True
            except Exception:  # noqa: BLE001
                pass  # fall through to content check

    # URL sources: default to fresh (no network call).
    if source.startswith(("http://", "https://")):
        return True

    # Local file: re-hash and compare.
    cached_sha = cached_state.get("content_sha256")
    if not cached_sha:
        return False
    try:
        from .models import content_sha256_bytes

        p = Path(source)
        if not p.is_file():
            return False
        actual_sha = content_sha256_bytes(p.read_bytes())
        return actual_sha == cached_sha
    except Exception:  # noqa: BLE001
        return False


def _recover_partial_state(document_dir: Path) -> bool:
    """Detect and recover partial state in a document directory.

    A partial state is one where `manifest.json` or `document.json` is
    missing but other files exist (interrupted mid-write).

    Recovery: move the partial directory to
    `<document_dir>.partial.<timestamp>` for forensic inspection. We do NOT
    silently delete user data.

    Returns True if recovery happened, False otherwise.
    """
    if not document_dir.is_dir():
        return False
    manifest = document_dir / "manifest.json"
    document_json = document_dir / "document.json"
    if manifest.is_file() and document_json.is_file():
        return False  # complete — nothing to recover
    # Partial. Move aside.
    timestamp = int(time.time())
    partial_dir = document_dir.parent / f"{document_dir.name}.partial.{timestamp}"
    try:
        document_dir.rename(partial_dir)
        return True
    except OSError:
        return False


def _extract_captured_at(result: ConversionResult) -> str | None:
    """Read captured_at from the document manifest."""
    try:
        manifest_path = result.document_dir / "manifest.json"
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            return manifest.get("captured_at")
    except Exception:  # noqa: BLE001
        pass
    return None


def _canonical_key(source: str) -> str:
    from .models import canonicalize_source

    return canonicalize_source(source)


def _resolve_document_dir(output_root: Path, doc_id: str | None, source: str) -> Path | None:
    """TASK_20: resolve a document directory by either the new
    human-readable name (preferred) or the legacy opaque hash.

    Looks up `outputs/.index.json` for the mapping from
    `<slug>-<short_hash>` to full `<document_id>`. Falls back to the
    legacy `output_root / doc_id` path for backward compatibility.
    """
    if not doc_id:
        return None
    # Legacy path: output_root / doc_id (still works for old outputs).
    legacy = output_root / doc_id
    if legacy.is_dir():
        return legacy
    # New path: look up via .index.json.
    index_path = output_root / ".index.json"
    if index_path.is_file():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
            for dir_name, entry in index.items():
                if entry.get("document_id") == doc_id:
                    return output_root / dir_name
        except Exception:  # noqa: BLE001
            pass
    # Last resort: scan output_root for a directory whose manifest.json
    # has this document_id. Slow but correct.
    try:
        for child in output_root.iterdir():
            if not child.is_dir():
                continue
            manifest_path = child / "manifest.json"
            if not manifest_path.is_file():
                continue
            try:
                m = json.loads(manifest_path.read_text(encoding="utf-8"))
                if m.get("document_id") == doc_id:
                    return child
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass
    return None


def _extract_content_sha(result: ConversionResult) -> str | None:
    try:
        manifest_path = result.document_dir / "manifest.json"
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            return manifest.get("content_sha256")
    except Exception:  # noqa: BLE001
        pass
    return None


def simulate_interruption_after(output_root: Path, n: int) -> None:
    """Test helper: truncate batch_state to keep only the first n entries.

    Used to verify resume behavior. This is only called from tests.
    """
    state = load_batch_state(output_root)
    keys = list(state.keys())[:n]
    truncated = {k: state[k] for k in keys}
    _save_batch_state(output_root, truncated)
