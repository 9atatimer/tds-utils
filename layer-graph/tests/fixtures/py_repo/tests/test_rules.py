from app.domain import rules

def test_limit() -> None:
    assert rules.LIMIT == 3
