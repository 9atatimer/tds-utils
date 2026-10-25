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
