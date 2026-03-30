#!/usr/bin/env python3
import os
import glob
from datetime import datetime
from search.domain.models import LogEntry
from search.app import get_search_index

def get_log_sample(panedir):
    """Same sampling logic as log_brander."""
    sample_text = []
    log_files = glob.glob(os.path.join(panedir, "*.log"))
    for log_file in log_files:
        with open(log_file, "r", errors="ignore") as f:
            lines = f.readlines()
            # Sample first and last 20 lines
            sample_text.extend(lines[:20])
            sample_text.extend(lines[-20:])
    
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
