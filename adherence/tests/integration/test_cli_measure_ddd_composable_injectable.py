"""`adhere measure --json` over the fixture prints the Domain-driven,
Composable and Injectable findings, each naming what its design row says
it names: real git and the real Python analyzer, with records,
complexity and duplication overridden by their fakes until their
adapters land (tasks 059 and 061). The task-060 done check."""

from __future__ import annotations

import functools
import json
from pathlib import Path

from click.testing import CliRunner

from adherence.adapters.fakes import FakeComplexity, FakeDuplication, FakeRecords
from adherence.cli.main import main
from adherence.container import build
from adherence.domain.qualities import Quality
from adherence.domain.records import DesignRecords, Term
from adherence.domain.target import Head

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "python"
DESIGN = "docs/design/DESIGN.TOOL.md"
RECORDS = DesignRecords(domain_language=(Term("Order", DESIGN, 40),))
USE = "src/tool/application/use.py"
SHIP = "src/tool/application/ship.py"
LEDGER = "src/tool/domain/ledger.py"
RULES = "src/tool/domain/rules.py"


def _document() -> dict[str, object]:
    builder = functools.partial(
        build,
        records=FakeRecords({Head.working_tree(): RECORDS}),
        complexity=FakeComplexity(),
        duplication=FakeDuplication(),
    )
    result = CliRunner().invoke(
        main, ["measure", "--root", str(FIXTURE), "--json"], obj=builder
    )
    assert result.exit_code == 0, result.output
    document: dict[str, object] = json.loads(result.output)
    return document


def _findings(document: dict[str, object], quality: Quality) -> set[tuple[str, ...]]:
    qualities = {q["quality"]: q for q in document["qualities"]}
    return {
        (f["check"], f["path"], f["symbol"], f["subject"])
        for f in qualities[quality.value]["findings"]
    }


def _ran(document: dict[str, object], quality: Quality) -> list[str]:
    qualities = {q["quality"]: q for q in document["qualities"]}
    ran: list[str] = qualities[quality.value]["ran"]
    return ran


def test_measure_json_over_the_fixture_prints_the_ddd_findings() -> None:
    """Given the fixture and a Domain Language defining Order, When `adhere
    measure --json` runs, Then Language names the undefined noun and the
    signature -- never the port a use case takes -- Boundary names the type,
    the writer and the owning unit, and Anemic's all-fields type is coverage
    awaiting its judged part."""
    document = _document()

    assert _ran(document, Quality.DOMAIN_DRIVEN) == ["Language", "Boundary", "Anemic"]
    found = _findings(document, Quality.DOMAIN_DRIVEN)
    assert ("Language", SHIP, "restock", "Entry in restock") in found
    assert (
        "Boundary",
        USE,
        "close_order",
        f"Order.status written by close_order; owned by Order in {RULES}",
    ) in found
    assert not any(
        check == "Language" and ("Order" in s or "Store" in s)
        for check, _, _, s in found
    )
    anemic = [c for c in document["coverage"] if c["check"] == "Anemic"]
    assert [(c["path"], c["reason"].split(":")[0]) for c in anemic] == [
        (LEDGER, "Entry")
    ]


def test_measure_json_over_the_fixture_prints_the_composable_findings() -> None:
    """Given the fixture, When `adhere measure --json` runs, Then Values in
    and out names the parameter, No nesting names both functions, and
    Helpers take values names the helper and the parameter."""
    document = _document()

    assert _ran(document, Quality.COMPOSABLE) == [
        "Values in and out",
        "No nesting",
        "Helpers take values",
    ]
    assert _findings(document, Quality.COMPOSABLE) == {
        ("Values in and out", SHIP, "ship", "payload: dict"),
        (
            "No nesting",
            USE,
            "close_order.helper",
            "close_order.helper inside close_order",
        ),
        ("Helpers take values", LEDGER, "total", "weigh: Callable[[Entry], int]"),
        ("Helpers take values", LEDGER, "post", "store: 'Store'"),
    }


def test_measure_json_over_the_fixture_prints_the_injectable_findings() -> None:
    """Given the fixture, When `adhere measure --json` runs, Then Ports as
    keywords names the use case and the port, No self-wiring the use case
    and the adapter, and No reach the unit and what it reached."""
    document = _document()

    assert _ran(document, Quality.INJECTABLE) == [
        "Ports as keywords",
        "No self-wiring",
        "No reach",
    ]
    assert _findings(document, Quality.INJECTABLE) == {
        ("Ports as keywords", SHIP, "ship", "store: Store"),
        ("No self-wiring", SHIP, "restock", "FsStore"),
        ("No reach", SHIP, "restock", "the environment: os.environ"),
        ("No reach", SHIP, "restock", "a singleton: sys.argv"),
    }
