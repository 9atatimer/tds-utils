"""`adhere measure --json` through the composition root over the task-057
fixture: real git, the real Python analyzer and the real markdown records
adapter over the fixture's design records, with complexity and
duplication overridden by their fakes until their adapters land
(task-061). The task-058 and task-059 done checks."""

from __future__ import annotations

import functools
import json
from pathlib import Path

from click.testing import CliRunner

from adherence.adapters.fakes import FakeComplexity, FakeDuplication
from adherence.cli.main import main
from adherence.container import build
from adherence.domain.qualities import CATALOG, Quality

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "python"
RECORD = "docs/design/ARCHITECTURE.TOOL.md"
DESIGN = "docs/design/DESIGN.TOOL.md"


def _measure(root: Path) -> tuple[int, str]:
    builder = functools.partial(
        build,
        complexity=FakeComplexity(),
        duplication=FakeDuplication(),
    )
    result = CliRunner().invoke(
        main, ["measure", "--root", str(root), "--json"], obj=builder
    )
    return result.exit_code, result.output


def test_measure_json_over_the_fixture_prints_the_hexagonal_findings() -> None:
    """Given the fixture and its architecture record naming a seam it has and
    one it lacks, When `adhere measure --json` runs, Then it prints the Hexagonal checks
    that ran and their findings, and every check that did not run as
    coverage missing with a reason."""
    code, output = _measure(FIXTURE)

    assert code == 0, output
    document = json.loads(output)
    assert document["not_run"] is None
    qualities = {q["quality"]: q for q in document["qualities"]}
    hexagonal = qualities[Quality.HEXAGONAL.value]
    assert hexagonal["ran"] == ["Grep", "Arrow", "Swap", "Change"]
    found = {(f["check"], f["path"], f["subject"]) for f in hexagonal["findings"]}
    assert ("Swap", "src/tool/ports/store.py", "Store") in found
    assert ("Change", RECORD, "Clock: no port") in found
    assert all(f["identity"] and f["evidence"]["text"] for f in hexagonal["findings"])
    covered = {c["check"]: c["reason"] for c in document["coverage"] if c["check"]}
    ran = {name for q in document["qualities"] for name in q["ran"]}
    for check in CATALOG:
        assert check.name in ran or covered.get(check.name), check.name


def test_measure_of_a_root_git_cannot_list_says_not_run(tmp_path: Path) -> None:
    """Given a root that is no git repository, When `adhere measure --json`
    runs, Then it exits non-zero and the document says not run, and why."""
    code, output = _measure(tmp_path)

    assert code == 1
    assert "not a git repository" in json.loads(output)["not_run"]


def test_measure_json_over_the_fixture_prints_the_layered_findings() -> None:
    """Given the fixture, its design record with a behavior the code carries,
    one it does not and a row nothing could trace, and its declaration with
    a runtime no unit wires, When `adhere measure --json` runs, Then the
    Layered rule checks ran, Trace driven by the record, and their findings
    print."""
    code, output = _measure(FIXTURE)

    assert code == 0, output
    layered = next(
        q for q in json.loads(output)["qualities"] if q["quality"] == "Layered"
    )
    assert layered["ran"] == ["Trace", "Purity", "Wiring", "Anatomy"]
    found = {(f["check"], f["path"], f["symbol"]) for f in layered["findings"]}
    assert found == {
        ("Trace", DESIGN, "An order is reopened"),
        ("Trace", DESIGN, "Orders"),
        ("Wiring", "adherence.toml", None),
    }
    subjects = " ".join(f["subject"] for f in layered["findings"])
    assert "reopen_order(order, store)" in subjects
    assert "runtime onefile" in subjects
