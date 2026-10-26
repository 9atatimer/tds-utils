"""Rules."""

from dataclasses import dataclass

LIMIT = 3


@dataclass(frozen=True)
class Order:
    total: int
    status: str = "open"

    def is_large(self) -> bool:
        return self.total > LIMIT


def classify(order: Order, *, strict: bool = False) -> str:
    if order.status == "open":
        return "pending"
    return "done"


def unfinished(order: Order) -> int:
    pass
