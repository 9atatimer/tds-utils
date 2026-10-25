"""domain/finding as pure functions over values, property-tested."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from adherence.domain.finding import Evidence, Finding, quoted
from adherence.domain.model import Layer, Unit, UnitKind
from adherence.domain.qualities import catalog_check

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
