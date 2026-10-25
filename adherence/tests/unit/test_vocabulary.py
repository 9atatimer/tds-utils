"""The declaration's [vocabulary] extends the Vocabulary a run is given,
never empties it (ARCHITECTURE.ARCH-ADHERENCE.md, Seams: Vocabulary and
Declaration; Mechanism > Measurement)."""

from __future__ import annotations

import pytest

from adherence.domain.declaration import DeclarationUnreadable, parse_declaration
from adherence.domain.model import ImportEdge
from tests.facts_kit import RULES, USE, facts, function, value
from tests.measure_kit import HEXAGON, declared, measure_with


def test_measure_under_a_vocabulary_extension_reads_it_and_keeps_the_rest() -> None:
    """Given a declaration whose [vocabulary] adds a wire format and a vendor,
    and lists no word of the shipped vocabulary, When the checks run, Then
    the added words are found as the shipped ones are, and the shipped ones
    are still found."""
    extension = (
        HEXAGON + b'\n[vocabulary]\nwire_formats = ["Frame"]\nvendors = ["acme"]\n'
    )
    files = {USE: b"x\n" * 9, RULES: b"import acme\nimport requests\n"}
    definitions = [
        function(USE, "send", 1, (value("frame", "Frame"),)),
        function(USE, "fetch", 2, (value("payload", "dict"),)),
    ]
    imports = (
        ImportEdge(RULES, "acme", 1, "import acme", None),
        ImportEdge(RULES, "requests", 2, "import requests", None),
    )

    report = measure_with(
        files, facts(definitions, imports=imports), declared(extension)
    )

    wire = {
        (f.unit.symbol, f.subject)
        for f in report.findings
        if f.check.name == "Values in and out"
    }
    assert wire == {("send", "frame: Frame"), ("fetch", "payload: dict")}
    leaks = {f.subject for f in report.findings if f.check.name == "Grep"}
    assert leaks == {"acme", "requests"}


@pytest.mark.parametrize(
    "table",
    [
        b'[vocabulary]\nwire_formats = "Frame"\n',
        b"[vocabulary]\nvendors = [1]\n",
        b'[vocabulary]\nwords = ["x"]\n',
        b'[vocabulary.regions]\n"flow functions" = "nowhere"\n',
    ],
)
def test_parse_declaration_with_an_unreadable_vocabulary_says_why(table: bytes) -> None:
    """Given a [vocabulary] entry that is not a list of words, names no
    vocabulary, or maps a region marker to no layer, When the declaration
    is parsed, Then it is unreadable and the reason names the vocabulary."""
    parsed = parse_declaration(table)

    assert isinstance(parsed, DeclarationUnreadable)
    assert "vocabulary" in parsed.reason
