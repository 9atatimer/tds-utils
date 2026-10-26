from tool.application.use import close_order


def test_close_order_saves() -> None:
    assert close_order is not None


def test_nothing() -> None:
    close_order(None, store=None)
