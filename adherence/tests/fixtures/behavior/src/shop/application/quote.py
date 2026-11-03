from shop.domain.tariff import tariff
from shop.ports.store import Store


def quote_tariff(code: int, *, store: Store) -> int:
    quote = tariff(code)
    store.save(quote)
    return quote
