"""The Behavior-driven quality's rule checks over real Python sources: the
Python analyzer models them and `measure` runs with the shipped
vocabulary, every other port a fake (DESIGN.ARCH-ADHERENCE.md, Behaviors:
A test that cannot fail is found, A test past the surface is found, A
behavior with no kept test is found)."""

from __future__ import annotations

from adherence.adapters.python_ast import PythonCodeModel
from adherence.container import SHIPPED_VOCABULARY
from adherence.domain.finding import Finding
from adherence.domain.model import CodeLanguage
from adherence.domain.records import (
    Behavior,
    DesignRecords,
    RecordsUnavailable,
    UseCase,
)
from adherence.domain.report import Report
from tests.measure_kit import measure_with

TEST = "tests/test_use.py"


def _measured(
    files: dict[str, bytes], records: DesignRecords | RecordsUnavailable | None = None
) -> Report:
    return measure_with(
        files,
        analyzers={CodeLanguage.PYTHON: PythonCodeModel()},
        records=records,
        vocabulary=SHIPPED_VOCABULARY,
    )


def _of(report: Report, check: str) -> list[Finding]:
    return [f for f in report.findings if f.check.name == check]


def _cannot_fail(report: Report) -> set[str]:
    assert "Real assertion" in {c.name for c in report.ran}
    return {f.unit.symbol or "" for f in _of(report, "Real assertion")}


def test_an_assertion_of_any_literal_is_a_placeholder() -> None:
    """Given tests whose only assertion is a literal -- a number, a string,
    a tuple, a negative number -- and one that asserts a result, When Real
    assertion runs, Then each literal-only test is found and the real one is
    not (Self-review R3)."""
    source = (
        b"def test_two():\n"
        b"    run()\n"
        b"    assert 2\n"
        b"def test_ok():\n"
        b'    assert "ok"\n'
        b"def test_tuple():\n"
        b"    assert (1, 2)\n"
        b"def test_negative():\n"
        b"    assert -1\n"
        b"def test_real():\n"
        b"    assert run() == 1\n"
    )

    report = _measured({TEST: source})

    assert _cannot_fail(report) == {
        "test_two",
        "test_ok",
        "test_tuple",
        "test_negative",
    }


def test_a_false_assertion_with_a_message_in_a_test_that_runs_code_can_fail() -> None:
    """Given tests that run code and `assert False` with a message -- after
    a call that should raise, and on a branch that should not be reached --
    one that asserts a bare `False` after running code, and one that only
    asserts `False` with a message, When Real assertion runs, Then only the
    bare one and the one that runs nothing are found (Self-review R4)."""
    source = (
        b"def test_raises_by_hand():\n"
        b"    try:\n"
        b"        run()\n"
        b'        assert False, "run should raise"\n'
        b"    except ValueError:\n"
        b"        pass\n"
        b"def test_unreachable_branch():\n"
        b"    result = run()\n"
        b"    if result is None:\n"
        b'        assert False, "unreachable"\n'
        b"def test_bare_false():\n"
        b"    run()\n"
        b"    assert False\n"
        b"def test_runs_nothing():\n"
        b'    assert False, "todo"\n'
    )

    report = _measured({TEST: source})

    assert _cannot_fail(report) == {"test_bare_false", "test_runs_nothing"}


def test_an_assertion_call_must_be_an_assertion_api() -> None:
    """Given tests whose only assertion call is a function or method the
    repository defines under an assertion API's name -- the test module's
    own, a test class's own, and one imported from the repository -- and
    tests asserting through pytest.raises and a mock's assert method, When
    Real assertion runs, Then each test asserting only through the
    repository's own code is found, and the others are not (Self-review
    R3)."""
    source = (
        b"import pytest\n"
        b"from unittest.mock import Mock\n"
        b"from app.testing import assert_any_call\n"
        b"def assert_called():\n"
        b"    pass\n"
        b"def test_own_helper():\n"
        b"    run()\n"
        b"    assert_called()\n"
        b"def test_imported_helper():\n"
        b"    run()\n"
        b"    assert_any_call()\n"
        b"class TestThing:\n"
        b"    def assert_called_once(self):\n"
        b"        pass\n"
        b"    def test_own_method(self):\n"
        b"        run()\n"
        b"        self.assert_called_once()\n"
        b"def test_raises():\n"
        b"    with pytest.raises(ValueError):\n"
        b"        run()\n"
        b"def test_mock():\n"
        b"    double = Mock()\n"
        b"    run(double)\n"
        b"    double.assert_called_once()\n"
    )
    files = {
        "src/app/__init__.py": b"",
        "src/app/testing.py": b"def assert_any_call():\n    pass\n",
        TEST: source,
    }

    report = _measured(files)

    assert _cannot_fail(report) == {
        "test_own_helper",
        "test_imported_helper",
        "TestThing.test_own_method",
    }


