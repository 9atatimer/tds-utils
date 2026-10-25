"""Shipping: the fixture's Composable and Injectable flaws."""

import os
import sys

from tool.adapters.fs_store import FsStore
from tool.domain.rules import Order
from tool.ports.store import Store


def ship(order: Order, store: Store, payload: dict) -> Order:
    store.save(order)
    return order


def restock(order: Order, *, store: Store) -> Order:
    FsStore(os.environ["HOME"]).save(order)
    print(sys.argv)
    return order
