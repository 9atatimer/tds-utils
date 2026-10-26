import os

from tool.domain.rules import Order


class FsStore:
    def __init__(self, root: str) -> None:
        self.root = root

    def save(self, order: Order) -> None:
        home = os.environ["HOME"]
        print(home, "claude-opus", order)
