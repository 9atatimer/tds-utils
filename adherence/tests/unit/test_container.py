"""Architect behavior (testing skill): Wiring, with Swap's fake-per-port half.

The composition root builds, in every stage, with every port faked; it
takes an override for every Protocol under ports/; and every port has a
fake to pass it (ARCHITECTURE.ARCH-ADHERENCE.md, Module map: container.py).
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from typing import Protocol, get_type_hints

import adherence.ports
from adherence.adapters.fakes import FakeRepository
from adherence.container import Stage, build
from adherence.ports.repository import RepositoryPort

FAKES: dict[type, object] = {RepositoryPort: FakeRepository({})}
OVERRIDE = {RepositoryPort: "repository"}


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


def test_every_port_has_a_fake_and_an_override() -> None:
    """Given every Protocol under ports/, When the fakes and the composition
    root's overrides are listed, Then each port has a fake and an override."""
    ports = _ports()
    hints = get_type_hints(build)

    assert ports, "no ports found; the discovery is broken"
    assert ports == set(FAKES), "a port without a fake, or a fake without a port"
    for port in ports:
        name = OVERRIDE[port]
        assert name in hints and port in getattr(hints[name], "__args__", ()), (
            f"build() takes no override for {port.__name__}"
        )


def test_build_with_every_port_faked_binds_the_fakes(tmp_path: Path) -> None:
    """Given a fake for every port, When the composition root is built for each
    stage, Then every port it binds is the fake passed in."""
    overrides = {OVERRIDE[port]: fake for port, fake in FAKES.items()}

    for stage in Stage:
        built = build(stage, root=str(tmp_path), **overrides)
        for name, fake in overrides.items():
            assert getattr(built, name) is fake, (stage, name)
