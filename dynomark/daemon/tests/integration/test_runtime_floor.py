"""Given the daemon's source uses PEP 695 type-parameter syntax
(``class Page[T]``, ``def paginate[T]`` in app/pages.py), When it is
installed, Then the package refuses an interpreter older than 3.12, which
would fail to import it with a SyntaxError instead of a clear refusal.

(The floor was first set for ``math.sumprod`` in the brute-force KNN; KNN
now runs in sqlite-vec, and the syntax is what keeps the floor.)"""

import sys
import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def test_the_interpreter_meets_the_floor() -> None:
    assert sys.version_info >= (3, 12)


def test_the_package_refuses_interpreters_below_the_floor() -> None:
    project = tomllib.loads(PYPROJECT.read_text())["project"]
    assert project["requires-python"] == ">=3.12"
