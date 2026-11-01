"""domain/finding as pure functions over values, property-tested."""

from __future__ import annotations

from dataclasses import replace

from hypothesis import given
from hypothesis import strategies as st

from adherence.domain.finding import Evidence, Finding, quoted
from adherence.domain.model import Layer, Unit, UnitKind
from adherence.domain.qualities import CheckKind, catalog_check

UNIT = Unit("src/a.py", UnitKind.FILE, None, 1, 1, Layer.DOMAIN)


def _finding(line: int, text: str = "fallback") -> Finding:
    return Finding(
        catalog_check("Grep"), UNIT, Layer.DOMAIN, "x", Evidence("src/a.py", line, text)
    )


@given(st.text(), st.text(), st.integers(0, 40), st.integers(0, 400))
def test_quoted_evidence_is_one_line_within_the_bound(
    source: str, fallback: str, line: int, bound: int
) -> None:
    """Given any source, any located line, any text of the check's own and any
    bound, When the evidence is quoted, Then it is at most the bound long and
    holds no line break."""
    finding = _finding(line, fallback)

    (finding,) = quoted((finding,), {"src/a.py": source.encode()}, bound)

    assert len(finding.evidence.text) <= bound
    assert not {"\n", "\r"} & set(finding.evidence.text)


def _flaw(
    *,
    check: str = "Grep",
    path: str = "src/a.py",
    symbol: str | None = "load",
    kind: UnitKind = UnitKind.FUNCTION,
    layer: Layer | None = Layer.DOMAIN,
    line: int = 3,
    text: str = "k = os.environ['K']",
) -> Finding:
    unit = Unit(path, kind, symbol, 1, 9, layer)
    return Finding(catalog_check(check), unit, layer, "x", Evidence(path, line, text))


def test_identity_of_one_flaw_moved_renamed_or_respaced_is_the_same() -> None:
    """Given one flaw, When it is found again after its file moved, its
    function was renamed, an edit above moved its line, or its whitespace
    changed, Then each finding has the same identity."""
    flaw = _flaw()

    assert flaw.identity == _flaw(path="src/b/moved.py").identity
    assert flaw.identity == _flaw(symbol="renamed").identity
    assert flaw.identity == _flaw(line=40).identity
    assert flaw.identity == _flaw(text="  k  =  os.environ['K']\t").identity


def test_identity_differs_by_quality_check_layer_unit_kind_and_evidence() -> None:
    """Given one flaw, When the check, the layer, the unit's kind or the
    offending line differs, Then the identity differs."""
    flaw = _flaw()

    assert flaw.identity != _flaw(check="Arrow").identity
    assert flaw.identity != _flaw(layer=Layer.APPLICATION).identity
    assert flaw.identity != _flaw(kind=UnitKind.TYPE).identity
    assert flaw.identity != _flaw(text="k = os.environ['J']").identity


@given(st.lists(st.sampled_from([" ", "\t", "  "]), min_size=4, max_size=4))
def test_identity_ignores_how_the_offending_line_is_spaced(gaps: list[str]) -> None:
    """Given the offending line spaced any way, When its finding's identity is
    taken, Then it is the identity of the line spaced once."""
    spaced = "".join(
        part + gap
        for part, gap in zip(["k", "=", "os.environ", "x"], gaps, strict=True)
    )

    assert _flaw(text=spaced).identity == _flaw(text="k = os.environ x").identity


def test_identity_of_a_judged_finding_differs_from_the_rule_finding_on_its_line() -> (
    None
):
    """Given a rule finding and a judged finding of one rule-and-judged check
    on the same line (Boundary's foreign write, and the judge's answer that
    it breaks an invariant), When their identities are taken, Then they
    differ, so a judgement is never paired with a fact by identity; every
    rule finding's identity is what it was."""
    rule = _flaw(check="Boundary", text="order.status = 'x'")
    judged = replace(rule, kind=CheckKind.JUDGED, confidence=0.9)

    assert judged.identity != rule.identity
    assert replace(judged, confidence=0.5).identity == judged.identity
    assert rule.identity == replace(rule, kind=CheckKind.RULE).identity


@given(st.text(), st.sampled_from(list(CheckKind)))
def test_an_unquoted_finding_keeps_its_identity_and_quotes_nothing(
    text: str, kind: CheckKind
) -> None:
    """Given a finding with any offending line, When it is unquoted (the form
    the ledger keeps: location and identity, no quoted code), Then its
    evidence holds no text, its identity is the quoted finding's, and
    unquoting it again changes nothing."""
    finding = replace(_finding(3, text), kind=kind)

    unquoted = finding.unquoted()

    assert unquoted.evidence == Evidence("src/a.py", 3, "")
    assert unquoted.identity == finding.identity
    assert unquoted.unquoted() == unquoted
