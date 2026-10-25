"""`adhere measure --json` through the composition root over the task-057
fixture: real git and the real Python analyzer, with records, complexity
and duplication overridden by their fakes until their adapters land
(tasks 059 and 061). The task-058 done check."""

from __future__ import annotations

import functools
import json
from pathlib import Path

from click.testing import CliRunner

from adherence.adapters.fakes import FakeComplexity, FakeDuplication, FakeRecords
from adherence.cli.main import main
from adherence.container import build
from adherence.domain.qualities import CATALOG, Quality
from adherence.domain.records import DesignRecords, Seam, SeamKind
from adherence.domain.target import Head

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "python"
RECORD = "docs/design/ARCHITECTURE.TOOL.md"
SEAMS = DesignRecords(
    seams=(
        Seam("Store", SeamKind.PORT, RECORD, 30),
        Seam("Clock", SeamKind.PORT, RECORD, 31),
    )
)


def _measure(root: Path) -> tuple[int, str]:
    builder = functools.partial(
        build,
        records=FakeRecords({Head.working_tree(): SEAMS}),
        complexity=FakeComplexity(),
        duplication=FakeDuplication(),
    )
    result = CliRunner().invoke(
        main, ["measure", "--root", str(root), "--json"], obj=builder
    )
    return result.exit_code, result.output


def test_measure_json_over_the_fixture_prints_the_hexagonal_findings() -> None:
    """Given the fixture and records naming a seam it has and one it lacks,
    When `adhere measure --json` runs, Then it prints the Hexagonal checks
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
        if check.name not in ran:
            assert covered.get(check.name), check.name
    for quality in qualities.values():
        if not quality["ran"]:
            assert quality["findings"] == [], quality["quality"]


def test_measure_of_a_root_git_cannot_list_says_not_run(tmp_path: Path) -> None:
    """Given a root that is no git repository, When `adhere measure --json`
    runs, Then it exits non-zero and the document says not run, and why."""
    code, output = _measure(tmp_path)

    assert code == 1
    assert "not a git repository" in json.loads(output)["not_run"]
