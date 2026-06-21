"""Shared pytest fixtures and helpers."""

from __future__ import annotations

import sys
from pathlib import Path

# Make `src/` importable without requiring installation.
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
