from typing import Protocol


class Store(Protocol):
    def save(self, quote: int) -> None: ...
