"""The markdown RecordsPort adapter: the shared contract, then what the
records' markdown shape gives -- the Behaviors table, the Domain Language,
the use-case surface with its signatures, and the seam list -- read through
RepositoryPort at a target (ARCHITECTURE.ARCH-ADHERENCE.md, Seams:
RecordsPort; Module map: adapters/markdown_records.py)."""

from __future__ import annotations

from pathlib import Path

from adherence.adapters.fakes import FakeRepository
from adherence.adapters.markdown_records import MarkdownRecords
from adherence.domain.declaration import Declaration, parse_declaration
from adherence.domain.model import Parameter
from adherence.domain.records import (
    DesignRecords,
    RecordsUnavailable,
    SeamKind,
)
from adherence.domain.target import Head
from adherence.ports.records import RecordsPort
from adherence.ports.repository import Refused
from tests.records_contract import (
    ARCHITECTURE,
    BASE,
    CLOSED,
    DESIGN,
    NOW,
    REOPENED,
    RecordsContract,
    declaration,
)

DESIGN_TEXT = f"""# Tool

> **Status:** APPROVED (the owner)

## Behaviors

| Behavior | Given / When / Then |
|---|---|
| {CLOSED} | Given an open order, When it is closed, Then the store holds it closed |

## Domain Language

- **Order.** What a customer asks for. Invariant: one
  status at a time.
- **Store.** Where orders are kept.
"""
DESIGN_TEXT_GROWN = DESIGN_TEXT.replace(
    "\n\n## Domain Language",
    f"\n| {REOPENED} | Given a closed order, When it is reopened, Then it is open |"
    "\n\n## Domain Language",
)
NOT_A_SEAM = (
    "| How a report is shown | presenters in `cli/` "
    "| entry-point concern, not a seam | no I/O |"
)
CLOSE_ORDER = (
    "`close_order(order: Order \\| Draft, *, store: Store, retries: int = 3) -> str`"
)
ARCHITECTURE_TEXT = f"""# Tool -- architecture

> **Status:** APPROVED (the owner)

## Seams

| Axis of change | Seam | Kind | Why it is a seam |
|---|---|---|---|
| Where orders are kept | `Store` | port | a file today, a database later |
| The retry ceiling | `Limits` | parameter set | tuned per stage |
| What counts as large | `Sizing` | policy | retuned per market |
{NOT_A_SEAM}

## Use-case surface

| Design behavior | Use case (signature) | Ports |
|---|---|---|
| {CLOSED} | {CLOSE_ORDER} | Store |
| {REOPENED} | (`close_order`; a reopened order is closed again) | Store |
| An order is loaded | (`load_order` reads it; `Store.get` is the port) | Store |
| A rumour | (nothing named here) | none |

`load_order(order_id: str, *, store: Store) -> Order` reads one order.
"""


def _line_of(text: str, needle: str) -> int:
    return next(n for n, line in enumerate(text.splitlines(), 1) if needle in line)


def _files(design: str) -> dict[str, bytes | Refused]:
    return {DESIGN: design.encode(), ARCHITECTURE: ARCHITECTURE_TEXT.encode()}


def _records(declared: Declaration | None = None) -> DesignRecords:
    port = MarkdownRecords(FakeRepository({BASE: _files(DESIGN_TEXT)}))
    records = port.records(BASE, declared or declaration(), None)
    assert isinstance(records, DesignRecords), records
    return records


class TestMarkdownRecords(RecordsContract):
    def port(self) -> RecordsPort:
        repository = FakeRepository(
            {
                BASE: _files(DESIGN_TEXT),
                Head.working_tree(): _files(DESIGN_TEXT_GROWN),
            }
        )
        return MarkdownRecords(repository, clock=lambda: NOW)


def test_records_read_each_behavior_with_its_scenario_and_line() -> None:
    """Given a design record's Behaviors table, When the records are read,
    Then each row is a behavior with its name, its Given / When / Then, the
    record's path and the row's line."""
    (behavior,) = _records().behaviors

    assert behavior.name == CLOSED
    assert behavior.scenario == (
        "Given an open order, When it is closed, Then the store holds it closed"
    )
    assert (behavior.path, behavior.line) == (DESIGN, _line_of(DESIGN_TEXT, CLOSED))


def test_records_read_each_domain_language_term() -> None:
    """Given a design record's Domain Language, When the records are read,
    Then each defined term is read by its spelling, with where it is defined."""
    terms = _records().terms

    assert [(t.name, t.path) for t in terms] == [("Order", DESIGN), ("Store", DESIGN)]
    assert terms[1].line == _line_of(DESIGN_TEXT, "**Store.**")


