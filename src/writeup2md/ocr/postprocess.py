"""Deterministic post-processors for OCR output.

These never repair syntax or invent content. They only:
- strip editor line numbers when clearly chrome;
- separate terminal commands from outputs when reliable;
- normalize line endings;
- record transformations applied.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..render import _strip_editor_line_numbers


@dataclass
class PostProcessResult:
    selected_text: str
    language: str | None
    segments: list[dict]
    transformations: list[str]
    confidence_delta: float


_PROMPT_RE = re.compile(r"^\s*(?:\$|>|>>)\s?(.*)$")
_PROMPT_PREFIX_RE = re.compile(r"^\s*(?:\$|>|>>)\s?")


def split_terminal_commands(text: str) -> list[dict]:
    """Split a terminal transcript into command/output segments.

    A line beginning with $ or > is treated as a command. Following lines
    until the next prompt are output. This is conservative: if no prompts are
    found, we return a single segment with role 'output'.
    """
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
            text_joined = "\n".join(buffer)
            segments.append({"role": "command", "text": text_joined})
            last_command = text_joined
        elif current_role == "output":
            segments.append(
                {"role": "output", "text": "\n".join(buffer), "command": last_command}
            )
        buffer = []
        current_role = None

    for ln in lines:
        m = _PROMPT_RE.match(ln)
        if m:
            # New command line — flush the previous segment first.
            flush()
            current_role = "command"
            buffer = [m.group(1)]
        else:
            if current_role is None:
                current_role = "output"
            elif current_role == "command":
                # Transition from command to output: flush the command, then
                # start an output segment.
                flush()
                current_role = "output"
            buffer.append(ln)
    flush()
    return segments


def postprocess(
    *,
    raw_text: str,
    visual_type: str,
    language: str | None,
    base_confidence: float,
) -> PostProcessResult:
    """Apply deterministic post-processing. Returns selected_text + metadata."""
    text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    transformations: list[str] = []
    segments: list[dict] = []
    confidence_delta = 0.0

    # Editor line-number stripping (conservative — only when EVERY non-empty
    # line begins with a number followed by whitespace).
    stripped, ln_transforms = _strip_editor_line_numbers(text)
    if ln_transforms:
        text = stripped
        transformations.extend(ln_transforms)

    # Trailing whitespace cleanup.
    new_lines = []
    for ln in text.split("\n"):
        new_lines.append(ln.rstrip())
    text = "\n".join(new_lines)
    if "trailing_whitespace_trimmed" not in transformations:
        # Only record this transformation if we actually changed something.
        if new_lines != raw_text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            transformations.append("trailing_whitespace_trimmed")

    # Terminal command/output splitting.
    if visual_type == "terminal":
        segs = split_terminal_commands(text)
        if segs and any(s["role"] == "command" for s in segs):
            segments = segs
            transformations.append("terminal_command_output_split")
            confidence_delta += 0.02  # small boost for clean structural signal

    # Strip leading/trailing blank lines.
    text = text.strip("\n")

    return PostProcessResult(
        selected_text=text,
        language=language,
        segments=segments,
        transformations=transformations,
        confidence_delta=confidence_delta,
    )
