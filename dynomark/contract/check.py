#!/usr/bin/env python3
"""check.py -- zero-dependency self-check of the Dynomark transport contract.

Python stdlib only. It checks the contract artifact against itself:

- CONTRACT_VERSION is the integer every non-frozen message pins in "v".
- Every object schema in messages.schema.json sets additionalProperties
  false, and the schema uses only the keywords the subset validator below
  implements (so nothing can pass here by being silently ignored).
- Message classification: every top-level oneOf branch has a string
  "type" const and exactly one of id (request), re (response) or
  event_id (event); every request X has a response "X.result".
- Every example file is valid JSON whose "type" is a known type; every
  message type has at least one valid example; every valid example
  validates; every invalid example fails, with the (keyword, path) that
  examples/invalid-rules.json names for it, and no two invalid examples
  break the same rule.
- Semantic rules JSON Schema cannot state, on the valid examples: op
  indices, receipt partitions, 512-byte LocalIndex rows, frame limits
  (on the JSON body, not the 4-byte header), snapshot shape, and no lone
  UTF-16 surrogate in any string.
- README.md's message table lists exactly the schema's message types,
  each with the direction its envelope implies.

The subset validator is a self-test aid, not a runtime validator. The
runtimes validate for real in their own contract tests (Pydantic, zod)
against the same example files.

Usage: python3 dynomark/contract/check.py    (any cwd)
Exit:  0 when every check passes, 1 otherwise.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

# --- Constants ---

HERE = Path(__file__).resolve().parent
V1 = HERE / "v1"
SCHEMA_PATH = V1 / "messages.schema.json"
VALID_DIR = V1 / "examples" / "valid"
INVALID_DIR = V1 / "examples" / "invalid"
RULES_PATH = V1 / "examples" / "invalid-rules.json"
README_PATH = V1 / "README.md"
VERSION_PATH = V1 / "CONTRACT_VERSION"

FROZEN_TYPES = {"hello", "hello.result", "error"}
MIN_INVALID = 20
LOCAL_INDEX_ROW_MAX_BYTES = 512
FRAME_MAX = {"extension -> daemon": 32 * 1024 * 1024, "daemon -> extension": 1024 * 1024}
DISCRIMINATORS = ("type", "op", "state")

ANNOTATIONS = {"$schema", "$id", "$comment", "title", "description", "default", "examples"}
APPLICATORS = {
    "$ref",
    "$defs",
    "type",
    "const",
    "enum",
    "properties",
    "required",
    "additionalProperties",
    "items",
    "minItems",
    "maxItems",
    "uniqueItems",
    "minLength",
    "maxLength",
    "pattern",
    "minimum",
    "maximum",
    "minProperties",
    "oneOf",
    "anyOf",
    "allOf",
    "not",
    "if",
    "then",
    "else",
}

Error = tuple[str, str, str]  # (json pointer, keyword, message)


# --- Action functions: JSON helpers ---


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f, object_pairs_hook=reject_duplicate_keys)


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate key {key!r}")
        out[key] = value
    return out


def json_type_of(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def json_equal(a: Any, b: Any) -> bool:
    ta, tb = json_type_of(a), json_type_of(b)
    numeric = {"integer", "number"}
    if ta != tb and not (ta in numeric and tb in numeric):
        return False
    if ta == "array":
        return len(a) == len(b) and all(json_equal(x, y) for x, y in zip(a, b))
    if ta == "object":
        return a.keys() == b.keys() and all(json_equal(a[k], b[k]) for k in a)
    return bool(a == b)


def pointer(base: str, token: str | int) -> str:
    text = str(token).replace("~", "~0").replace("/", "~1")
    return f"{base}/{text}"


def resolve_ref(root: dict[str, Any], ref: str) -> dict[str, Any]:
    if not ref.startswith("#/"):
        raise ValueError(f"unsupported $ref {ref!r}")
    node: Any = root
    for token in ref[2:].split("/"):
        node = node[token.replace("~1", "/").replace("~0", "~")]
    return node  # type: ignore[no-any-return]


def ecma_pattern(pattern: str) -> re.Pattern[str]:
    # ECMA-262 "$" (no multiline) is end of input; Python's also matches
    # before a trailing newline. \Z restores the ECMA meaning.
    if pattern.endswith("$") and not pattern.endswith("\\$"):
        pattern = pattern[:-1] + r"\Z"
    return re.compile(pattern)


# --- Action functions: the subset validator ---


def type_matches(expected: str, value: Any) -> bool:
    actual = json_type_of(value)
    if expected == "number":
        return actual in {"integer", "number"}
    if expected == "integer" and actual == "number":
        return float(value).is_integer()
    return actual == expected


def discriminated_branch(root: dict[str, Any], branches: list[dict[str, Any]], value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    for branch in branches:
        target = resolve_ref(root, branch["$ref"]) if "$ref" in branch else branch
        props = target.get("properties", {})
        for key in DISCRIMINATORS:
            const = props.get(key, {}).get("const")
            if const is not None and key in value and json_equal(value[key], const):
                return branch
    return None


def validate(schema: Any, value: Any, path: str, root: dict[str, Any]) -> list[Error]:
    if schema is True:
        return []
    if schema is False:
        return [(path, "false", "no value allowed")]
    errors: list[Error] = []
    for keyword in schema:
        if keyword not in APPLICATORS and keyword not in ANNOTATIONS:
            raise ValueError(f"unsupported keyword {keyword!r} at schema for {path or '/'}")
    if "$ref" in schema:
        errors += validate(resolve_ref(root, schema["$ref"]), value, path, root)
    errors += validate_generic(schema, value, path)
    errors += validate_string(schema, value, path)
    errors += validate_number(schema, value, path)
    errors += validate_array(schema, value, path, root)
    errors += validate_object(schema, value, path, root)
    errors += validate_combinators(schema, value, path, root)
    return errors


def validate_generic(schema: dict[str, Any], value: Any, path: str) -> list[Error]:
    errors: list[Error] = []
    if "type" in schema:
        allowed = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(type_matches(t, value) for t in allowed):
            errors.append((path, "type", f"expected {allowed}, got {json_type_of(value)}"))
    if "const" in schema and not json_equal(value, schema["const"]):
        errors.append((path, "const", f"expected {schema['const']!r}"))
    if "enum" in schema and not any(json_equal(value, e) for e in schema["enum"]):
        errors.append((path, "enum", f"{value!r} not in {schema['enum']}"))
    return errors


def validate_string(schema: dict[str, Any], value: Any, path: str) -> list[Error]:
    if not isinstance(value, str):
        return []
    errors: list[Error] = []
    if "minLength" in schema and len(value) < schema["minLength"]:
        errors.append((path, "minLength", f"shorter than {schema['minLength']}"))
    if "maxLength" in schema and len(value) > schema["maxLength"]:
        errors.append((path, "maxLength", f"longer than {schema['maxLength']}"))
    if "pattern" in schema and not ecma_pattern(schema["pattern"]).search(value):
        errors.append((path, "pattern", f"does not match {schema['pattern']}"))
    return errors


def validate_number(schema: dict[str, Any], value: Any, path: str) -> list[Error]:
    if json_type_of(value) not in {"integer", "number"}:
        return []
    errors: list[Error] = []
    if "minimum" in schema and value < schema["minimum"]:
        errors.append((path, "minimum", f"below {schema['minimum']}"))
    if "maximum" in schema and value > schema["maximum"]:
        errors.append((path, "maximum", f"above {schema['maximum']}"))
    return errors


def validate_array(schema: dict[str, Any], value: Any, path: str, root: dict[str, Any]) -> list[Error]:
    if not isinstance(value, list):
        return []
    errors: list[Error] = []
    if "minItems" in schema and len(value) < schema["minItems"]:
        errors.append((path, "minItems", f"fewer than {schema['minItems']}"))
    if "maxItems" in schema and len(value) > schema["maxItems"]:
        errors.append((path, "maxItems", f"more than {schema['maxItems']}"))
    if schema.get("uniqueItems"):
        for i, item in enumerate(value):
            if any(json_equal(item, other) for other in value[:i]):
                errors.append((pointer(path, i), "uniqueItems", "duplicate item"))
    if "items" in schema:
        for i, item in enumerate(value):
            errors += validate(schema["items"], item, pointer(path, i), root)
    return errors


def validate_object(schema: dict[str, Any], value: Any, path: str, root: dict[str, Any]) -> list[Error]:
    if not isinstance(value, dict):
        return []
    errors: list[Error] = []
    props = schema.get("properties", {})
    for name in schema.get("required", []):
        if name not in value:
            errors.append((pointer(path, name), "required", "missing"))
    if "minProperties" in schema and len(value) < schema["minProperties"]:
        errors.append((path, "minProperties", f"fewer than {schema['minProperties']} properties"))
    for name, item in value.items():
        if name in props:
            errors += validate(props[name], item, pointer(path, name), root)
        elif schema.get("additionalProperties") is False:
            errors.append((pointer(path, name), "additionalProperties", "not allowed"))
        elif "additionalProperties" in schema:
            errors += validate(schema["additionalProperties"], item, pointer(path, name), root)
    return errors


def validate_combinators(schema: dict[str, Any], value: Any, path: str, root: dict[str, Any]) -> list[Error]:
    errors: list[Error] = []
    for sub in schema.get("allOf", []):
        errors += validate(sub, value, path, root)
    if "anyOf" in schema and all(validate(sub, value, path, root) for sub in schema["anyOf"]):
        errors.append((path, "anyOf", "no branch matches"))
    if "oneOf" in schema:
        errors += validate_one_of(schema["oneOf"], value, path, root)
    if "not" in schema and not validate(schema["not"], value, path, root):
        errors.append((path, "not", "matches a forbidden schema"))
    if "if" in schema:
        branch = "then" if not validate(schema["if"], value, path, root) else "else"
        if branch in schema:
            errors += validate(schema[branch], value, path, root)
    return errors


def validate_one_of(branches: list[Any], value: Any, path: str, root: dict[str, Any]) -> list[Error]:
    results = [validate(sub, value, path, root) for sub in branches]
    passing = sum(1 for r in results if not r)
    if passing == 1:
        return []
    if passing > 1:
        return [(path, "oneOf", f"{passing} branches match")]
    chosen = discriminated_branch(root, branches, value)
    if chosen is not None:
        return results[branches.index(chosen)]
    return [(path, "oneOf", "no branch matches")]


# --- Action functions: schema introspection ---


def walk_schemas(node: Any, where: str) -> list[tuple[str, dict[str, Any]]]:
    found: list[tuple[str, dict[str, Any]]] = []
    if isinstance(node, dict):
        found.append((where, node))
        for key, sub in node.items():
            if key in {"properties", "$defs"}:
                for name, s in sub.items():
                    found += walk_schemas(s, f"{where}/{key}/{name}")
            elif key in {"items", "not", "if", "then", "else", "additionalProperties"}:
                found += walk_schemas(sub, f"{where}/{key}")
            elif key in {"oneOf", "anyOf", "allOf"}:
                for i, s in enumerate(sub):
                    found += walk_schemas(s, f"{where}/{key}/{i}")
    return found


def classify_messages(schema: dict[str, Any]) -> dict[str, dict[str, str]]:
    """type -> {def, kind, direction}; raises on a malformed message def."""
    out: dict[str, dict[str, str]] = {}
    for branch in schema["oneOf"]:
        def_name = branch["$ref"].rsplit("/", 1)[1]
        target = resolve_ref(schema, branch["$ref"])
        props = target["properties"]
        type_ = props["type"]["const"]
        kinds = [k for k, key in (("request", "id"), ("response", "re"), ("event", "event_id")) if key in props]
        if len(kinds) != 1 or type_ in out:
            raise ValueError(f"message {def_name}: envelope kinds {kinds}, duplicate={type_ in out}")
        for key in ("v", "type", {"request": "id", "response": "re", "event": "event_id"}[kinds[0]]):
            if key not in target["required"]:
                raise ValueError(f"message {def_name}: envelope field {key} not required")
        direction = "extension -> daemon" if kinds[0] == "request" else "daemon -> extension"
        out[type_] = {"def": def_name, "kind": kinds[0], "direction": direction}
    return out


# --- Action functions: semantic checks on valid examples ---


def check_operations(ops: list[dict[str, Any]], where: str) -> list[str]:
    indices = [op["index"] for op in ops]
    if indices != list(range(len(ops))):
        return [f"{where}: op indices {indices} are not 0..{len(ops) - 1} in order"]
    return []


def check_receipt(receipt: dict[str, Any], where: str) -> list[str]:
    problems = check_snapshot(receipt["snapshot"], where) if "snapshot" in receipt else []
    if receipt["state"] == "REJECTED":
        return problems
    applied = [a["index"] for a in receipt["applied"]]
    skipped = [s["index"] for s in receipt["skipped"]]
    if applied != sorted(applied) or skipped != sorted(skipped) or set(applied) & set(skipped):
        problems.append(f"{where}: applied/skipped not ascending and disjoint")
    if receipt["state"] == "PARTIAL":
        covered = sorted(applied + skipped)
        if covered != list(range(receipt["failed"]["index"])):
            problems.append(f"{where}: PARTIAL prefix {covered} != 0..failed.index-1")
    return problems


def check_snapshot(snapshot: dict[str, Any], where: str) -> list[str]:
    nodes = snapshot["nodes"]
    ids = [n["id"] for n in nodes]
    roots = [n for n in nodes if n["parent_id"] is None]
    problems: list[str] = []
    if len(set(ids)) != len(ids):
        problems.append(f"{where}: duplicate node ids")
    if len(roots) != 1:
        problems.append(f"{where}: {len(roots)} nodes with parent_id null, want 1")
        return problems
    by_id = {n["id"]: n for n in nodes}
    for key, node_id in snapshot["root_ids"].items():
        node = by_id.get(node_id)
        if node is None or node["parent_id"] != roots[0]["id"] or node["kind"] != "folder":
            problems.append(f"{where}: root_ids.{key} is not a folder directly under the root")
    siblings: dict[str, list[int]] = {}
    for n in nodes:
        if n["parent_id"] is None:
            continue
        parent = by_id.get(n["parent_id"])
        if parent is None or parent["kind"] != "folder":
            problems.append(f"{where}: node {n['id']} has unknown or non-folder parent {n['parent_id']}")
        siblings.setdefault(n["parent_id"], []).append(n["index"])
    for parent_id, indices in siblings.items():
        if sorted(indices) != list(range(len(indices))):
            problems.append(f"{where}: children of {parent_id} have indices {sorted(indices)}, want 0..n-1")
    return problems


def lone_surrogates(value: Any, path: str) -> list[str]:
    if isinstance(value, str):
        return [path or "/"] if any(0xD800 <= ord(c) <= 0xDFFF for c in value) else []
    if isinstance(value, list):
        return [p for i, item in enumerate(value) for p in lone_surrogates(item, pointer(path, i))]
    if isinstance(value, dict):
        return [p for k, item in value.items() for p in lone_surrogates(k, path) + lone_surrogates(item, pointer(path, k))]
    return []


def compact_utf8_len(value: Any) -> int:
    return len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def semantic_problems(doc: dict[str, Any], where: str, direction: str) -> list[str]:
    problems: list[str] = []
    if compact_utf8_len(doc) > FRAME_MAX[direction]:
        problems.append(f"{where}: JSON body exceeds {FRAME_MAX[direction]} bytes")
    for p in lone_surrogates(doc, ""):
        problems.append(f"{where}: {p}: lone UTF-16 surrogate (strings must be Unicode scalar values)")
    kind = doc["type"]
    if kind == "batch.offer":
        problems += check_operations(doc["batch"]["operations"], where)
    if kind == "diff.page.result":
        for item in doc["items"]:
            problems += check_operations(item["operations"], where)
    if kind == "batch.receipt":
        problems += check_receipt(doc["receipt"], where)
    if kind == "tree.snapshot":
        problems += check_snapshot(doc["snapshot"], where)
    if kind == "index.pull.result":
        for i, row in enumerate(doc["rows"]):
            if compact_utf8_len(row) > LOCAL_INDEX_ROW_MAX_BYTES:
                problems.append(f"{where}: rows[{i}] exceeds {LOCAL_INDEX_ROW_MAX_BYTES} bytes")
    return problems


# --- Action functions: README ---


def readme_table(text: str) -> dict[str, str]:
    """Message type -> direction, from the table whose header starts with | Message type |."""
    rows: dict[str, str] = {}
    in_table = False
    for line in text.splitlines():
        if line.startswith("| Message type |"):
            in_table = True
            continue
        if in_table and line.startswith("|---"):
            continue
        if in_table and line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            name = cells[0].strip("`")
            if name in rows:
                raise ValueError(f"README table lists {name} twice")
            rows[name] = cells[1]
            continue
        if in_table:
            break
    return rows


# --- Flow functions ---


def check_schema_shape(schema: dict[str, Any], version: int) -> list[str]:
    problems: list[str] = []
    for where, node in walk_schemas(schema, "#"):
        for keyword in node:
            if keyword not in APPLICATORS and keyword not in ANNOTATIONS:
                problems.append(f"{where}: keyword {keyword!r} unsupported by the self-check")
        if node.get("type") == "object" and node.get("additionalProperties") is not False:
            problems.append(f"{where}: object schema without additionalProperties false")
    messages = classify_messages(schema)
    for type_, info in messages.items():
        v = resolve_ref(schema, f"#/$defs/{info['def']}")["properties"]["v"]
        if type_ in FROZEN_TYPES:
            if "const" in v:
                problems.append(f"{type_}: frozen message must accept any v")
        elif v.get("const") != version:
            problems.append(f"{type_}: v const {v.get('const')} != CONTRACT_VERSION {version}")
        if info["kind"] == "request" and f"{type_}.result" not in messages:
            problems.append(f"request {type_} has no {type_}.result")
        if type_.endswith(".result") and type_[: -len(".result")] not in messages:
            problems.append(f"response {type_} has no request")
    return problems


def check_valid_examples(schema: dict[str, Any], messages: dict[str, dict[str, str]]) -> list[str]:
    problems: list[str] = []
    seen: set[str] = set()
    for path in sorted(VALID_DIR.glob("*.json")):
        name = path.name
        try:
            doc = load_json(path)
        except ValueError as exc:
            problems.append(f"valid/{name}: not valid JSON: {exc}")
            continue
        type_ = doc.get("type") if isinstance(doc, dict) else None
        if type_ not in messages:
            problems.append(f"valid/{name}: unknown type {type_!r}")
            continue
        if name.removesuffix(".json").split("--", 1)[0] != type_:
            problems.append(f"valid/{name}: file name does not start with its type {type_}")
        seen.add(type_)
        errors = validate(schema, doc, "", schema)
        problems += [f"valid/{name}: {p or '/'}: {k}: {m}" for p, k, m in errors]
        if not errors:
            problems += semantic_problems(doc, f"valid/{name}", messages[type_]["direction"])
    for type_ in sorted(set(messages) - seen):
        problems.append(f"message type {type_} has no valid example")
    return problems


def check_invalid_examples(schema: dict[str, Any], messages: dict[str, dict[str, str]]) -> list[str]:
    problems: list[str] = []
    rules: dict[str, dict[str, str]] = load_json(RULES_PATH)
    files = sorted(INVALID_DIR.glob("*.json"))
    if len(files) < MIN_INVALID:
        problems.append(f"only {len(files)} invalid examples, want >= {MIN_INVALID}")
    if set(rules) != {f.name for f in files}:
        problems.append(f"invalid-rules.json keys != invalid files: {sorted(set(rules) ^ {f.name for f in files})}")
    distinct: dict[tuple[str, str, str], str] = {}
    for path in files:
        name = path.name
        try:
            doc = load_json(path)
        except ValueError as exc:
            problems.append(f"invalid/{name}: not valid JSON: {exc}")
            continue
        type_ = doc.get("type") if isinstance(doc, dict) else None
        rule = rules.get(name, {})
        if type_ not in messages and rule.get("keyword") != "oneOf":
            problems.append(f"invalid/{name}: unknown type {type_!r} but rule is not the top-level oneOf")
        errors = validate(schema, doc, "", schema)
        if not errors:
            problems.append(f"invalid/{name}: validates, but must be rejected")
            continue
        want = (rule.get("path", "?"), rule.get("keyword", "?"))
        if want not in {(p, k) for p, k, _ in errors}:
            problems.append(f"invalid/{name}: rejected for {[(p, k) for p, k, _ in errors]}, not {want}")
        key = (str(type_), want[1], want[0])
        if key in distinct:
            problems.append(f"invalid/{name}: breaks the same rule as {distinct[key]}")
        distinct[key] = name
    return problems


def check_readme(messages: dict[str, dict[str, str]]) -> list[str]:
    table = readme_table(README_PATH.read_text(encoding="utf-8"))
    problems: list[str] = []
    for type_ in sorted(set(messages) ^ set(table)):
        where = "schema only" if type_ in messages else "README only"
        problems.append(f"README table vs schema: {type_} ({where})")
    for type_ in sorted(set(messages) & set(table)):
        if table[type_] != messages[type_]["direction"]:
            problems.append(f"README table: {type_} direction {table[type_]!r} != {messages[type_]['direction']!r}")
    return problems


def run_checks() -> list[str]:
    version_text = VERSION_PATH.read_text(encoding="utf-8").strip()
    if not version_text.isdigit():
        return [f"CONTRACT_VERSION is {version_text!r}, want a single integer"]
    version = int(version_text)
    schema = load_json(SCHEMA_PATH)
    problems = check_schema_shape(schema, version)
    messages = classify_messages(schema)
    problems += check_valid_examples(schema, messages)
    problems += check_invalid_examples(schema, messages)
    problems += check_readme(messages)
    return problems


# --- Main ---


def main() -> int:
    problems = run_checks()
    for problem in problems:
        print(f"FAIL {problem}")
    if problems:
        print(f"check.py: {len(problems)} problem(s)")
        return 1
    print("check.py: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
