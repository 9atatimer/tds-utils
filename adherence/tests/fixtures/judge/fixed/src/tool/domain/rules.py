"""Pricing rules."""


def price(quantity: int) -> int:
    return quantity * 3


def discount(quantity: int) -> int:
    return quantity // 10
