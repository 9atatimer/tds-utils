from typing import Protocol

from tool.domain.rules import Order


class Store(Protocol):
    def save(self, order: Order) -> None: ...
