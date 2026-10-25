from shop.domain import tariff


def test_band_rounds_down() -> None:
    assert tariff._band(25) == 2


def test_tariff_runs() -> None:
    tariff.tariff(3)
