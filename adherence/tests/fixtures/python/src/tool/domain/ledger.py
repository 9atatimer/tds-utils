"""The ledger: the fixture's Domain-driven and Composable flaws."""

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Entry:
    amount: int
    memo: str


def total(entries: list[Entry], weigh: Callable[[Entry], int]) -> int:
    return sum(weigh(e) for e in entries)


def post(entry: Entry, store: "Store") -> None:
    store.save(entry)
