"""The declaration's [vocabulary] extends the Vocabulary a run is given,
never empties it (ARCHITECTURE.ARCH-ADHERENCE.md, Seams: Vocabulary and
Declaration; Mechanism > Measurement)."""

from __future__ import annotations

import pytest

from adherence.domain.declaration import DeclarationUnreadable, parse_declaration
from adherence.domain.model import ImportEdge
from adherence.domain.records import DesignRecords, Term
from tests.facts_kit import FS, RULES, STORE, USE, facts, function, port, type_, value
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


def test_measure_under_an_excusing_vocabulary_refuses_it_and_says_so() -> None:
    """Given a declaration whose [vocabulary] adds words to the sets that
    excuse -- a fake prefix that makes the real adapter a fake, a plain
    type that makes a foreign noun the language's own -- When the checks
    run, Then neither word is read: the port is still unfaked and the noun
    still foreign, and the report says each set was refused and why, as
    it says a refused exemption."""
    extension = HEXAGON + (
        b'\n[vocabulary]\nfakes = ["Fs"]\nplain_types = ["Gadget"]\nstubs = ["todo"]\n'
    )
    files = {USE: b"x\n" * 9, STORE: b"x\n" * 9, FS: b"x\n" * 9}
    definitions = [
        *port(STORE, "Store", 1),
        type_(FS, "FsStore", 1, bases=("Store",)),
        function(USE, "pick", 1, (value("item", "Gadget"),)),
    ]

    report = measure_with(
        files,
        facts(definitions),
        declared(extension),
        records=DesignRecords(domain_language=(Term("Order", "docs/D.md", 1),)),
    )

    assert {(f.check.name, f.subject) for f in report.findings} >= {
        ("Swap", "Store"),
        ("Language", "Gadget in pick"),
    }
    messages = [n.message for n in report.notices]
    assert any("fakes" in m and "vocabulary" in m for m in messages), messages
    assert any("plain_types" in m and "vocabulary" in m for m in messages), messages
    assert not any("stubs" in m for m in messages), messages
