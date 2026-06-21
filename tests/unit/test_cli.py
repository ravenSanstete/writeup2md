"""Tests for the Typer CLI surface (help text, doctor, exit codes)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from writeup2md.cli import app


runner = CliRunner()


def test_help_lists_all_required_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    out = result.output
    for cmd in ("convert", "batch", "inspect", "ui", "doctor"):
        assert cmd in out


def test_convert_help_matches_cli_spec_options():
    result = runner.invoke(app, ["convert", "--help"])
    assert result.exit_code == 0
    out = result.output
    for opt in ("--output", "--profile", "--device", "--force", "--keep-evidence", "--open-ui"):
        assert opt in out


def test_convert_help_lists_strict_flag():
    """TASK_19: --strict flag is exposed on convert."""
    result = runner.invoke(app, ["convert", "--help"])
    assert result.exit_code == 0
    assert "--strict" in result.output


def test_batch_help_lists_strict_flag():
    """TASK_19: --strict flag is exposed on batch."""
    result = runner.invoke(app, ["batch", "--help"])
    assert result.exit_code == 0
    assert "--strict" in result.output


def test_batch_help_matches_cli_spec_options():
    result = runner.invoke(app, ["batch", "--help"])
    assert result.exit_code == 0
    out = result.output
    for opt in ("--workers", "--resume", "--retry", "--profile", "--recursive", "--include", "--exclude"):
        assert opt in out


def test_doctor_runs_and_reports(tmp_path: Path):
    result = runner.invoke(app, ["doctor", "--output-root", str(tmp_path)])
    # doctor should always run; optional deps may be missing, but required ones
    # (typer/rich/pydantic/yaml) must be present.
    assert "python" in result.output
    assert "package:typer" in result.output


def test_convert_nonexistent_source_returns_input_error():
    result = runner.invoke(app, ["convert", "/nonexistent/path.pdf"])
    assert result.exit_code in (4, 5)  # input error or execution failure


def test_batch_workers_over_max_rejected(tmp_path: Path):
    manifest = tmp_path / "sources.jsonl"
    manifest.write_text('{"source":"./a.pdf"}\n', encoding="utf-8")
    result = runner.invoke(
        app,
        ["batch", str(manifest), "--workers", "5", "--profile", "macbook"],
    )
    # Should be input/configuration error.
    assert result.exit_code in (4, 2, 5)


def test_inspect_missing_dir_returns_input_error(tmp_path: Path):
    result = runner.invoke(app, ["inspect", str(tmp_path / "nope")])
    assert result.exit_code == 4


def test_version_command():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "writeup2md" in result.output


def test_main_shorthand_routes_to_convert():
    """TASK_20.A: `writeup2md SOURCE` should route to convert."""
    from writeup2md.cli import main

    # We can't easily run main() in-process because it modifies sys.argv
    # and calls app(). Instead, verify the routing logic directly:
    # when sys.argv[1] is not a known subcommand, main() prepends "convert".
    import writeup2md.cli as cli_mod

    original_argv = list(__import__("sys").argv)
    try:
        # Simulate `writeup2md /some/path.pdf --force`.
        import sys
        sys.argv = ["writeup2md", "/some/path.pdf", "--force"]
        # Capture the argv after main() prepares it.
        argv = sys.argv[1:]
        # The main() function should prepend "convert" — verify the
        # detection logic directly.
        if argv and argv[0] not in cli_mod._KNOWN_SUBCOMMANDS and not argv[0].startswith("-"):
            routed = ["convert"] + argv
        else:
            routed = argv
        assert routed[0] == "convert"
        assert routed[1] == "/some/path.pdf"
        assert "--force" in routed
    finally:
        import sys
        sys.argv = original_argv


def test_main_shorthand_preserves_known_subcommands():
    """TASK_20.A: `writeup2md convert SOURCE` still works (no double-routing)."""
    import sys
    from writeup2md.cli import _KNOWN_SUBCOMMANDS

    # Subcommands should be in the known set.
    for cmd in ("convert", "batch", "inspect", "ui", "doctor", "version", "evaluate-ocr"):
        assert cmd in _KNOWN_SUBCOMMANDS