def test_a_unittest_assert_method_is_an_assertion() -> None:
    """Given unittest-style tests asserting through `self.assertEqual`,
    `self.assertRaises` and `self.assertIn` on TestCase subclasses imported
    two ways, and one that asserts nothing, When Real assertion runs, Then
    only the one that asserts nothing is found (Self-review R4)."""
    source = (
        b"import unittest\n"
        b"from unittest import IsolatedAsyncioTestCase\n"
        b"class TestUse(unittest.TestCase):\n"
        b"    def test_equal(self):\n"
        b"        self.assertEqual(run(), 1)\n"
        b"    def test_raises(self):\n"
        b"        with self.assertRaises(ValueError):\n"
        b"            run()\n"
        b"    def test_nothing(self):\n"
        b"        run()\n"
        b"class TestAsync(IsolatedAsyncioTestCase):\n"
        b"    async def test_in(self):\n"
        b"        self.assertIn(1, await run())\n"
    )

    report = _measured({TEST: source})

    assert _cannot_fail(report) == {"TestUse.test_nothing"}


DESIGN = "docs/design/DESIGN.APP.md"
ARCHITECTURE = "docs/design/ARCHITECTURE.APP.md"
GOT = "A thing is got"
MEASURED = "A thing is measured"
RECORDS = DesignRecords(
    behaviors=(Behavior(GOT, DESIGN, 10), Behavior(MEASURED, DESIGN, 11)),
    surface=(
        UseCase(GOT, "get", ARCHITECTURE, 20),
        UseCase(MEASURED, "measure", ARCHITECTURE, 21),
    ),
)
APP = {
    "src/app/__init__.py": b"",
    "src/app/application/__init__.py": b"",
    "src/app/application/use.py": (
        b"def get(key):\n    return key\n\n\ndef measure():\n    return 1\n"
    ),
}


def _unkept(report: Report) -> set[str]:
    assert "Kept test" in {c.name for c in report.ran}
    return {f.unit.symbol or "" for f in _of(report, "Kept test")}


def test_a_behavior_is_kept_only_by_a_call_to_its_use_case() -> None:
    """Given use cases `get` and `measure`, a test calling `measure` by its
    import and a test calling a `get` method on an HTTP client of its own,
    When Kept test runs, Then the behavior whose use case is `get` is found:
    a method of another object by the same name keeps nothing (Self-review
    R5)."""
    source = (
        b"from app.application.use import measure\n"
        b"def test_client():\n"
        b"    client = Client()\n"
        b'    assert client.get("/x") == 1\n'
        b"def test_measure():\n"
        b"    assert measure() == 1\n"
    )

    report = _measured({**APP, TEST: source}, records=RECORDS)

    assert _unkept(report) == {GOT}


def test_a_use_case_reached_through_a_test_helper_is_kept() -> None:
    """Given a test reaching `measure` through a helper in another test
    module, which reaches it through a helper of its own, a test reaching
    `get` through a helper in its own module, and a use case no test
    reaches, When Kept test runs, Then only the behavior no test reaches is
    found: calls are followed through test-layer helpers (Self-review R6)."""
    dropped = "A thing is dropped"
    records = DesignRecords(
        behaviors=(*RECORDS.behaviors, Behavior(dropped, DESIGN, 12)),
        surface=(*RECORDS.surface, UseCase(dropped, "drop", ARCHITECTURE, 22)),
    )
    use = APP["src/app/application/use.py"] + b"\n\ndef drop():\n    return 0\n"
    kit = (
        b"from app.application.use import measure\n"
        b"def measure_with(x):\n"
        b"    return _measure()\n"
        b"def _measure():\n"
        b"    return measure()\n"
    )
    source = (
        b"from app.application.use import get\n"
        b"from tests.kit import measure_with\n"
        b"def _got():\n"
        b'    return get("k")\n'
        b"def test_measure():\n"
        b"    assert measure_with(1) == 1\n"
        b"def test_get():\n"
        b'    assert _got() == "k"\n'
    )
    files = {
        **APP,
        "src/app/application/use.py": use,
        "tests/__init__.py": b"",
        "tests/kit.py": kit,
        TEST: source,
    }

    report = _measured(files, records=records)

    assert _unkept(report) == {dropped}


