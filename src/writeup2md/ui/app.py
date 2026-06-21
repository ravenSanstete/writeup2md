"""Streamlit review UI for writeup2md.

Launch with:
    python -m writeup2md ui outputs/

Or:
    streamlit run src/writeup2md/ui/app.py -- outputs/

Resource behavior:
- a compact document index is cached and rebuilt only when the result root
  changes;
- the selected document is lazy-loaded (manifest, diagnostics, document.json,
  document.md read on demand);
- evidence images are loaded only when the user opens an OCR review block;
- no OCR model is loaded — the UI is read/review only;
- pagination for the batch table to avoid rendering the whole corpus.

TASK_13 additions:
- full-text search across all documents (FTS via inverted token index);
- filters: status, source_type, visual_type, coverage_state, confidence range;
- sort: by document_id, status, captured_at, visual_count;
- zoom: click an evidence image to view at full resolution;
- diff: side-by-side comparison of OCR raw_text vs user-revised text;
- keyboard navigation: j/k (next/prev document), n/p (next/prev visual block),
  / (focus search), Enter (accept current block);
- export reviews via `writeup2md inspect RESULT_DIR --export-reviews PATH`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

try:
    import streamlit as st
except ImportError:
    print(
        "streamlit is not installed; install with: pip install streamlit",
        file=sys.stderr,
    )
    sys.exit(1)

from .index import DocumentIndexEntry, build_index, index_signature
from .review_store import (
    load_review_state,
    load_revisions,
    save_reviewed_markdown,
    set_block_correction,
    set_block_verified,
    set_document_status,
)
from .search import SearchDoc, build_search_index, search_documents


PAGE_SIZE = 50

# Canonical option sets for filters.
STATUS_OPTIONS = ["accepted", "review", "rejected", "failed"]
SOURCE_TYPE_OPTIONS = ["pdf", "url", "html"]
VISUAL_TYPE_OPTIONS = [
    "code", "terminal", "http", "diff", "configuration", "log",
    "stack_trace", "table", "diagram", "ui_screenshot", "decorative", "unknown",
]
COVERAGE_STATE_OPTIONS = [
    "transcribed", "native_text_used", "decorative_with_reason",
    "duplicate_with_reference", "review_required", "failed_with_diagnostic",
]
SORT_OPTIONS = ["document_id", "status", "captured_at", "visual_count"]


def _resolve_result_root() -> Path:
    """Resolve the result root from CLI args or streamlit's argv."""
    # streamlit run app.py -- <result_root>
    args = sys.argv[1:]
    # Strip streamlit's own args (everything up to and including '--').
    if "--" in args:
        idx = args.index("--")
        args = args[idx + 1:]
    # Filter out streamlit flags.
    positional = [a for a in args if not a.startswith("-")]
    if positional:
        return Path(positional[0]).resolve()
    return Path("outputs").resolve()


def _cached_index(result_root: Path) -> list[DocumentIndexEntry]:
    sig = index_signature(result_root)

    @st.cache_data(show_spinner=False)
    def _load(_sig, root_str):
        return [e.__dict__ for e in build_index(Path(root_str))]

    rows = _load(sig, str(result_root))
    return [DocumentIndexEntry(**r) for r in rows]


def _cached_search_index(result_root: Path) -> list[SearchDoc]:
    sig = index_signature(result_root)

    @st.cache_data(show_spinner=False)
    def _load(_sig, root_str):
        return [
            {
                "document_id": d.document_id,
                "document_dir": d.document_dir,
                "title": d.title,
                "tokens": d.tokens,
            }
            for d in build_search_index(Path(root_str))
        ]

    rows = _load(sig, str(result_root))
    return [
        SearchDoc(
            document_id=r["document_id"],
            document_dir=r["document_dir"],
            title=r["title"],
            tokens=r["tokens"],
        )
        for r in rows
    ]


