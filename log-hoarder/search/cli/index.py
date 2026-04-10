"""CLI entry point for indexing archived session logs."""

from __future__ import annotations

import glob
import os
from collections import deque
from datetime import datetime

from search.adapters.txtai_adapter import TxtaiAdapter
from search.domain.models import LogEntry


def get_log_sample(panedir: str) -> str:
    """Return a short sample of log content for a pane directory.

    TEMPORARY: This sampling approach will be replaced by full-file chunked
    indexing. The design requires every byte of every log to be covered by
    embeddings — this truncation is scaffolding only.
    """
    sample_text: list[str] = []
    log_files = glob.glob(os.path.join(panedir, "*.log"))
    for log_file in log_files:
        with open(log_file, "r", errors="ignore") as f:
            head: list[str] = []
            tail: deque[str] = deque(maxlen=20)
            for i, line in enumerate(f):
                if i < 20:
                    head.append(line)
                tail.append(line)
            sample_text.extend(head)
            sample_text.extend(tail)

    full_sample = "".join(sample_text)
    printable_sample = "".join(
        c for c in full_sample if c.isprintable() or c == "\n"
    )
    return printable_sample[:500]


def run_indexer() -> None:
    log_dir = os.environ.get(
        "LOG_SEARCH_LOG_DIR",
        os.environ.get(
            "TDS_LOG_DIR",
            os.path.expanduser("~/.local/share/log-hoarder"),
        ),
    )
    # LOG_SEARCH_LOG_DIR points directly at the archived/ tree when set.
    # Otherwise derive from the log-hoarder root.
    if os.environ.get("LOG_SEARCH_LOG_DIR"):
        archived_path = log_dir
    else:
        archived_path = os.path.join(log_dir, "archived")

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
    new_entries: list[LogEntry] = []

    for panedir in glob.glob(os.path.join(archived_path, "*/*/*")):
        if not os.path.isdir(panedir):
            continue

        if index.is_indexed(panedir):
            continue

        print(f"Indexing: {panedir}")

        slug = None
        slug_file = os.path.join(panedir, "slug.txt")
        if os.path.exists(slug_file):
            with open(slug_file, "r") as f:
                slug = f.read().strip()

        sample = get_log_sample(panedir)
        if not sample.strip():
            print(f"  Skipping (empty log): {panedir}")
            continue

        timestamp = datetime.fromtimestamp(os.path.getmtime(panedir))

        entry = LogEntry(
            path=panedir,
            timestamp=timestamp,
            slug=slug,
            content_sample=sample,
        )
        new_entries.append(entry)

    if new_entries:
        index.add_entries(new_entries)
        index.save()
        print(f"Indexed {len(new_entries)} sessions.")
    else:
        print("No new logs to index.")


if __name__ == "__main__":
    run_indexer()
