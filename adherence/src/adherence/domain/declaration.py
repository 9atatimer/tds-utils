"""domain/declaration.py -- a repository's Declaration, parsed and validated.

The one owner of what a declaration says (ARCHITECTURE.ARCH-ADHERENCE.md,
Module map). Values in, values out: the bytes arrive from RepositoryPort
through the use case. adherence.toml is TOML read with the standard
library; its tables are the architecture's (Mechanism, Measurement).
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar

# --- Constants ---------------------------------------------------------------

DECLARATION_PATH = "adherence.toml"

TABLES = frozenset(
    {"layers", "runtimes", "records", "radar", "exemptions", "limits", "vocabulary"}
)
EXEMPTION_KEYS = frozenset({"check", "unit", "finding", "reason"})

# --- Values ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Exemption:
    """An owner's statement that a unit is not checked by one check, or that
    one finding is dismissed, with a reason."""

    reason: str
    check: str | None = None
    unit: str | None = None
    finding: str | None = None


@dataclass(frozen=True, slots=True)
class Declaration:
    """A repository's statement of its layers, runtimes, records, radar and
    exemptions. Declaration.none is the value for a repository that has none.
    """

    declared: bool = True
    exemptions: tuple[Exemption, ...] = ()

    none: ClassVar[Declaration]


Declaration.none = Declaration(declared=False)


@dataclass(frozen=True, slots=True)
class DeclarationUnreadable:
    """The outcome of a declaration that cannot be read, with the reason."""

    reason: str


# --- Pure helpers ------------------------------------------------------------


def _text_field(entry: Mapping[str, object], key: str) -> str | None:
    value = entry.get(key)
    return value if isinstance(value, str) and value else None


def _exemption(entry: object, number: int) -> Exemption | DeclarationUnreadable:
    """One [[exemptions]] entry, or why it cannot be read."""
    where = f"{DECLARATION_PATH}: exemption {number}"
    if not isinstance(entry, dict):
        return DeclarationUnreadable(f"{where} is not a table")
    unknown = sorted(set(entry) - EXEMPTION_KEYS)
    if unknown:
        return DeclarationUnreadable(
            f"{where} has unknown key(s): {', '.join(unknown)}"
        )
    if any(not isinstance(entry[key], str) for key in entry):
        return DeclarationUnreadable(f"{where} has a value that is not a string")
    reason = _text_field(entry, "reason")
    if reason is None:
        return DeclarationUnreadable(f"{where} has no reason")
    check = _text_field(entry, "check")
    unit = _text_field(entry, "unit")
    finding = _text_field(entry, "finding")
    if finding is not None and (check or unit):
        return DeclarationUnreadable(
            f"{where} names a finding and a check or unit; it names one or the other"
        )
    if finding is None and not (check and unit):
        return DeclarationUnreadable(
            f"{where} names a unit and a check, or one finding; it has neither"
        )
    return Exemption(reason=reason, check=check, unit=unit, finding=finding)


def _exemptions(value: object) -> tuple[Exemption, ...] | DeclarationUnreadable:
    if not isinstance(value, list):
        return DeclarationUnreadable(
            f"{DECLARATION_PATH}: exemptions is an array of tables ([[exemptions]])"
        )
    parsed: list[Exemption] = []
    for number, entry in enumerate(value, start=1):
        exemption = _exemption(entry, number)
        if isinstance(exemption, DeclarationUnreadable):
            return exemption
        parsed.append(exemption)
    return tuple(parsed)


def parse_declaration(text: bytes) -> Declaration | DeclarationUnreadable:
    """The Declaration that adherence.toml's bytes state, or why they cannot
    be read."""
    try:
        document = tomllib.loads(text.decode("utf-8"))
    except UnicodeDecodeError as error:
        return DeclarationUnreadable(f"{DECLARATION_PATH} is not utf-8: {error}")
    except tomllib.TOMLDecodeError as error:
        return DeclarationUnreadable(f"{DECLARATION_PATH}: {error}")
    unknown = sorted(set(document) - TABLES)
    if unknown:
        return DeclarationUnreadable(
            f"{DECLARATION_PATH}: unknown table(s): {', '.join(unknown)}"
        )
    exemptions = _exemptions(document.get("exemptions", []))
    if isinstance(exemptions, DeclarationUnreadable):
        return exemptions
    return Declaration(exemptions=exemptions)
