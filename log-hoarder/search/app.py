import os
from .adapters.txtai_adapter import TxtaiAdapter

def get_search_index():
    """
    Factory function to return the configured search index implementation.
    Defaults to TxtaiAdapter for the MVP.
    """
    log_dir = os.environ.get("TDS_LOG_DIR", os.path.expanduser("~/.local/share/log-hoarder"))
    index_path = os.path.join(log_dir, "search_index")
    
    # In Phase 2, we could check an environment variable to decide 
    # whether to return TxtaiAdapter or SqliteVecAdapter.
    return TxtaiAdapter(index_path=index_path)
