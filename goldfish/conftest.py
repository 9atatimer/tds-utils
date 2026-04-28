"""Pytest config: put `goldfish/` on sys.path so `from core import ...` works
regardless of which directory pytest is invoked from.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
