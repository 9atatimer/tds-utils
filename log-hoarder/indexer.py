#!/usr/bin/env python3
import os
import glob
from collections import deque
from datetime import datetime
from search.domain.models import LogEntry
from search.app import get_search_index

def get_log_sample(panedir):
    """Return a short sample of log content for a pane directory.

    TEMPORARY: This sampling approach will be replaced by full-file chunked
    indexing (Task 2 in TODO_PLAN.md). The design requires every byte of
    every log to be covered by embeddings -- this 500-char truncation is
    scaffolding only.
    """
    sample_text = []
    log_files = glob.glob(os.path.join(panedir, "*.log"))
    for log_file in log_files:
        with open(log_file, "r", errors="ignore") as f:
            head = []
            tail = deque(maxlen=20)
            for i, line in enumerate(f):
                if i < 20:
                    head.append(line)
                tail.append(line)
            sample_text.extend(head)
            sample_text.extend(tail)
    
    # Strip non-printable characters and truncate
    full_sample = "".join(sample_text)
    printable_sample = "".join(c for c in full_sample if c.isprintable() or c == "\n")
    return printable_sample[:500]  # Increased sample size for better embeddings

def run_indexer():
    log_dir = os.environ.get("TDS_LOG_DIR", os.path.expanduser("~/.local/share/log-hoarder"))
    archived_path = os.path.join(log_dir, "archived")
    
    index = get_search_index()
    new_entries = []

    # Walk through archived/SESSION/WINDOW/PANE/
    for panedir in glob.glob(os.path.join(archived_path, "*/*/*")):
        if not os.path.isdir(panedir):
            continue
            
        # Use a unique identifier for each pane log (the directory path)
        if index.is_indexed(panedir):
            continue
            
        print(f"Indexing: {panedir}")
        
        # Load metadata
        slug = None
        slug_file = os.path.join(panedir, "slug.txt")
        if os.path.exists(slug_file):
            with open(slug_file, "r") as f:
                slug = f.read().strip()
        
        sample = get_log_sample(panedir)
        
        # Use directory mtime as a fallback timestamp
        timestamp = datetime.fromtimestamp(os.path.getmtime(panedir))
        
        entry = LogEntry(
            path=panedir,
            timestamp=timestamp,
            slug=slug,
            content_sample=sample
        )
        new_entries.append(entry)

    if new_entries:
        index.add_entries(new_entries)
        index.save()
        print(f"Successfully indexed {len(new_entries)} new entries.")
    else:
        print("No new logs to index.")

if __name__ == "__main__":
    run_indexer()
