"""Contract v1 golden files against the daemon's Pydantic wire models.

contract/v1/README.md, Validation: "the daemon's Pydantic models ... MUST
accept every file in examples/valid/ and reject every file in
examples/invalid/". Design: Transport contract, "Identity and version --
The contract is a versioned schema artifact in the repo".
"""

from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

from dynomark_daemon.wire.messages import MESSAGE_MODELS, validate_message
from tests.contract.golden import (
    invalid_files,
    invalid_rules,
    load_object,
    message_def_names,
    message_type_of,
    schema_defs,
    valid_files,
)

pytestmark = pytest.mark.contract

# Invalid examples this runtime cannot reject because the rule is enforced
# only by the extension or by check.py, keyed by file name, each with the
# reason from invalid-rules.json. Every rule in contract v1 is a JSON Schema
# keyword the Pydantic models express, so the list is empty; an entry here
# is asserted to still be accepted, so a stale one fails.
UNENFORCEABLE_HERE: dict[str, str] = {}

DEF_NAME_BY_TYPE = {message_type_of(name): name for name in message_def_names()}


def _ids(paths: list[Path]) -> list[str]:
    return [path.name for path in paths]


@pytest.mark.parametrize("path", valid_files(), ids=_ids(valid_files()))
def test_parse_valid_example_yields_the_model_of_its_type(path: Path) -> None:
    """Given a contract v1 valid example, When the daemon parses it, Then it is
    accepted as the wire model named after the schema $def of its type."""
    raw = path.read_bytes()
    doc_type = cast(str, load_object(path)["type"])

    message = validate_message(raw)

    assert type(message).__name__ == DEF_NAME_BY_TYPE[doc_type]
    assert message.type == doc_type


@pytest.mark.parametrize("path", invalid_files(), ids=_ids(invalid_files()))
def test_parse_invalid_example_is_rejected(path: Path) -> None:
    """Given a contract v1 invalid example, When the daemon parses it, Then it is
    rejected (the rule named in invalid-rules.json holds on the daemon)."""
    raw = path.read_bytes()
    if path.name in UNENFORCEABLE_HERE:
        validate_message(raw)
        return

    with pytest.raises(ValidationError):
        validate_message(raw)


def test_unenforceable_allowlist_names_only_known_invalid_examples() -> None:
    """Given the allowlist, When compared to invalid-rules.json, Then every entry
    is a real invalid example (no stale exemption)."""
    assert set(UNENFORCEABLE_HERE) <= set(invalid_rules())


def test_wire_models_cover_exactly_the_schema_message_types() -> None:
    """Given messages.schema.json, When its message types are compared to the
    wire models, Then the two sets are equal (no missing, no extra model)."""
    assert set(MESSAGE_MODELS) == set(DEF_NAME_BY_TYPE)
    assert {model.__name__ for model in MESSAGE_MODELS.values()} == set(
        DEF_NAME_BY_TYPE.values()
    )


@pytest.mark.parametrize("def_name", message_def_names())
def test_wire_model_fields_match_schema_properties(def_name: str) -> None:
    """Given a message $def, When its properties and required set are compared to
    the wire model's fields, Then they are identical (same envelope, same body)."""
    definition = schema_defs()[def_name]
    properties = set(cast(dict[str, object], definition["properties"]))
    required = set(cast(list[str], definition["required"]))
    model = MESSAGE_MODELS[message_type_of(def_name)]

    fields = {f.alias or name: f for name, f in model.model_fields.items()}

    assert set(fields) == properties
    assert {key for key, f in fields.items() if f.is_required()} == required