RULES = {
    "src/app/domain/__init__.py": b"",
    "src/app/domain/rules.py": (
        b"def price(x):\n"
        b"    return _round(x)\n"
        b"def _round(x):\n"
        b"    return x\n"
        b"class Store:\n"
        b"    def _load(self):\n"
        b"        return 1\n"
    ),
}


def _past_surface(report: Report) -> set[str]:
    assert "Public surface" in {c.name for c in report.ran}
    return {f.subject for f in _of(report, "Public surface")}


def test_an_internal_is_found_by_the_definition_a_call_resolves_to() -> None:
    """Given a test calling a domain internal under an alias, one calling it
    through its module, and one calling a `_load` method on a test double of
    its own while a domain type defines `_load`, When Public surface runs,
    Then the aliased and the direct reach are found and the double's method
    is not (Self-review R7)."""
    source = (
        b"from app.domain.rules import _round as tidy\n"
        b"from app.domain import rules\n"
        b"def test_alias():\n"
        b"    assert tidy(1) == 1\n"
        b"def test_direct():\n"
        b"    assert rules._round(1) == 1\n"
        b"def test_double():\n"
        b"    double = Fake()\n"
        b"    assert double._load() == 1\n"
    )

    report = _measured({**APP, **RULES, TEST: source}, records=RECORDS)

    assert _past_surface(report) == {
        "test_alias -> tidy",
        "test_direct -> rules._round",
    }


def test_an_internal_reached_through_getattr_is_found() -> None:
    """Given a test reaching a domain internal by `getattr` with the name
    written as a string, and one reading a public name the same way, When
    Public surface runs, Then the internal reach is found (Self-review R7)."""
    source = (
        b"from app.domain import rules\n"
        b"def test_getattr():\n"
        b'    assert getattr(rules, "_round")(1) == 1\n'
        b"def test_public():\n"
        b'    assert getattr(rules, "price")(1) == 1\n'
    )

    report = _measured({**APP, **RULES, TEST: source}, records=RECORDS)

    assert _past_surface(report) == {"test_getattr -> rules._round"}


HELPED = {
    **APP,
    **RULES,
    "src/app/application/use.py": (
        APP["src/app/application/use.py"] + b"\n\ndef normalise(x):\n    return x\n"
    ),
}
HELPER_TEST = (
    b"from app.application.use import measure, normalise\n"
    b"from app.domain.rules import Store, price\n"
    b"def test_measure():\n"
    b"    assert measure() == 1\n"
    b"def test_price():\n"
    b"    assert price(1) == 1\n"
    b"def test_store():\n"
    b"    assert Store() is not None\n"
    b"def test_helper():\n"
    b"    assert normalise(1) == 1\n"
)


def test_a_test_calling_an_application_helper_is_found() -> None:
    """Given tests calling a use case, a pure domain function, a domain
    type, and a public application function that is not a use case, When
    Public surface runs, Then only the call to the application helper is
    found: tests drive the use case or the pure domain beneath it
    (Self-review R7)."""
    report = _measured({**HELPED, TEST: HELPER_TEST}, records=RECORDS)

    assert _past_surface(report) == {"test_helper -> normalise"}


def test_without_a_readable_record_a_helper_cannot_be_told() -> None:
    """Given no readable design record, When Public surface runs, Then which
    application function is a use case cannot be told: that half is
    coverage naming the record, and no helper is found (Self-review R7)."""
    unread = RecordsUnavailable(f"{DESIGN} is in draft")

    report = _measured({**HELPED, TEST: HELPER_TEST}, records=unread)

    assert _past_surface(report) == set()
    assert any(
        c.check == "Public surface" and DESIGN in c.reason for c in report.coverage
    )
