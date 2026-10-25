"""`adhere measure --json` through the composition root over the task-061
fixture: real git, the real Python analyzer, and the complexity and
duplication tooling the composition root binds (lizard, jscpd), with the
records and the radar overridden by the fake until task-059's markdown
adapter lands. The task-061 done check: the Behavior-driven, Complete and
Radar-true qualities print their findings. Skipped, never faked, when
either tool is not installed."""

from __future__ import annotations

import functools
import importlib.util
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from adherence.adapters.fakes import FakeRecords
from adherence.cli.main import main
from adherence.container import build
from adherence.domain.qualities import Quality
from adherence.domain.records import (
    Behavior,
    DesignRecords,
    Radar,
    RadarEntry,
    Ring,
    UseCase,
)
from adherence.domain.target import Head

ENGINE = Path(__file__).resolve().parents[2]
FIXTURE = ENGINE / "tests" / "fixtures" / "behavior"
JSCPD = ENGINE / "node_modules" / ".bin" / "jscpd"
DESIGN = "docs/design/DESIGN.SHOP.md"
ARCHITECTURE = "docs/design/ARCHITECTURE.SHOP.md"
RADAR_PATH = "docs/TECH_RADAR.md"
RECORDS = DesignRecords(
    behaviors=(
        Behavior("A tariff is looked up", DESIGN, 40),
        Behavior("A tariff is quoted", DESIGN, 41),
    ),
    surface=(
        UseCase("A tariff is looked up", "tariff", ARCHITECTURE, 60),
        UseCase("A tariff is quoted", "quote_tariff", ARCHITECTURE, 61),
    ),
)
RADAR = Radar(entries=(RadarEntry("attrs", Ring.ADOPT, RADAR_PATH, 12),))
TARIFF = "src/shop/domain/tariff.py"
LEGACY = "src/shop/adapters/legacy_tariff.py"
TESTS = "tests/test_tariff.py"

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("lizard") is None or not JSCPD.is_file(),
    reason="lizard (uv sync) and jscpd (npm ci --ignore-scripts) must be installed",
)


def _measure(root: Path) -> tuple[int, str]:
    head = Head.working_tree()
    builder = functools.partial(
        build, records=FakeRecords({head: RECORDS}, radar={head: RADAR})
    )
    result = CliRunner().invoke(
        main, ["measure", "--root", str(root), "--json"], obj=builder
    )
    return result.exit_code, result.output


def _found(quality: dict[str, list[dict[str, str]]]) -> set[tuple[str, str]]:
    return {(f["check"], f["path"]) for f in quality["findings"]}


def test_measure_json_over_the_fixture_prints_the_three_qualities() -> None:
    """Given the fixture, records naming a behavior no test keeps, and a radar
    holding the domain's import, When `adhere measure --json` runs, Then the
    Behavior-driven, Complete and Radar-true checks run and each prints the
    finding the fixture plants for it."""
    code, output = _measure(FIXTURE)

    assert code == 0, output
    document = json.loads(output)
    qualities = {q["quality"]: q for q in document["qualities"]}
    behavior = qualities[Quality.BEHAVIOR_DRIVEN.value]
    complete = qualities[Quality.COMPLETE.value]
    radar = qualities[Quality.RADAR_TRUE.value]
    assert set(behavior["ran"]) == {"Kept test", "Public surface", "Real assertion"}
    assert set(complete["ran"]) == {"Stub", "Complexity", "Duplication"}
    assert set(radar["ran"]) == {"Dependency", "Edge only"}
    assert _found(behavior) == {
        ("Kept test", DESIGN),
        ("Public surface", TESTS),
        ("Real assertion", TESTS),
    }
    assert {
        ("Stub", TARIFF),
        ("Complexity", TARIFF),
        ("Complexity", LEGACY),
        ("Duplication", TARIFF),
    } <= _found(complete)
    assert _found(radar) == {("Dependency", LEGACY), ("Edge only", TARIFF)}
    covered = {c["check"] for c in document["coverage"] if c["check"]}
    assert {"Then asserted", "Done", "Hand-rolled"} <= covered
