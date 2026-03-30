#!/usr/bin/env python3
import sys
from search.app import get_search_index

def run_search(query):
    index = get_search_index()
    matches = index.search(query, limit=5)
    
    if not matches:
        print("No matches found.")
        return

    print(f"\nTop 5 results for: '{query}'\n")
    for i, match in enumerate(matches, 1):
        entry = match.entry
        timestamp_str = entry.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        slug_display = f"({entry.slug})" if entry.slug else ""
        
        print(f"{i}. [{timestamp_str}] Score: {match.score:.4f} {slug_display}")
        print(f"   Path: {entry.path}")
        print("-" * 20)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f'Usage: {sys.argv[0]} "query text"')
        sys.exit(1)
        
    query = " ".join(sys.argv[1:])
    run_search(query)
