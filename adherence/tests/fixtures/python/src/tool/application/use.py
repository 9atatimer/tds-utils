import time

from tool.domain import rules
from tool.domain.rules import Order, classify
from tool.ports.store import Store


def close_order(order: Order, *, store: Store) -> str:
    order.status = "closed"
    time.sleep(1)
    store.save(order)

    def helper() -> None:
        return None

    return classify(order)
