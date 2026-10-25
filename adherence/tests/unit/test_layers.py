"""domain/declaration: the [layers] table and the layer each unit is in.

A declaration assigns a directory, a file or a region of a file to a layer
(DESIGN.ARCH-ADHERENCE.md, Units and layers); every covered unit is in
exactly one layer, so the most specific assignment wins: a region over a
file, a literal path over a glob, a longer glob over a shorter one.
"""

from __future__ import annotations

import time

import pytest

from adherence.domain.declaration import (
    Declaration,
    DeclarationUnreadable,
    layer_of,
    matches,
    parse_declaration,
)
from adherence.domain.model import Layer, Region

LAYERS = b"""
[layers]
application = ["src/tool/**"]
domain = ["src/tool/domain/**"]
adapters = ["src/tool/adapters/*.py"]
"composition root" = ["src/tool/container.py"]
test = ["tests/**"]
regions = [
    { file = "bin/tool.py", layer = "domain", lines = [3, 5] },
    { file = "bin/marked.py" },
]
"""


def _declaration() -> Declaration:
    declaration = parse_declaration(LAYERS)
    assert isinstance(declaration, Declaration), declaration
    return declaration


@pytest.mark.parametrize(
    ("path", "layer"),
    [
        ("src/tool/domain/rules.py", Layer.DOMAIN),
        ("src/tool/domain/deep/more.py", Layer.DOMAIN),
        ("src/tool/application/use.py", Layer.APPLICATION),
        ("src/tool/adapters/fs.py", Layer.ADAPTERS),
        ("src/tool/adapters/sub/fs.py", Layer.APPLICATION),
        ("src/tool/container.py", Layer.COMPOSITION_ROOT),
        ("tests/test_use.py", Layer.TEST),
        ("notes/scratch.py", None),
    ],
)
def test_layer_of_a_file_is_its_most_specific_assignment(
    path: str, layer: Layer | None
) -> None:
    """Given globs and literal paths per layer, When a file's layer is asked,
    Then the most specific assignment wins, and an uncovered file has none."""
    assert layer_of(path, None, _declaration()) is layer


def test_layer_of_a_line_in_a_region_is_the_regions_layer() -> None:
    """Given a line-range region of a file, When a line's layer is asked,
    Then a line inside it is in the region's layer and one outside is not."""
    declaration = _declaration()

    assert layer_of("bin/tool.py", 4, declaration) is Layer.DOMAIN
    assert layer_of("bin/tool.py", 6, declaration) is None


def test_layer_of_honors_regions_found_by_marker() -> None:
    """Given a file whose regions come from its markers, When a line's layer
    is asked with those regions, Then the marker region decides it."""
    found = (Region("bin/marked.py", 10, 20, Layer.ADAPTERS),)

    assert layer_of("bin/marked.py", 12, _declaration(), found) is Layer.ADAPTERS
    assert _declaration().layers.marker_files == ("bin/marked.py",)


@pytest.mark.parametrize(
    ("text", "named"),
    [
        (b'[layers]\nservices = ["src/**"]\n', "services"),
        (b'[layers]\ndomain = "src/**"\n', "domain"),
        (b'[layers]\nregions = [{ layer = "domain", lines = [1, 2] }]\n', "file"),
        (
            b'[layers]\nregions = [{ file = "a", layer = "domain", lines = [5, 2] }]\n',
            "lines",
        ),
        (b'[layers]\nregions = [{ file = "a", layer = "domain" }]\n', "lines"),
    ],
)
def test_parse_declaration_with_malformed_layers_is_unreadable(
    text: bytes, named: str
) -> None:
    """Given a [layers] table that names no real layer or a malformed region,
    When it is parsed, Then it is DeclarationUnreadable naming the problem."""
    loaded = parse_declaration(text)

    assert isinstance(loaded, DeclarationUnreadable)
    assert named in loaded.reason


def test_matches_a_glob_of_repeated_double_stars_promptly() -> None:
    """Given a declaration glob of many `**/` segments, which the declaration's
    author controls, When it is matched against a deep path that it misses,
    Then the answer comes promptly: no backtracking blow-up holds the run.

    A backtracking matcher takes seconds here (about 3s at nine segments on
    an M1, growing about 14x per segment); a linear one takes microseconds,
    so the half-second bound leaves a wide margin for a slow runner."""
    started = time.perf_counter()

    assert not matches("**/" * 9 + "x", "a/" * 30 + "y")
    assert time.perf_counter() - started < 0.5


@pytest.mark.parametrize(
    ("pattern", "path", "expected"),
    [
        ("src/**", "src/a/b.py", True),
        ("src/**", "src", False),
        ("**/test_*.py", "test_a.py", True),
        ("**/test_*.py", "x/y/test_a.py", True),
        ("src/*.py", "src/a/b.py", False),
        ("src/**/b.py", "src/b.py", True),
        ("src/**/b.py", "src/a/c/b.py", True),
        ("a?c/d", "abc/d", True),
        ("a?c/d", "a/c/d", False),
    ],
)
def test_matches_follows_glob_rules(pattern: str, path: str, expected: bool) -> None:
    """Given a layer pattern and a path, When they are matched, Then `**`
    crosses directories and `*` and `?` stay within one."""
    assert matches(pattern, path) is expected
