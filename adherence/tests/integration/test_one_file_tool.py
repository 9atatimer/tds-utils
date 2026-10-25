"""A one-file tool is measured: the real Python analyzer finds the file's
regions by their section markers, and the layer checks find in those
regions what they would find in packages (DESIGN.ARCH-ADHERENCE.md, G12
and Behaviors: A one-file tool is measured). The other ports are fakes."""

from __future__ import annotations

from dataclasses import replace

from adherence.adapters.fakes import (
    FakeComplexity,
    FakeDecision,
    FakeDuplication,
    FakeRecords,
    FakeRepository,
)
from adherence.adapters.python_ast import PythonCodeModel
from adherence.application.measure import measure
from adherence.domain.model import CodeLanguage, Layer, Parameter, Signature
from adherence.domain.questions import Unavailable
from adherence.domain.records import Behavior, DesignRecords, SurfaceRow, UseCase
from adherence.domain.target import Head
from tests.measure_kit import declared, parameters

HEAD = Head.working_tree()
TOOL = "bin/tool.py"
LATE = "bin/late.py"
TOOL_TEXT = b'''"""A one-file tool."""
from __future__ import annotations

from typing import Protocol


# --- Pure helpers ---
def price(order: str, store: Store) -> int:
    return len(order)


# --- Ports ---
class Store(Protocol):
    def save(self, order: str) -> None: ...


# --- Action functions ---
class FileStore:
    def save(self, order: str) -> None:
        print(order)


# --- Flow functions ---
def close_order(order: str, *, store: Store) -> str:
    store.save(order)
    spare = FileStore()
    return order


# --- Entry points ---
def main() -> None:
    close_order("o", store=FileStore())
'''
LATE_TEXT = b"""# --- Entry points ---
def main() -> None:
    print(twice(2))


# --- Pure helpers ---
def twice(n: int) -> int:
    return n * 2
"""
DECLARATION = b"""
[layers]
regions = [{ file = "bin/tool.py" }, { file = "bin/late.py" }]

[runtimes]
tool = ["bin/tool.py"]
"""
REGIONS = {
    "ports": Layer.PORTS,
    "pure helpers": Layer.DOMAIN,
    "action functions": Layer.ADAPTERS,
    "flow functions": Layer.APPLICATION,
    "entry points": Layer.COMPOSITION_ROOT,
}
DESIGN = "docs/design/DESIGN.TOOL.md"
ARCHITECTURE = "docs/design/ARCHITECTURE.TOOL.md"
GIVEN = "Given an order, When it is {}, Then it is {}"


def _use_case(name: str, *parameters: tuple[str, bool]) -> UseCase:
    stated = tuple(Parameter(n, "str", k, False) for n, k in parameters)
    return UseCase(name, Signature(stated, "str"), ARCHITECTURE, 3)


RECORDS = DesignRecords(
    behaviors=(
        Behavior("An order is closed", GIVEN.format("closed", "closed"), DESIGN, 9),
        Behavior("An order is priced", GIVEN.format("priced", "priced"), DESIGN, 10),
    ),
    use_cases=(
        _use_case("close_order", ("order", False), ("store", True)),
        _use_case("price", ("order", False), ("store", False)),
    ),
    surface=(
        SurfaceRow("An order is closed", "close_order", ARCHITECTURE, 3),
        SurfaceRow("An order is priced", "price", ARCHITECTURE, 4),
    ),
)


def test_measure_one_file_tool_finds_in_its_regions_what_packages_show() -> None:
    """Given one file whose section markers make ports, rules, adapters,
    workflow and entry-point regions, and one whose entry points come first,
    When a run is asked for, Then Purity finds the rule taking the port,
    Wiring the workflow constructing the adapter, Trace the behavior only a
    rule carries, and Anatomy the file out of order -- each in the layer its
    region gives it -- and the behavior the workflow carries has a home."""
    vocabulary = parameters().vocabulary
    report = measure(
        HEAD,
        declared(DECLARATION),
        repository=FakeRepository({HEAD: {TOOL: TOOL_TEXT, LATE: LATE_TEXT}}),
        analyzers={CodeLanguage.PYTHON: PythonCodeModel()},
        complexity=FakeComplexity(),
        duplication=FakeDuplication(),
        records=FakeRecords({HEAD: RECORDS}),
        judge=FakeDecision(Unavailable("no judge")),
        parameters=parameters(vocabulary=replace(vocabulary, regions=REGIONS)),
        deadline=None,
    )

    found = {
        (f.check.name, f.unit.path, f.unit.symbol, f.layer, f.subject)
        for f in report.findings
    }
    assert ("Purity", TOOL, "price", Layer.DOMAIN, "store: the port Store") in found
    assert ("Wiring", TOOL, "close_order", Layer.APPLICATION, "FileStore") in found
    trace = {f.unit.symbol for f in report.findings if f.check.name == "Trace"}
    assert trace == {"An order is priced"}
    (anatomy,) = (f for f in report.findings if f.check.name == "Anatomy")
    assert (anatomy.unit.path, anatomy.layer) == (LATE, Layer.DOMAIN)
