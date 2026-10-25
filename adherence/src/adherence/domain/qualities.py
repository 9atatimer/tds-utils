"""domain/qualities.py -- the closed quality set and the check catalog.

Each check is named in the problem's language and typed rule, judged, or
rule with a judged part, at the catalog (DESIGN.ARCH-ADHERENCE.md, The
Qualities table).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

# --- Values ------------------------------------------------------------------


class Quality(enum.Enum):
    """The nine structural properties. The set is closed by the design."""

    LAYERED = "Layered"
    HEXAGONAL = "Hexagonal"
    DOMAIN_DRIVEN = "Domain-driven"
    COMPOSABLE = "Composable"
    INJECTABLE = "Injectable"
    BEHAVIOR_DRIVEN = "Behavior-driven"
    COMPLETE = "Complete"
    RADAR_TRUE = "Radar-true"
    DECLARED = "Declared"


class CheckKind(enum.Enum):
    """A rule check's result is a fact; a judged check's is a probability.
    A check with both runs the judged part only on what the rule part left."""

    RULE = "rule"
    JUDGED = "judged"
    RULE_AND_JUDGED = "rule and judged"


@dataclass(frozen=True, slots=True)
class Check:
    """One named test of one quality."""

    name: str
    quality: Quality
    kind: CheckKind


# --- Constants ---------------------------------------------------------------

_R, _J, _RJ = CheckKind.RULE, CheckKind.JUDGED, CheckKind.RULE_AND_JUDGED

CATALOG: tuple[Check, ...] = (
    Check("Trace", Quality.LAYERED, _R),
    Check("Purity", Quality.LAYERED, _RJ),
    Check("Wiring", Quality.LAYERED, _R),
    Check("Anatomy", Quality.LAYERED, _R),
    Check("Two jobs", Quality.LAYERED, _J),
    Check("Grep", Quality.HEXAGONAL, _R),
    Check("Arrow", Quality.HEXAGONAL, _R),
    Check("Swap", Quality.HEXAGONAL, _R),
    Check("Change", Quality.HEXAGONAL, _R),
    Check("Language", Quality.DOMAIN_DRIVEN, _RJ),
    Check("Decision", Quality.DOMAIN_DRIVEN, _J),
    Check("Boundary", Quality.DOMAIN_DRIVEN, _RJ),
    Check("Anemic", Quality.DOMAIN_DRIVEN, _RJ),
    Check("Values in and out", Quality.COMPOSABLE, _R),
    Check("No nesting", Quality.COMPOSABLE, _R),
    Check("Helpers take values", Quality.COMPOSABLE, _R),
    Check("Ports as keywords", Quality.INJECTABLE, _R),
    Check("No self-wiring", Quality.INJECTABLE, _R),
    Check("No reach", Quality.INJECTABLE, _R),
    Check("Kept test", Quality.BEHAVIOR_DRIVEN, _R),
    Check("Then asserted", Quality.BEHAVIOR_DRIVEN, _J),
    Check("Public surface", Quality.BEHAVIOR_DRIVEN, _R),
    Check("Real assertion", Quality.BEHAVIOR_DRIVEN, _R),
    Check("Stub", Quality.COMPLETE, _R),
    Check("Done", Quality.COMPLETE, _J),
    Check("Hand-rolled", Quality.COMPLETE, _J),
    Check("Complexity", Quality.COMPLETE, _R),
    Check("Duplication", Quality.COMPLETE, _R),
    Check("Dependency", Quality.RADAR_TRUE, _R),
    Check("Edge only", Quality.RADAR_TRUE, _R),
    Check("Covered", Quality.DECLARED, _R),
    Check("Record kept", Quality.DECLARED, _R),
)

_BY_NAME = {check.name: check for check in CATALOG}

# --- Pure helpers ------------------------------------------------------------


def check_named(name: str) -> Check | None:
    """The catalog's check of that name, or None if the catalog has none."""
    return _BY_NAME.get(name)


def catalog_check(name: str) -> Check:
    """The catalog's check of that name; the name must be one of the catalog's."""
    return _BY_NAME[name]