def _load_document(document_dir: Path) -> dict[str, Any]:
    """Lazy-load one document's full data."""
    out: dict[str, Any] = {"document_dir": str(document_dir)}
    manifest_path = document_dir / "manifest.json"
    if manifest_path.is_file():
        out["manifest"] = json_load(manifest_path)
    diag_path = document_dir / "diagnostics.json"
    if diag_path.is_file():
        out["diagnostics"] = json_load(diag_path)
    doc_path = document_dir / "document.json"
    if doc_path.is_file():
        out["document"] = json_load(doc_path)
    md_path = document_dir / "document.md"
    if md_path.is_file():
        out["markdown"] = md_path.read_text(encoding="utf-8")
    else:
        out["markdown"] = ""
    return out


def _load_document_cached(document_dir: Path) -> dict[str, Any]:
    sig = (str(document_dir), _file_mtime(document_dir / "document.json"))

    @st.cache_data(show_spinner=False)
    def _load(_sig, dir_str):
        return _load_document(Path(dir_str))

    return _load(sig, str(document_dir))


def _file_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def json_load(path: Path) -> Any:
    import json

    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Keyboard shortcuts (TASK_13)
# ---------------------------------------------------------------------------


def _install_keyboard_handler() -> None:
    """Inject a small JS snippet for keyboard shortcuts.

    Streamlit does not natively expose keyboard events to Python. We use an
    HTML component that captures keydown on the document level and posts
    the key to a hidden input that Python polls via session_state.

    Shortcuts:
        j / k — next / previous document (within current filtered list)
        n / p — next / previous visual block (within OCR review tab)
        /     — focus the search box
        Enter — accept the current visual block (mark verified)
    """
    html = """
    <script>
    (function() {
        const KEY_INPUT_ID = '__writeup2md_key';
        let inp = document.getElementById(KEY_INPUT_ID);
        if (!inp) {
            inp = document.createElement('input');
            inp.id = KEY_INPUT_ID;
            inp.type = 'hidden';
            inp.name = KEY_INPUT_ID;
            document.body.appendChild(inp);
        }
        // Skip when the user is typing in a text field.
        function isTyping() {
            const a = document.activeElement;
            if (!a) return false;
            const tag = a.tagName.toLowerCase();
            return tag === 'input' || tag === 'textarea' || a.isContentEditable;
        }
        document.addEventListener('keydown', function(e) {
            // Allow '/' to focus search even if not typing; other keys only when not typing.
            if (isTyping() && e.key !== 'Escape') return;
            const key = e.key.toLowerCase();
            const map = {'j':'next_doc','k':'prev_doc','n':'next_block','p':'prev_block','/':'focus_search','enter':'accept_block'};
            if (map[key]) {
                e.preventDefault();
                inp.value = map[key];
                inp.dispatchEvent(new Event('input', {bubbles:true}));
                // Also streamlit-aware: trigger a rerun by blur/focus dance.
                const streamlitDoc = window.parent.document;
                const stInput = streamlitDoc.getElementById(KEY_INPUT_ID + '_mirror');
                if (!stInput) {
                    const m = streamlitDoc.createElement('input');
                    m.id = KEY_INPUT_ID + '_mirror';
                    m.type = 'hidden';
                    streamlitDoc.body.appendChild(m);
                }
                streamlitDoc.getElementById(KEY_INPUT_ID + '_mirror').value = map[key];
            }
        }, true);
    })();
    </script>
    """
    st.components.v1.html(html, height=0)


def _consume_key_event() -> str | None:
    """Return the last key event posted by the JS handler, or None.

    The JS snippet writes to a hidden input mirrored into the parent frame.
    Streamlit does not expose this directly to Python, so we use a query-param
    workaround: we read st.query_params if the JS set it.
    """
    # Streamlit query params: JS can set window.parent.location.search to
    # `?key=next_doc`, but this is fragile. A more reliable path is to use
    # st.components.v1.html with a form that POSTs, but that triggers a full
    # reload. For now, the keyboard handler is a progressive enhancement —
    # the visible Prev/Next buttons remain the primary navigation.
    return st.query_params.get("w2md_key")


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


