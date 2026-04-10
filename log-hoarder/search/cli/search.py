"""CLI entry point for semantic search over session logs."""

from __future__ import annotations

import os
import sys

from search.adapters.txtai_adapter import TxtaiAdapter


def run_search(query: str) -> None:
    index_path = os.environ.get(
        "LOG_SEARCH_INDEX_DIR",
        os.path.join(
            os.environ.get(
                "TDS_LOG_DIR",
                os.path.expanduser("~/.local/share/log-hoarder"),
            ),
            "search_index",
        ),
    )

    index = TxtaiAdapter(index_path=index_path)
    matches = index.search(query, limit=10)

    if not matches:
        return

    for match in matches:
        entry = match.entry
        timestamp_str = entry.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        slug_display = entry.slug or ""

        # Output format: SESSION_PATH  SCORE  TIMESTAMP  SLUG
        # One line per result, parseable by shell scripts and fzf.
        print(f"{entry.path}\t{match.score:.4f}\t{timestamp_str}\t{slug_display}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m search.cli.search \"query text\"", file=sys.stderr)
        sys.exit(1)

    query = " ".join(sys.argv[1:])
    run_search(query)
