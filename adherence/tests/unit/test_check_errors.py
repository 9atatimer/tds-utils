"""A rule check that errors is coverage (DESIGN.ARCH-ADHERENCE.md, Behaviors;
ARCHITECTURE.ARCH-ADHERENCE.md, Use-case surface: a check function's
exception is caught once at the check boundary and becomes Coverage naming
check, unit and error), and a check that could not run on a unit the change
touched makes the verdict inconclusive at best. A check's code cannot be
made to raise through a port, so both halves are domain tests over values:
run_checks with a check that raises on one file, and the comparison of two
reports."""

from __future__ import annotations

from adherence.domain.checks.outcome import CheckOutcome
from adherence.domain.checks.run import TARGET_CHECKS, run_checks
from adherence.domain.coverage import Coverage
from adherence.domain.declaration import Declaration
from adherence.domain.model import CodeModel, Layer, Unit, UnitKind
from adherence.domain.parameters import Parameters
from adherence.domain.qualities import catalog_check
from adherence.domain.records import DesignRecords, RecordsUnavailable
from adherence.domain.report import Report, Verdict
from adherence.domain.target import Base, Change, ChangedPaths, Head
from adherence.domain.verdict import compared
from tests.measure_kit import declared, parameters

BROKEN = "src/app/domain/broken.py"
FINE = "src/app/domain/fine.py"
CHANGE = Change(
    "example",
    Base("b" * 40),
    Head.at_revision("c" * 40),
    ChangedPaths(modified=(BROKEN,)),
)


def _stub_that_raises_on_broken(
    model: CodeModel,
    declaration: Declaration,
    records: DesignRecords | RecordsUnavailable,
    parameters: Parameters,
) -> CheckOutcome:
    if any(u.path == BROKEN for u in model.units):
        raise KeyError("an unexpected definition")
    return CheckOutcome()


def _file(path: str) -> Unit:
    return Unit(path, UnitKind.FILE, None, 1, 1, Layer.DOMAIN)


def test_run_checks_with_a_check_that_raises_on_a_file_covers_it() -> None:
    """Given a rule check that raises on one file and not another, When the
    checks run, Then coverage names the check, the file and the error, the
    other checks still run, and the check is not reported as ran."""
    model = CodeModel(units=(_file(BROKEN), _file(FINE)))
    checks = {**TARGET_CHECKS, "Stub": _stub_that_raises_on_broken}

    checked = run_checks(
        model,
        declared(),
        RecordsUnavailable("none"),
        parameters(),
        checks=checks,
    )

    (failed,) = [c for c in checked.coverage if c.check == "Stub"]
    assert failed.path == BROKEN
    assert "KeyError" in failed.reason and "an unexpected definition" in failed.reason
    assert "Stub" not in {c.name for c in checked.ran}
    assert "Grep" in {c.name for c in checked.ran}


def test_compared_with_a_check_in_coverage_on_a_touched_unit_is_inconclusive() -> None:
    """Given a head where a rule check could not run on a unit the change
    touched, and nothing introduced, When the reports are compared, Then the
    verdict is inconclusive and the reasons name the check and the unit."""
    stub = catalog_check("Stub")
    base = Report(ran=(stub,), units=(_file(BROKEN),))
    head = Report(
        units=(_file(BROKEN),),
        coverage=(Coverage("the check failed: KeyError", check="Stub", path=BROKEN),),
    )

    report = compared(base=base, head=head, change=CHANGE)

    assert report.verdict is Verdict.INCONCLUSIVE
    assert any("Stub" in r and BROKEN in r for r in report.reasons)


def test_compared_with_a_check_lost_since_the_base_is_inconclusive() -> None:
    """Given a check that ran at the base and is coverage at the head, on no
    unit the change touched, When the reports are compared, Then the verdict
    is inconclusive; a check in coverage for the same reason on both sides is
    not."""
    arrow = catalog_check("Arrow")
    same = Coverage("no radar was read", check="Dependency")
    base = Report(ran=(arrow,), units=(_file(FINE),), coverage=(same,))
    head = Report(
        units=(_file(FINE),),
        coverage=(same, Coverage("the check failed: ValueError", check="Arrow")),
    )

    report = compared(base=base, head=head, change=CHANGE)

    assert report.verdict is Verdict.INCONCLUSIVE
    assert [r for r in report.reasons if "Dependency" in r] == []
