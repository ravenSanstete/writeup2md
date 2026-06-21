"""Streamlit UI launcher — populated in TASK_06."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def launch_ui(result_root: Path | str, port: int = 8501) -> None:
    """Launch the Streamlit review UI as a subprocess."""
    root = Path(result_root)
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(Path(__file__).parent / "ui" / "app.py"),
        "--server.port",
        str(port),
        "--",
        str(root),
    ]
    # Block until Streamlit exits.
    try:
        subprocess.run(cmd, check=False)
    except KeyboardInterrupt:
        pass