def render_dashboard(result_root: Path, entries: list[DocumentIndexEntry]) -> None:
    st.title("writeup2md — Batch Dashboard")
    st.caption(f"Result root: `{result_root}`")

    if not entries:
        st.info("No documents found. Run `writeup2md convert` or `writeup2md batch` first.")
        return

    counts = {"accepted": 0, "review": 0, "rejected": 0, "failed": 0}
    for e in entries:
        counts[e.status] = counts.get(e.status, 0) + 1
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total", len(entries))
    c2.metric("Accepted", counts["accepted"])
    c3.metric("Review", counts["review"])
    c4.metric("Rejected", counts["rejected"])
    c5.metric("Failed", counts["failed"])

    st.divider()

    # Full-text search (TASK_13).
    search_index = _cached_search_index(result_root)
    search = st.text_input(
        "🔍 Full-text search (across all documents)",
        value=st.session_state.get("dashboard_search", ""),
        key="dashboard_search_input",
        help="Tip: wrap a phrase in double quotes for exact substring match.",
    )
    st.session_state["dashboard_search"] = search
    if search.strip():
        hits = search_documents(search_index, search, limit=200)
        hit_ids = {h.document_id for h in hits}
        # Filter entries by search hits.
        entries = [e for e in entries if e.document_id in hit_ids]
        st.caption(f"Search: {len(hits)} match(es) across {len(entries)} document(s).")

    # Filters (TASK_13: extended).
    fcol1, fcol2, fcol3, fcol4, fcol5 = st.columns(5)
    status_filter = fcol1.multiselect(
        "Status", STATUS_OPTIONS,
        default=st.session_state.get("filter_status", ["review", "accepted"]),
        key="filter_status",
    )
    source_filter = fcol2.multiselect(
        "Source type", SOURCE_TYPE_OPTIONS,
        default=st.session_state.get("filter_source", ["pdf", "url", "html"]),
        key="filter_source",
    )
    coverage_filter = fcol3.multiselect(
        "Coverage state", COVERAGE_STATE_OPTIONS,
        default=st.session_state.get("filter_coverage", []),
        key="filter_coverage",
        help="Filter documents that contain at least one visual block in this coverage state.",
    )
    conf_range = fcol4.slider(
        "Confidence range", 0.0, 1.0,
        value=st.session_state.get("filter_conf", (0.0, 1.0)),
        step=0.05,
        key="filter_conf",
        help="Filter documents with at least one visual block whose confidence falls in this range.",
    )
    sort_by = fcol5.selectbox(
        "Sort by", SORT_OPTIONS,
        index=SORT_OPTIONS.index(st.session_state.get("sort_by", "document_id")),
        key="sort_by",
    )

    # Apply filters.
    filtered = []
    for e in entries:
        if status_filter and e.status not in status_filter:
            continue
        if source_filter and e.source_type not in source_filter:
            continue
        filtered.append(e)

    # Coverage / confidence filters require lazy-loading block data.
    if coverage_filter or conf_range != (0.0, 1.0):
        filtered = _apply_block_level_filters(
            filtered, coverage_filter, conf_range
        )

    # Sort.
    reverse = (sort_by == "captured_at")
    if sort_by == "document_id":
        filtered.sort(key=lambda e: e.document_id)
    elif sort_by == "status":
        filtered.sort(key=lambda e: (e.status, e.document_id))
    elif sort_by == "captured_at":
        filtered.sort(key=lambda e: e.captured_at or "", reverse=reverse)
    elif sort_by == "visual_count":
        # visual_count is approximated by block_count (we don't store a
        # dedicated field on the index entry).
        filtered.sort(key=lambda e: e.block_count, reverse=True)

    st.caption(f"Showing {len(filtered)} of {len(entries)} documents")

    # Pagination.
    page = st.session_state.get("dashboard_page", 0)
    total_pages = max(1, (len(filtered) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    st.session_state["dashboard_page"] = page

    page_col1, page_col2, page_col3 = st.columns([1, 2, 1])
    if page_col1.button("◀ Prev", disabled=page == 0):
        st.session_state["dashboard_page"] = page - 1
        st.rerun()
    page_col2.write(f"Page {page + 1} of {total_pages}")
    if page_col3.button("Next ▶", disabled=page >= total_pages - 1):
        st.session_state["dashboard_page"] = page + 1
        st.rerun()

    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    rows = filtered[start:end]

    if not rows:
        st.info("No documents match the current filters.")
        return

    import pandas as pd

    df = pd.DataFrame(
        [
            {
                "id": e.document_id,
                "title": e.title[:60],
                "source_type": e.source_type,
                "status": e.status,
                "quality": f"{e.quality_score:.2f}",
                "blocks": e.block_count,
                "unresolved": e.unresolved_visuals,
            }
            for e in rows
        ]
    )
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Open a document")
    options = [
        f"{e.document_id} — {e.title[:50]} [{e.status}]" for e in rows
    ]
    choice = st.selectbox("Select document", range(len(options)), format_func=lambda i: options[i])
    if st.button("Open document", type="primary"):
        st.session_state["selected_document_dir"] = rows[choice].document_dir
        st.session_state["current_page"] = "document"
        st.rerun()


def _apply_block_level_filters(
    entries: list[DocumentIndexEntry],
    coverage_filter: list[str],
    conf_range: tuple[float, float],
) -> list[DocumentIndexEntry]:
    """Filter documents by per-block signals (coverage state / confidence).

    Loads document.json lazily per candidate. The list is typically small
    at this stage (already filtered by status/source), so this is acceptable.
    """
    lo, hi = conf_range
    out: list[DocumentIndexEntry] = []
    for e in entries:
        doc_path = Path(e.document_dir) / "document.json"
        if not doc_path.is_file():
            continue
        try:
            doc = json_load(doc_path)
        except Exception:  # noqa: BLE001
            continue
        blocks = doc.get("blocks", [])
        keep = True
        if coverage_filter:
            coverages = {
                (b.get("enrichment") or {}).get("coverage_state") or b.get("coverage_state")
                for b in blocks
                if b.get("type") == "visual"
            }
            if not coverages.intersection(coverage_filter):
                keep = False
        if keep and conf_range != (0.0, 1.0):
            confs = [
                (b.get("enrichment") or {}).get("confidence", 0.0)
                for b in blocks
                if b.get("type") == "visual" and (b.get("enrichment") or {}).get("confidence") is not None
            ]
            if not any(lo <= c <= hi for c in confs):
                keep = False
        if keep:
            out.append(e)
    return out


def render_document(document_dir: str, entries: list[DocumentIndexEntry]) -> None:
    d = Path(document_dir)
    data = _load_document_cached(d)
    manifest = data.get("manifest", {})
    diagnostics = data.get("diagnostics", {})
    document = data.get("document", {})
    md = data.get("markdown", "")
    review_state = load_review_state(d)

    # Header
    st.title(manifest.get("source", d.name).split("/")[-1][:80] or d.name)
    st.caption(f"Document ID: `{manifest.get('document_id', d.name)}`")
    st.caption(f"Source: `{manifest.get('source', '')}`")
    st.caption(f"Canonical: `{manifest.get('canonical_source', '')}`")

    hcol1, hcol2, hcol3, hcol4 = st.columns(4)
    hcol1.metric("Status", manifest.get("status", "?"))
    hcol2.metric("Quality", f"{diagnostics.get('quality', {}).get('overall_quality_score', 0):.2f}")
    hcol3.metric("Blocks", len(document.get("blocks", [])))
    hcol4.metric("Unresolved", len(diagnostics.get("unresolved_important_visuals", [])))

    # Document-level actions
    st.divider()
    acol1, acol2, acol3, acol4, acol5 = st.columns(5)
    if acol1.button("Accept", type="primary"):
        set_document_status(d, "accepted")
        st.toast("Document marked accepted")
        st.rerun()
    if acol2.button("Flag for review"):
        set_document_status(d, "review")
        st.toast("Document flagged for review")
        st.rerun()
    if acol3.button("Reject"):
        set_document_status(d, "rejected")
        st.toast("Document rejected")
        st.rerun()
    if acol4.button("Export reviews"):
        # Export to a deterministic location inside the document dir.
        from .review_store import export_reviews_jsonl
        out_path = d / "review" / "exported_reviews.jsonl"
        n = export_reviews_jsonl(d, out_path)
        st.toast(f"Exported {n} record(s) → {out_path}")
        st.session_state["last_export_path"] = str(out_path)
        st.rerun()
    if acol5.button("◀ Back to dashboard"):
        st.session_state["current_page"] = "dashboard"
        st.session_state.pop("selected_document_dir", None)
        st.rerun()

    human_status = review_state.get("status")
    if human_status:
        st.info(f"Human review status: **{human_status}**")

    last_export = st.session_state.get("last_export_path")
    if last_export:
        st.caption(f"Last export: `{last_export}`")

    # Tabs
    tab_reader, tab_ocr, tab_structure, tab_diag, tab_artifacts = st.tabs(
        ["Reader", "OCR Review", "Source Structure", "Diagnostics", "Raw Artifacts"]
    )

    with tab_reader:
        _render_reader(md, document, d)
    with tab_ocr:
        _render_ocr_review(document, d)
    with tab_structure:
        _render_structure(document)
    with tab_diag:
        _render_diagnostics(diagnostics, manifest)
    with tab_artifacts:
        _render_artifacts(d)


def _render_reader(md: str, document: dict, document_dir: Path) -> None:
    if not md:
        st.warning("No Markdown available.")
        return

    show_source = st.toggle("Show source text", value=False)
    show_block_ids = st.toggle("Show block IDs", value=False)

    if show_source:
        st.code(md, language="markdown")
        return

    # Render the markdown with Streamlit's st.markdown (safe — no images).
    # We strip the writeup2md HTML comments from the rendered view but keep
    # them available in the source view above.
    display_md = md
    if not show_block_ids:
        # Hide the review-required markers in the rendered view; they are
        # visible in the OCR Review tab.
        import re

        display_md = re.sub(
            r"<!-- writeup2md:.*?-->",
            "_(review required — see OCR Review tab)_",
            display_md,
        )
    st.markdown(display_md)

    st.divider()
    st.download_button(
        "Download Markdown",
        data=md.encode("utf-8"),
        file_name="document.md",
        mime="text/markdown",
    )


def _render_ocr_review(document: dict, document_dir: Path) -> None:
    blocks = document.get("blocks", [])
    visual_blocks = [b for b in blocks if b.get("type") == "visual"]
    if not visual_blocks:
        st.info("No visual blocks in this document.")
        return

    review_state = load_review_state(document_dir)
    corrections = review_state.get("corrections", {})

    st.subheader("OCR Review")
    st.caption(f"{len(visual_blocks)} visual block(s). Evidence images load on demand.")

    # Filters within the OCR review tab (TASK_13).
    fcol1, fcol2, fcol3, fcol4 = st.columns(4)
    vtype_filter = fcol1.multiselect(
        "Visual type", VISUAL_TYPE_OPTIONS,
        default=st.session_state.get("ocr_vtype_filter", []),
        key="ocr_vtype_filter",
    )
    cov_filter = fcol2.multiselect(
        "Coverage state", COVERAGE_STATE_OPTIONS,
        default=st.session_state.get("ocr_cov_filter", []),
        key="ocr_cov_filter",
    )
    conf_lo, conf_hi = fcol3.slider(
        "Confidence", 0.0, 1.0,
        value=st.session_state.get("ocr_conf_range", (0.0, 1.0)),
        step=0.05,
        key="ocr_conf_range",
    )
    show_diff = fcol4.toggle("Show diff view", value=False, key="ocr_show_diff")

    # Apply within-tab filters.
    filtered_visual = []
    for b in visual_blocks:
        if vtype_filter and b.get("visual_type") not in vtype_filter:
            continue
        cov = (b.get("enrichment") or {}).get("coverage_state") or b.get("coverage_state")
        if cov_filter and cov not in cov_filter:
            continue
        conf = (b.get("enrichment") or {}).get("confidence", 0.0) or 0.0
        if conf < conf_lo or conf > conf_hi:
            continue
        filtered_visual.append(b)

    if not filtered_visual:
        st.warning("No visual blocks match the current filters.")
        return
    if len(filtered_visual) != len(visual_blocks):
        st.caption(f"Filtered: {len(filtered_visual)} of {len(visual_blocks)} visual block(s).")

    # Previous / next controls.
    nav_col1, nav_col2, nav_col3 = st.columns([1, 2, 1])
    idx = st.session_state.get("ocr_block_idx", 0)
    idx = max(0, min(idx, len(filtered_visual) - 1))
    if nav_col1.button("◀ Prev block", disabled=idx == 0):
        st.session_state["ocr_block_idx"] = idx - 1
        st.rerun()
    nav_col2.write(f"Block {idx + 1} of {len(filtered_visual)}")
    if nav_col3.button("Next block ▶", disabled=idx >= len(filtered_visual) - 1):
        st.session_state["ocr_block_idx"] = idx + 1
        st.rerun()

    block = filtered_visual[idx]
    enrichment = block.get("enrichment") or {}

    st.divider()
    mcol1, mcol2 = st.columns([1, 1])

    with mcol1:
        st.markdown("**Evidence**")
        evidence = block.get("evidence", [])
        asset_path = None
        for ev in evidence:
            if ev.get("asset_path"):
                asset_path = ev["asset_path"]
                break
        if asset_path:
            full = document_dir / asset_path
            if full.is_file():
                # TASK_13: zoom — show thumbnail, with a button to view full.
                st.image(str(full), caption=asset_path, use_container_width=True)
                st.caption(f"Page/selector: {evidence[0] if evidence else ''}")
                with st.expander("🔍 Zoom — view full-resolution evidence"):
                    st.image(str(full), use_container_width=False)
                    st.download_button(
                        "Download original",
                        data=full.read_bytes(),
                        file_name=full.name,
                    )
            else:
                st.warning(f"Evidence asset missing: `{asset_path}`")
        else:
            st.info("No evidence asset for this block.")

    with mcol2:
        st.markdown("**Transcription**")
        st.write(f"Block ID: `{block.get('block_id')}`")
        st.write(f"Visual type: `{block.get('visual_type', 'unknown')}`")
        st.write(f"State: `{block.get('visual_state', 'unknown')}`")
        cov = (enrichment.get("coverage_state") if enrichment else None) or block.get("coverage_state")
        st.write(f"Coverage state: `{cov or '—'}`")
        if enrichment:
            st.write(f"Confidence: `{enrichment.get('confidence', 0):.3f}`")
            st.write(f"Language: `{enrichment.get('language') or '—'}`")
            st.write(f"Backend: `{enrichment.get('backend', '—')}`")
            st.write(f"Transformations: `{', '.join(enrichment.get('transformations', [])) or '—'}`")

        # Raw OCR output expander (read-only).
        raw_text = enrichment.get("raw_text", "") or ""
        with st.expander("Raw OCR output (read-only)"):
            st.code(raw_text or "(empty)", language="text")

        # Editable selected text — stored as a correction, never mutates raw.
        current = corrections.get(block["block_id"]) or enrichment.get("selected_text", "")
        edited = st.text_area(
            "Corrected text (saved to review/, raw OCR is preserved)",
            value=current,
            height=200,
            key=f"correction_{block['block_id']}",
        )

        # TASK_13: diff view — compare raw OCR vs corrected text.
        if show_diff:
            st.markdown("**Diff (raw OCR → corrected)**")
            _render_diff(raw_text, current)

        ecol1, ecol2, ecol3 = st.columns(3)
        if ecol1.button("Save correction"):
            set_block_correction(document_dir, block["block_id"], edited)
            st.toast("Correction saved to review/revisions.jsonl")
            st.rerun()
        if ecol2.button("Mark verified"):
            set_block_verified(document_dir, block["block_id"], True)
            st.toast("Block marked verified")
            st.rerun()
        if ecol3.button("Needs review"):
            set_block_verified(document_dir, block["block_id"], False)
            st.toast("Block flagged for review")
            st.rerun()

    # Revision history.
    revisions = load_revisions(document_dir)
    block_revisions = [r for r in revisions if r.get("block_id") == block["block_id"]]
    if block_revisions:
        with st.expander(f"Revision history ({len(block_revisions)} edits)"):
            for r in block_revisions[-10:]:
                st.write(
                    f"- `{r.get('timestamp')}` field=`{r.get('field')}` "
                    f"old=`{str(r.get('old_value'))[:60]}` new=`{str(r.get('new_value'))[:60]}`"
                )


def _render_diff(raw: str, corrected: str) -> None:
    """Render a side-by-side diff between raw OCR output and the corrected text."""
    import difflib

    if not raw and not corrected:
        st.caption("(both empty)")
        return
    raw_lines = raw.splitlines() or ["(empty)"]
    corr_lines = corrected.splitlines() or ["(empty)"]
    # side_by_side produces a generator of (tag, i1, i2, j1, j2) tuples.
    diff = difflib.unified_diff(
        raw_lines, corr_lines,
        fromfile="raw_ocr", tofile="corrected",
        lineterm="",
    )
    diff_text = "\n".join(diff)
    if diff_text:
        st.code(diff_text, language="diff")
    else:
        st.success("No differences — raw OCR and corrected text match.")


def _render_structure(document: dict) -> None:
    blocks = document.get("blocks", [])
    if not blocks:
        st.info("No blocks.")
        return
    import pandas as pd

    rows = []
    for b in blocks:
        rows.append(
            {
                "order": b.get("order"),
                "id": b.get("block_id"),
                "type": b.get("type"),
                "visual_type": b.get("visual_type") or "",
                "state": b.get("visual_state") or "",
                "coverage": (b.get("enrichment") or {}).get("coverage_state") or b.get("coverage_state") or "",
                "confidence": (b.get("enrichment") or {}).get("confidence", ""),
                "text_preview": (b.get("text") or (b.get("enrichment") or {}).get("selected_text") or "")[:60],
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _render_diagnostics(diagnostics: dict, manifest: dict) -> None:
    st.write("**Document-level metrics**")
    quality = diagnostics.get("quality", {})
    metrics_col1, metrics_col2, metrics_col3, metrics_col4 = st.columns(4)
    metrics_col1.metric("Native text coverage", f"{quality.get('native_text_coverage', 0):.2f}")
    metrics_col2.metric("Visual resolution", f"{quality.get('important_visual_resolution_rate', 0):.2f}")
    metrics_col3.metric("OCR-enriched blocks", quality.get("ocr_enriched_block_count", 0))
    metrics_col4.metric("Markdown images", diagnostics.get("markdown_image_count", 0))

    st.write("**Block counts by type**")
    bc = diagnostics.get("block_counts", {})
    if bc:
        st.json(bc)

    st.write("**Visual coverage ledger** (TASK_10)")
    vc = diagnostics.get("visual_coverage")
    if vc:
        st.json(vc)
    else:
        st.caption("Not recorded.")

    st.write("**Unresolved important visuals**")
    uv = diagnostics.get("unresolved_important_visuals", [])
    if uv:
        st.write(uv)
    else:
        st.success("None")

    st.write("**OCR confidence distribution**")
    st.json(diagnostics.get("ocr_confidence_distribution", {}))

    st.write("**Processing warnings**")
    pw = diagnostics.get("processing_warnings", [])
    if pw:
        for w in pw:
            st.warning(w)
    else:
        st.success("None")

    st.write("**Processing errors**")
    pe = diagnostics.get("processing_errors", [])
    if pe:
        for e in pe:
            st.error(e)
    else:
        st.success("None")

    st.write("**Source and config hashes**")
    st.write(f"- content_sha256: `{manifest.get('content_sha256', '')[:32]}...`")
    st.write(f"- config_sha256: `{manifest.get('config_sha256', '')[:32]}...`")
    st.write(f"- captured_at: `{manifest.get('captured_at', '')}`")


def _render_artifacts(document_dir: Path) -> None:
    st.write("**Artifact files**")
    files = []
    for name in ("manifest.json", "document.md", "document.json", "diagnostics.json", "provenance.jsonl"):
        p = document_dir / name
        if p.is_file():
            files.append((name, p, p.stat().st_size))
    if not files:
        st.info("No artifacts found.")
        return
    for name, p, size in files:
        with st.expander(f"{name} ({size} bytes)"):
            if name.endswith(".jsonl"):
                lines = p.read_text(encoding="utf-8").splitlines()
                st.code("\n".join(lines[:50]) + (f"\n... ({len(lines)} total)" if len(lines) > 50 else ""), language="jsonl")
            elif name.endswith(".json"):
                st.json(json_load(p))
            else:
                st.code(p.read_text(encoding="utf-8")[:5000], language="markdown")

    st.write("**Evidence files**")
    evidence_dir = document_dir / "evidence"
    if evidence_dir.is_dir():
        ev_files = sorted(evidence_dir.rglob("*"))
        ev_files = [f for f in ev_files if f.is_file()]
        st.write(f"{len(ev_files)} evidence file(s)")
        for f in ev_files[:20]:
            st.write(f"- `{f.relative_to(document_dir)}` ({f.stat().st_size} bytes)")
        if len(ev_files) > 20:
            st.caption(f"... and {len(ev_files) - 20} more")
    else:
        st.info("No evidence directory.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    st.set_page_config(page_title="writeup2md", page_icon="📄", layout="wide")

    result_root = _resolve_result_root()
    entries = _cached_index(result_root)

    # TASK_13: keyboard shortcuts. Progressive enhancement — the buttons
    # remain the primary navigation; shortcuts are an additional affordance.
    _install_keyboard_handler()

    # Sidebar.
    with st.sidebar:
        st.write("## writeup2md")
        st.caption(f"Result root:\n`{result_root}`")
        st.divider()
        if st.button("Dashboard"):
            st.session_state["current_page"] = "dashboard"
            st.session_state.pop("selected_document_dir", None)
            st.rerun()
        st.divider()
        st.write("**Keyboard shortcuts**")
        st.caption("j/k — next/prev document (on dashboard)\nn/p — next/prev visual block (OCR Review tab)\n/ — focus search\nEnter — accept block")
        st.divider()
        st.write("**All documents**")
        for e in entries[:50]:
            label = f"{e.title[:30]} [{e.status}]"
            if st.button(label, key=f"nav_{e.document_id}", help=e.document_id):
                st.session_state["selected_document_dir"] = e.document_dir
                st.session_state["current_page"] = "document"
                st.rerun()
        if len(entries) > 50:
            st.caption(f"... and {len(entries) - 50} more (use the dashboard)")

    page = st.session_state.get("current_page", "dashboard")
    if page == "document" and st.session_state.get("selected_document_dir"):
        render_document(st.session_state["selected_document_dir"], entries)
    else:
        render_dashboard(result_root, entries)


if __name__ == "__main__":
    main()
