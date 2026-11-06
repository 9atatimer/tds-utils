"""The tests' SARIF schema checker (tests/json_schema.py) accepts a
conforming document and refuses each way one can break, so a presenter
test that reads no violation means the document conforms."""

from __future__ import annotations

import copy

from tests.json_schema import sarif_violations

MINIMAL: dict[str, object] = {
    "version": "2.1.0",
    "runs": [
        {
            "tool": {"driver": {"name": "adherence", "rules": [{"id": "stub"}]}},
            "results": [
                {
                    "ruleId": "stub",
                    "level": "error",
                    "message": {"text": "a stub"},
                    "locations": [
                        {
                            "physicalLocation": {
                                "artifactLocation": {"uri": "src/a%20b.py"},
                                "region": {"startLine": 4},
                            }
                        }
                    ],
                }
            ],
        }
    ],
}


def _broken(path: tuple[object, ...], value: object) -> dict[str, object]:
    document = copy.deepcopy(MINIMAL)
    node: object = document
    for key in path[:-1]:
        node = node[key]  # type: ignore[index]
    node[path[-1]] = value  # type: ignore[index]
    return document


def test_sarif_violations_of_a_conforming_document_are_none() -> None:
    """Given a minimal conforming SARIF document, When it is checked, Then
    there is no violation."""
    assert sarif_violations(MINIMAL) == []


def test_sarif_violations_name_each_way_a_document_breaks() -> None:
    """Given documents that break the schema by a missing required field, a
    wrong version, a property the schema does not allow, a level outside
    its enum, a line below 1, a message with no text, and a URI with a
    space, When each is checked, Then each has a violation."""
    result = ("runs", 0, "results", 0)
    region = (*result, "locations", 0, "physicalLocation", "region")
    uri = (*result, "locations", 0, "physicalLocation", "artifactLocation", "uri")
    broken = [
        {k: v for k, v in MINIMAL.items() if k != "version"},
        _broken(("version",), "2.0.0"),
        _broken(("extra",), True),
        _broken((*result, "level"), "fatal"),
        _broken((*region, "startLine"), 0),
        _broken((*result, "message"), {}),
        _broken(uri, "src/a b.py"),
    ]

    for document in broken:
        assert sarif_violations(document), document
