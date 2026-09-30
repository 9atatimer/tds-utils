"""Access to the shared contract v1 golden files (dynomark/contract/v1/).

Reading these files is fixture I/O, the one exception the contract suite
is allowed: they are the contract both runtimes are validated against.
"""

import json
from pathlib import Path
from typing import cast

CONTRACT_V1 = Path(__file__).resolve().parents[3] / "contract" / "v1"
VALID_DIR = CONTRACT_V1 / "examples" / "valid"
INVALID_DIR = CONTRACT_V1 / "examples" / "invalid"

JsonObject = dict[str, object]


def valid_files() -> list[Path]:
    return sorted(VALID_DIR.glob("*.json"))


def invalid_files() -> list[Path]:
    return sorted(INVALID_DIR.glob("*.json"))


def load_object(path: Path) -> JsonObject:
    return cast(JsonObject, json.loads(path.read_text(encoding="utf-8")))


def schema() -> JsonObject:
    return load_object(CONTRACT_V1 / "messages.schema.json")


def schema_defs() -> dict[str, JsonObject]:
    return cast(dict[str, JsonObject], schema()["$defs"])


def message_def_names() -> list[str]:
    """The $defs names the schema's root oneOf lists: one per message type."""
    branches = cast(list[dict[str, str]], schema()["oneOf"])
    return [branch["$ref"].removeprefix("#/$defs/") for branch in branches]


def message_type_of(def_name: str) -> str:
    properties = cast(dict[str, JsonObject], schema_defs()[def_name]["properties"])
    return cast(str, properties["type"]["const"])


def invalid_rules() -> dict[str, dict[str, str]]:
    path = CONTRACT_V1 / "examples" / "invalid-rules.json"
    return cast(dict[str, dict[str, str]], load_object(path))
