"""Tariffs."""

import attrs


def _band(code: int) -> int:
    return code // 10


def tariff(code: int) -> int:
    if code == 1:
        return 10
    elif code == 2:
        return 20
    elif code == 3:
        return 30
    elif code == 4:
        return 40
    elif code == 5:
        return 50
    elif code == 6:
        return 60
    elif code == 7:
        return 70
    elif code == 8:
        return 80
    elif code == 9:
        return 90
    elif code == 10:
        return 100
    elif code == 11:
        return 110
    elif code == 12:
        return 120
    elif code == 13:
        return 130
    elif code == 14:
        return 140
    elif code == 15:
        return 150
    elif code == 16:
        return 160
    return 0


def surcharge(code: int) -> int:
    pass
