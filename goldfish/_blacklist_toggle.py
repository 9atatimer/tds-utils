#!/usr/bin/env python3
"""Flip the marker on one line of a state file. Invoked by fzf's space bind.

Usage: _blacklist_toggle.py <state-file> <line>

Reads the state file, replaces the first line equal to <line> with its
toggled form (via `core.toggle_marker_line`), and atomically writes back.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from core import toggle_marker_line  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        return 2
    state_path = Path(argv[1])
    target = argv[2]
    try:
        text = state_path.read_text()
    except OSError:
        return 1
    lines = text.splitlines()
    flipped = False
    out: list[str] = []
    for line in lines:
        if not flipped and line == target:
            out.append(toggle_marker_line(line))
            flipped = True
        else:
            out.append(line)
    tmp = state_path.with_suffix(state_path.suffix + ".tmp")
    tmp.write_text("\n".join(out))
    tmp.replace(state_path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
