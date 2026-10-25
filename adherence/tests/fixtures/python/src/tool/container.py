from tool.adapters.fs_store import FsStore

from .application.use import close_order


def build() -> FsStore:
    return FsStore("/tmp")
