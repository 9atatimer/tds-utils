"""A JSON Schema (draft-04) checker for the tests, over the keywords the
official SARIF 2.1.0 schema uses -- type, enum, properties, required,
additionalProperties, items, minItems, uniqueItems, minimum, maximum,
pattern, format (uri, uri-reference, date-time), anyOf, oneOf, allOf and
local $ref -- and refusing any other keyword, so a schema it cannot read
fails loudly instead of passing.

No JSON Schema library is on the radar (lmde/TECH_RADAR.md); the schema
itself is vendored as a test fixture (tests/fixtures/sarif/).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

SARIF_SCHEMA = (
    Path(__file__).resolve().parent / "fixtures" / "sarif" / "sarif-schema-2.1.0.json"
)
# Keywords that annotate and assert nothing.
ANNOTATIONS = frozenset({"$schema", "id", "title", "description", "default"})
ASSERTIONS = frozenset(
    {
        "$ref",
        "type",
        "enum",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "minItems",
        "uniqueItems",
        "minimum",
        "maximum",
        "pattern",
        "format",
        "anyOf",
        "oneOf",
        "allOf",
        "definitions",
    }
)
# Characters no URI, absolute or relative, may carry unescaped.
NOT_IN_URI = re.compile(r"[\s\x00-\x1f\x7f<>\"{}|\\^`]")

Schema = Mapping[str, object]


def _is_type(instance: object, name: str) -> bool:
    if name == "integer":
        return isinstance(instance, int) and not isinstance(instance, bool)
    if name == "number":
        return isinstance(instance, int | float) and not isinstance(instance, bool)
    expected = {
        "string": str,
        "boolean": bool,
        "object": dict,
        "array": list,
        "null": type(None),
    }
    return isinstance(instance, expected[name])


def _is_format(instance: str, name: str) -> bool:
    if NOT_IN_URI.search(instance) and name in {"uri", "uri-reference"}:
        return False
    if name == "uri":
        return bool(urlsplit(instance).scheme)
    if name == "uri-reference":
        return True
    try:
        datetime.fromisoformat(instance.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _resolve(reference: str, root: Schema) -> Schema:
    if not reference.startswith("#/"):
        raise ValueError(f"only local references are read: {reference}")
    node: object = root
    for part in reference[2:].split("/"):
        assert isinstance(node, Mapping)
        node = node[part]
    assert isinstance(node, Mapping)
    return node


def _object_violations(
    instance: Mapping[str, object], schema: Schema, root: Schema, at: str
) -> list[str]:
    found: list[str] = []
    properties = schema.get("properties", {})
    assert isinstance(properties, Mapping)
    required = schema.get("required", [])
    assert isinstance(required, Sequence)
    found.extend(f"{at}: missing {key}" for key in required if key not in instance)
    extra = schema.get("additionalProperties", True)
    for key, value in instance.items():
        if key in properties:
            found.extend(violations(value, properties[key], root, f"{at}.{key}"))
        elif extra is False:
            found.append(f"{at}: {key} is not allowed")
        elif isinstance(extra, Mapping):
            found.extend(violations(value, extra, root, f"{at}.{key}"))
    return found


def _array_violations(
    instance: Sequence[object], schema: Schema, root: Schema, at: str
) -> list[str]:
    found: list[str] = []
    minimum = schema.get("minItems")
    if isinstance(minimum, int) and len(instance) < minimum:
        found.append(f"{at}: fewer than {minimum} items")
    spelled = [json.dumps(item, sort_keys=True) for item in instance]
    if schema.get("uniqueItems") and len(set(spelled)) != len(spelled):
        found.append(f"{at}: items are not unique")
    items = schema.get("items")
    if isinstance(items, Mapping):
        for index, item in enumerate(instance):
            found.extend(violations(item, items, root, f"{at}[{index}]"))
    return found


def _scalar_violations(instance: object, schema: Schema, at: str) -> list[str]:
    found: list[str] = []
    low, high = schema.get("minimum"), schema.get("maximum")
    if _is_type(instance, "number"):
        assert isinstance(instance, int | float)
        if isinstance(low, int | float) and instance < low:
            found.append(f"{at}: below {low}")
        if isinstance(high, int | float) and instance > high:
            found.append(f"{at}: above {high}")
    if isinstance(instance, str):
        pattern, form = schema.get("pattern"), schema.get("format")
        if isinstance(pattern, str) and not re.search(pattern, instance):
            found.append(f"{at}: does not match {pattern}")
        if isinstance(form, str) and not _is_format(instance, form):
            found.append(f"{at}: not a {form}: {instance!r}")
    return found


def _combined_violations(
    instance: object, schema: Schema, root: Schema, at: str
) -> list[str]:
    found: list[str] = []
    every = schema.get("allOf", [])
    assert isinstance(every, Sequence)
    for part in every:
        found.extend(violations(instance, part, root, at))
    for keyword in ("anyOf", "oneOf"):
        options = schema.get(keyword)
        if not isinstance(options, Sequence):
            continue
        held = sum(not violations(instance, o, root, at) for o in options)
        if held == 0 or (keyword == "oneOf" and held > 1):
            found.append(f"{at}: {keyword} holds for {held} of {len(options)}")
    return found


def violations(
    instance: object, schema: object, root: Schema, at: str = "$"
) -> list[str]:
    """Every way the instance breaks the schema, each naming where; none
    when it conforms. `root` is the document local references resolve in."""
    assert isinstance(schema, Mapping)
    unknown = set(schema) - ANNOTATIONS - ASSERTIONS
    if unknown:
        raise ValueError(f"{at}: keywords this checker cannot read: {sorted(unknown)}")
    reference = schema.get("$ref")
    if isinstance(reference, str):
        return violations(instance, _resolve(reference, root), root, at)
    types = schema.get("type")
    names = [types] if isinstance(types, str) else types or []
    assert isinstance(names, list)
    if names and not any(_is_type(instance, n) for n in names):
        return [f"{at}: not of type {names}"]
    enum = schema.get("enum")
    if isinstance(enum, list) and instance not in enum:
        return [f"{at}: {instance!r} is not one of {enum}"]
    found = _combined_violations(instance, schema, root, at)
    if isinstance(instance, dict):
        found.extend(_object_violations(instance, schema, root, at))
    elif isinstance(instance, list):
        found.extend(_array_violations(instance, schema, root, at))
    return [*found, *_scalar_violations(instance, schema, at)]


def sarif_violations(document: object) -> list[str]:
    """Every way a document breaks the official SARIF 2.1.0 schema."""
    schema = json.loads(SARIF_SCHEMA.read_text(encoding="utf-8"))
    return violations(document, schema, schema)
