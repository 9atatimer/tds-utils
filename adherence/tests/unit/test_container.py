"""Architect behavior (testing skill): Wiring, with Swap's fake-per-port half.

The composition root builds, in every stage, with every port faked; it
takes an override for every Protocol under ports/; and every port has a
fake to pass it (ARCHITECTURE.ARCH-ADHERENCE.md, Module map: container.py).
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from typing import Protocol, get_args, get_type_hints

import adherence.ports
from adherence.adapters.fakes import FakeCodeModel, FakeRepository
from adherence.container import Stage, build
from adherence.domain.model import CodeLanguage
from adherence.ports.code_model import CodeModelPort
from adherence.ports.repository import RepositoryPort

# Each port: the override build() takes for it, and the fake passed there
# (a port bound per language takes a mapping of fakes).
OVERRIDES: dict[type, tuple[str, object]] = {
    RepositoryPort: ("repository", FakeRepository({})),
    CodeModelPort: ("analyzers", {CodeLanguage.PYTHON: FakeCodeModel()}),
}


def _ports() -> set[type]:
    found: set[type] = set()
    for module in pkgutil.iter_modules(adherence.ports.__path__):
        loaded = importlib.import_module(f"adherence.ports.{module.name}")
        for value in vars(loaded).values():
            if (
                isinstance(value, type)
                and Protocol in value.__mro__[1:]
                and value.__module__ == loaded.__name__
            ):
                found.add(value)
    return found


def _mentions(hint: object, port: type) -> bool:
    """Whether a type hint names the port, at any depth (Mapping[K, Port])."""
    return hint is port or any(_mentions(arg, port) for arg in get_args(hint))


def test_every_port_has_a_fake_and_an_override() -> None:
    """Given every Protocol under ports/, When the fakes and the composition
    root's overrides are listed, Then each port has a fake and an override."""
    ports = _ports()
    hints = get_type_hints(build)

    assert ports, "no ports found; the discovery is broken"
    assert ports == set(OVERRIDES), "a port without a fake, or a fake without a port"
    for port, (name, _fake) in OVERRIDES.items():
        assert name in hints and _mentions(hints[name], port), (
            f"build() takes no override for {port.__name__}"
        )


def test_build_with_every_port_faked_binds_the_fakes(tmp_path: Path) -> None:
    """Given a fake for every port, When the composition root is built for each
    stage, Then every port it binds is the fake passed in."""
    overrides = dict(OVERRIDES.values())

    for stage in Stage:
        built = build(stage, root=str(tmp_path), **overrides)
        for name, fake in overrides.items():
            assert getattr(built, name) is fake, (stage, name)


def test_build_binds_an_analyzer_for_every_measured_language(tmp_path: Path) -> None:
    """Given no analyzer override, When the composition root is built, Then
    every language the suite measures has an analyzer, and TypeScript and
    JavaScript share one, so an import from one to the other resolves."""
    built = build(Stage.LAPTOP, root=str(tmp_path))

    assert set(built.analyzers) == set(CodeLanguage)
    assert (
        built.analyzers[CodeLanguage.TYPESCRIPT]
        is built.analyzers[CodeLanguage.JAVASCRIPT]
    )


def test_build_measures_shell(tmp_path: Path) -> None:
    """Given no analyzer override, When the composition root is built, Then
    shell is a measured language with an analyzer bound, as G11 names it."""
    built = build(Stage.LAPTOP, root=str(tmp_path))

    assert CodeLanguage.SHELL in built.analyzers
