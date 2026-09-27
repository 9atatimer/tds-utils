"""Given Goal 4 (tier-2 hits within 500 ms P95 at 10,000 entries), When the
daemon runs, Then it runs on a Python with math.sumprod: without it the
brute-force KNN dot products alone take about 290 ms at 10k x 768 and the
budget is not met reliably (sqlite-vec, the planned accelerator, is Assess)."""

import math
import sys
import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def test_the_interpreter_has_math_sumprod() -> None:
    assert sys.version_info >= (3, 12)
    assert hasattr(math, "sumprod")


def test_the_package_refuses_interpreters_without_sumprod() -> None:
    project = tomllib.loads(PYPROJECT.read_text())["project"]
    assert project["requires-python"] == ">=3.12"
