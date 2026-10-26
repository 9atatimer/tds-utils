"""`adhere measure --json` through the composition root over the task-061
fixture: every adapter the composition root binds -- real git, the real
Python analyzer, the markdown records adapter over the fixture's design
records and radar, and the complexity and duplication tooling (lizard,
jscpd). The task-061 done check: every target-level quality runs, and the
Behavior-driven, Complete and Radar-true qualities print their findings.
Skipped, never faked, when either tool is not installed."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from adherence.cli.main import main
from adherence.domain.qualities import Quality

ENGINE = Path(__file__).resolve().parents[2]
FIXTURE = ENGINE / "tests" / "fixtures" / "behavior"
JSCPD = ENGINE / "node_modules" / ".bin" / "jscpd"
DESIGN = "docs/design/DESIGN.SHOP.md"
TARIFF = "src/shop/domain/tariff.py"
LEGACY = "src/shop/adapters/legacy_tariff.py"
TESTS = "tests/test_tariff.py"

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("lizard") is None or not JSCPD.is_file(),
    reason="lizard (uv sync) and jscpd (npm ci --ignore-scripts) must be installed",
)


def _measure(root: Path) -> tuple[int, str]:
    result = CliRunner().invoke(main, ["measure", "--root", str(root), "--json"])
    return result.exit_code, result.output


def _found(quality: dict[str, list[dict[str, str]]]) -> set[tuple[str, str]]:
    return {(f["check"], f["path"]) for f in quality["findings"]}


def test_measure_json_over_the_fixture_prints_the_three_qualities() -> None:
    """Given the fixture, its records naming a behavior no test keeps, and its
    radar holding the domain's import, When `adhere measure --json` runs,
    Then every target-level quality runs, and the Behavior-driven, Complete
    and Radar-true checks each print the finding the fixture plants."""
    code, output = _measure(FIXTURE)

    assert code == 0, output
    document = json.loads(output)
    qualities = {q["quality"]: q for q in document["qualities"]}
    assert {name for name, q in qualities.items() if q["ran"]} == {
        quality.value for quality in Quality if quality is not Quality.DECLARED
    }
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
        ("Duplication", LEGACY),
    } <= _found(complete)
    assert _found(radar) == {("Dependency", LEGACY), ("Edge only", TARIFF)}
    covered = {c["check"]: c["reason"] for c in document["coverage"] if c["check"]}
    assert {"Then asserted", "Done", "Hand-rolled"} <= set(covered)
    for declared in ("Covered", "Record kept"):
        assert "change-level" in covered[declared], declared
