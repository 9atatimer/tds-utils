"""One frame body <-> one contract v1 message.

contract/v1/README.md, Framing: a body is UTF-8 JSON, no BOM, exactly one
object; duplicate keys are invalid; every string is Unicode scalar values.
Connection lifecycle, step 3: a body that is not a JSON object closes the
connection (``MalformedBody``); an object failing the schema is answered
``error`` ``invalid`` with ``re`` the request's id if it reads as an ``Id``
(``InvalidMessage``). The 4-byte length header is the transport adapter's.
"""

import json
from typing import Final

from pydantic import ValidationError

from dynomark_daemon.wire.base import FullMatch
from dynomark_daemon.wire.messages import AnyMessage, validate_message

# --- Constants ---

BOM: Final = "﻿"
_READABLE_ID: Final = FullMatch(r"^[A-Za-z0-9._:-]{1,128}$")


# --- Errors ---


class MalformedBody(ValueError):
    """Not one UTF-8 JSON object: the receiver closes without answering."""


class InvalidMessage(ValueError):
    """A JSON object that fails contract v1; answered ``error`` ``invalid``."""

    def __init__(self, detail: str, *, re: str | None) -> None:
        super().__init__(detail)
        self.re = re


# --- Helpers ---


class _ObjectPairs:
    """``object_pairs_hook`` that notes duplicate keys and the last object seen.

    JSON objects close inside-out, so the last one seen is the top level.
    """

    def __init__(self) -> None:
        self.duplicates: set[str] = set()
        self.top_level: list[tuple[str, object]] = []

    def __call__(self, pairs: list[tuple[str, object]]) -> dict[str, object]:
        keys = [key for key, _ in pairs]
        self.duplicates.update(key for key in keys if keys.count(key) > 1)
        self.top_level = pairs
        return dict(pairs)


def _reject_non_finite(constant: str) -> float:
    raise MalformedBody(f"{constant} is not JSON")


def _decode_text(body: bytes | str) -> str:
    try:
        text = body.decode("utf-8") if isinstance(body, bytes) else body
    except UnicodeDecodeError as error:
        raise MalformedBody("body is not UTF-8") from error
    if text.startswith(BOM):
        raise MalformedBody("body starts with a byte order mark")
    return text


def _object_pairs(text: str) -> _ObjectPairs:
    """Parse ``text`` as one JSON object, or raise ``MalformedBody``."""
    pairs = _ObjectPairs()
    try:
        document = json.loads(
            text, object_pairs_hook=pairs, parse_constant=_reject_non_finite
        )
    except json.JSONDecodeError as error:
        raise MalformedBody(f"body is not JSON: {error}") from error
    if not isinstance(document, dict):
        raise MalformedBody("body is not a JSON object")
    return pairs


def _readable_id(pairs: list[tuple[str, object]]) -> str | None:
    """The first top-level ``id`` value, when it is a readable ``Id``."""
    candidate = next((value for key, value in pairs if key == "id"), None)
    if not isinstance(candidate, str):
        return None
    try:
        return _READABLE_ID(candidate)
    except ValueError:
        return None


# --- Entry points ---


def decode_body(body: bytes | str) -> AnyMessage:
    """Decode one frame body into its message.

    Raises:
        MalformedBody: not one UTF-8 JSON object.
        InvalidMessage: a JSON object that fails contract v1.
    """
    text = _decode_text(body)
    pairs = _object_pairs(text)
    re = _readable_id(pairs.top_level)
    if pairs.duplicates:
        raise InvalidMessage(f"duplicate keys: {sorted(pairs.duplicates)}", re=re)
    try:
        return validate_message(text)
    except ValidationError as error:
        raise InvalidMessage(str(error), re=re) from error


def encode_message(message: AnyMessage) -> bytes:
    """Encode a message as a compact UTF-8 JSON frame body (no header)."""
    return message.model_dump_json().encode("utf-8")