def test_records_read_the_use_case_each_surface_row_names() -> None:
    """Given an architecture record's use-case surface, When the records are
    read, Then each row names the behavior and the use case it names first,
    by signature or by reference, or none when it names none."""
    surface = {row.behavior: row.use_case for row in _records().surface}

    assert surface == {
        CLOSED: "close_order",
        REOPENED: "close_order",
        "An order is loaded": "load_order",
        "A rumour": None,
    }


def test_records_read_each_signature_the_surface_gives() -> None:
    """Given signatures in the surface's table and in its prose, When the
    records are read, Then each use case has its parameters in order, each
    marked keyword-only after the bare star, with its annotation (an escaped
    table pipe read as a pipe) and its default."""
    use_cases = {u.name: u for u in _records().use_cases}

    close = use_cases["close_order"]
    assert close.signature.parameters == (
        Parameter("order", "Order | Draft", False, False),
        Parameter("store", "Store", True, False),
        Parameter("retries", "int", True, True),
    )
    assert close.signature.returns == "str"
    assert (close.path, close.line) == (
        ARCHITECTURE,
        _line_of(ARCHITECTURE_TEXT, "`close_order(order"),
    )
    load = use_cases["load_order"]
    assert [(p.name, p.keyword_only) for p in load.signature.parameters] == [
        ("order_id", False),
        ("store", True),
    ]


def test_records_read_each_seam_with_its_kind() -> None:
    """Given an architecture record's Seams table, When the records are read,
    Then each port, policy and parameter is a seam with its kind and line,
    and a row whose kind is no seam is not one."""
    seams = [(s.name, s.kind, s.path) for s in _records().seams]

    assert seams == [
        ("Store", SeamKind.PORT, ARCHITECTURE),
        ("Limits", SeamKind.PARAMETER, ARCHITECTURE),
        ("Sizing", SeamKind.POLICY, ARCHITECTURE),
    ]
    assert _records().seams[0].line == _line_of(ARCHITECTURE_TEXT, "`Store` | port")


def test_records_of_a_declaration_naming_none_are_unavailable() -> None:
    """Given a declaration with no [records] table, When the records are
    read, Then they are unavailable, saying the declaration names none."""
    bare = parse_declaration(b'[layers]\ndomain = ["src/**"]\n')
    assert isinstance(bare, Declaration)
    port = MarkdownRecords(FakeRepository({BASE: _files(DESIGN_TEXT)}))

    answer = port.records(BASE, bare, None)

    assert isinstance(answer, RecordsUnavailable)
    assert "names no design record" in answer.reason


def test_records_the_repository_refuses_are_unavailable() -> None:
    """Given a record the repository refuses to hand over, When the records
    are read, Then they are unavailable, naming the record and why."""
    files = {**_files(DESIGN_TEXT), DESIGN: Refused(DESIGN, "a symbolic link")}
    port = MarkdownRecords(FakeRepository({BASE: files}))

    answer = port.records(BASE, declaration(), None)

    assert isinstance(answer, RecordsUnavailable)
    assert DESIGN in answer.reason and "a symbolic link" in answer.reason


ENGINE_RECORDS = Path(__file__).resolve().parents[3] / "docs" / "design"


def test_records_of_the_engines_own_design_are_read_whole() -> None:
    """Given the engine's own design and architecture records, When they are
    read, Then every behavior has a surface row naming a use case, and
    measure's signature is read from the surface, keyword-only ports and all."""
    design = "docs/design/DESIGN.ARCH-ADHERENCE.md"
    architecture = "docs/design/ARCHITECTURE.ARCH-ADHERENCE.md"
    files = {
        path: (ENGINE_RECORDS / path.rpartition("/")[2]).read_bytes()
        for path in (design, architecture)
    }
    declared = parse_declaration(
        f'[records]\ndesign = "{design}"\narchitecture = "{architecture}"\n'.encode()
    )
    assert isinstance(declared, Declaration), declared

    records = MarkdownRecords(FakeRepository({BASE: files})).records(
        BASE, declared, None
    )

    assert isinstance(records, DesignRecords), records
    names = {b.name for b in records.behaviors}
    assert "A behavior with no home is found" in names
    surface = {row.behavior: row.use_case for row in records.surface}
    assert {surface.get(name) for name in names} <= {
        "measure",
        "judge_change",
        "judge_bounded",
        "load_declaration",
        "explain",
        "record_report",
    }
    measure = next(u for u in records.use_cases if u.name == "measure")
    assert [p.name for p in measure.signature.parameters][:3] == [
        "at",
        "declaration",
        "repository",
    ]
    assert all(p.keyword_only for p in measure.signature.parameters[2:])
    assert "Quality" in {t.name for t in records.terms}
    assert "RepositoryPort" in {s.name for s in records.seams}
