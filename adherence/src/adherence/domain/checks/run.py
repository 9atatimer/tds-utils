"""domain/checks/run.py -- every target-level check over one CodeModel.

The checks implemented so far, by catalog name; measure calls run_checks
once per target.
"""

from __future__ import annotations

from collections.abc import Mapping

from adherence.domain.checks import hexagonal
from adherence.domain.checks.outcome import CheckFunction
from adherence.domain.declaration import Declaration
from adherence.domain.finding import Finding
from adherence.domain.model import CodeModel
from adherence.domain.parameters import Parameters
from adherence.domain.qualities import CATALOG
from adherence.domain.records import DesignRecords, RecordsUnavailable

# --- Constants ---------------------------------------------------------------

TARGET_CHECKS: Mapping[str, CheckFunction] = {
    "Grep": hexagonal.grep,
}

# --- Pure helpers ------------------------------------------------------------


def run_checks(
    model: CodeModel,
    declaration: Declaration,
    records: DesignRecords | RecordsUnavailable,
    parameters: Parameters,
) -> tuple[Finding, ...]:
    """Every implemented check's findings, in catalog order."""
    return tuple(
        finding
        for check in CATALOG
        if check.name in TARGET_CHECKS
        for finding in TARGET_CHECKS[check.name](
            model, declaration, records, parameters
        ).findings
    )
