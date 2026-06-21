"""Multi-panel splitting for OCR output (TASK_11).

When a visual block contains multiple panels (terminal command vs output,
HTTP request vs response, diff header vs hunks), we split the text into
labeled segments. The split is STRUCTURAL — based on delimiter lines and
known markers, never on semantic understanding.

Panel labels:
- terminal: `command` (line begins with `$` or `>`), `output` (other lines).
- http: `request_line`, `request_header`, `request_body`, `status_line`,
  `response_header`, `response_body`.
- diff: `file_header`, `hunk_header`, `hunk_content`.
"""

from __future__ import annotations

import re


_TERMINAL_PROMPT_RE = re.compile(r"^\s*(?:\$|>|>>)\s?(.*)$")
_HTTP_REQUEST_LINE_RE = re.compile(r"^\s*(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS) [^ ]+ HTTP/\d", re.MULTILINE)
_HTTP_STATUS_LINE_RE = re.compile(r"^\s*HTTP/\d[\d.]*\s+\d{3}", re.MULTILINE)
_HTTP_HEADER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9\-]*:\s+.+$")
_DIFF_FILE_HEADER_RE = re.compile(r"^(diff --git|index |---|\+\+\+) ")
_DIFF_HUNK_HEADER_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@")


def split_terminal_panels(text: str) -> list[dict]:
    """Split a terminal transcript into command/output segments.

    A line beginning with `$` or `>` is treated as a command. Following
    lines until the next prompt are output. If no prompts are found,
    returns a single segment with role='output'.
    """
    if not text:
        return []
    lines = text.split("\n")
    segments: list[dict] = []
    current_role: str | None = None
    buffer: list[str] = []
    last_command: str | None = None

    def flush() -> None:
        nonlocal buffer, current_role, last_command
        if not buffer and current_role is None:
            return
        if current_role == "command":
            joined = "\n".join(buffer)
            segments.append({"role": "command", "text": joined})
            last_command = joined
        elif current_role == "output":
            segments.append(
                {"role": "output", "text": "\n".join(buffer), "command": last_command}
            )
        buffer = []
        current_role = None

    for ln in lines:
        m = _TERMINAL_PROMPT_RE.match(ln)
        if m:
            flush()
            current_role = "command"
            buffer = [m.group(1)]
        else:
            if current_role is None:
                current_role = "output"
            elif current_role == "command":
                flush()
                current_role = "output"
            buffer.append(ln)
    flush()
    return segments


def split_http_panels(text: str) -> list[dict]:
    """Split an HTTP transcript into request/response panels.

    Detection:
    - A request line (`METHOD path HTTP/\\d`) starts a request.
    - A status line (`HTTP/\\d 200 OK`) starts a response.
    - Headers follow until an empty line.
    - Body follows until the next request/status line or end of text.

    Returns segments with roles: request_line, request_header, request_body,
    status_line, response_header, response_body.
    """
    if not text:
        return []
    lines = text.split("\n")
    segments: list[dict] = []
    state: str | None = None  # "request_line", "request_header", "request_body",
                              # "status_line", "response_header", "response_body"
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer, state
        if state and buffer:
            segments.append({"role": state, "text": "\n".join(buffer)})
        buffer = []

    for ln in lines:
        if _HTTP_REQUEST_LINE_RE.match(ln):
            flush()
            state = "request_line"
            buffer = [ln]
        elif _HTTP_STATUS_LINE_RE.match(ln):
            flush()
            state = "status_line"
            buffer = [ln]
        elif state in ("request_line", "status_line"):
            # First line after start: switch to header mode.
            if ln.strip() == "":
                flush()
                state = "request_body" if state == "request_line" else "response_body"
                buffer = []
            elif _HTTP_HEADER_RE.match(ln):
                flush()
                state = "request_header" if state == "request_line" else "response_header"
                buffer = [ln]
            else:
                # Continuation of the start line — unlikely but possible.
                buffer.append(ln)
        elif state in ("request_header", "response_header"):
            if ln.strip() == "":
                flush()
                state = "request_body" if state == "request_header" else "response_body"
                buffer = []
            elif _HTTP_HEADER_RE.match(ln):
                buffer.append(ln)
            else:
                # Not a header — must be body.
                flush()
                state = "request_body" if state == "request_header" else "response_body"
                buffer = [ln]
        elif state in ("request_body", "response_body"):
            # Stay in body until next request/status line.
            buffer.append(ln)
        else:
            # No state yet — unknown leading content. Treat as response body.
            state = "response_body"
            buffer = [ln]
    flush()
    return segments


def split_diff_panels(text: str) -> list[dict]:
    """Split a diff into file-header / hunk-header / hunk-content panels."""
    if not text:
        return []
    lines = text.split("\n")
    segments: list[dict] = []
    state: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer, state
        if state and buffer:
            segments.append({"role": state, "text": "\n".join(buffer)})
        buffer = []

    for ln in lines:
        if _DIFF_FILE_HEADER_RE.match(ln):
            flush()
            state = "file_header"
            buffer = [ln]
        elif _DIFF_HUNK_HEADER_RE.match(ln):
            flush()
            state = "hunk_header"
            buffer = [ln]
        elif state == "hunk_header":
            flush()
            state = "hunk_content"
            buffer = [ln]
        else:
            if state is None:
                # Unknown leading content — assign to hunk_content.
                state = "hunk_content"
            buffer.append(ln)
    flush()
    return segments


def split_panels(text: str, visual_type: str | None) -> list[dict]:
    """Dispatch to the correct panel splitter based on visual_type."""
    if not text or not visual_type:
        return []
    if visual_type == "terminal":
        return split_terminal_panels(text)
    if visual_type == "http":
        return split_http_panels(text)
    if visual_type == "diff":
        return split_diff_panels(text)
    return []
