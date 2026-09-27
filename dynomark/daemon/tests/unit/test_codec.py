"""Frame bodies in and out (contract/v1/README.md, Framing and Connection
lifecycle, step 3).

A body that is not a JSON object closes the connection without an answer
(``MalformedBody``); a JSON object that fails the contract is answered
``error`` ``invalid`` with ``re`` the request's id when it is a readable
``Id`` (``InvalidMessage``).
"""

import json

import pytest
from hypothesis import given
from hypothesis import strategies as st

from dynomark_daemon.wire.codec import (
    InvalidMessage,
    MalformedBody,
    decode_body,
    encode_message,
)
from dynomark_daemon.wire.messages import Status

STATUS = b'{"v":1,"type":"status","id":"r-1"}'

json_scalars = st.none() | st.booleans() | st.integers() | st.text(max_size=8)
json_values = st.recursive(
    json_scalars,
    lambda inner: (
        st.lists(inner, max_size=3)
        | st.dictionaries(st.text(max_size=6), inner, max_size=3)
    ),
    max_leaves=10,
)


def test_decode_status_request_yields_the_status_model() -> None:
    """Given a well-formed status request, When decoded, Then it is a Status."""
    assert decode_body(STATUS) == Status(v=1, type="status", id="r-1")


def test_encode_message_writes_compact_utf8_json() -> None:
    """Given a message with a non-ASCII field, When encoded, Then the body is
    compact JSON with the character unescaped (frame sizes are UTF-8 bytes)."""
    message = decode_body('{"v":1,"type":"search","id":"q","query":"cafeé"}')

    body = encode_message(message)

    assert body == '{"v":1,"type":"search","id":"q","query":"cafeé"}'.encode()


@pytest.mark.parametrize(
    "body",
    [b"", b"[]", b'"status"', b"{", b"\xef\xbb\xbf" + STATUS, b"\xff{}"],
    ids=["empty", "array", "string", "truncated", "bom", "not-utf8"],
)
def test_decode_non_object_body_is_malformed(body: bytes) -> None:
    """Given a body that is not one UTF-8 JSON object, When decoded, Then it is
    MalformedBody (the connection closes without an answer)."""
    with pytest.raises(MalformedBody):
        decode_body(body)


def test_decode_non_finite_number_is_malformed() -> None:
    """Given a body using NaN (not JSON), When decoded, Then it is MalformedBody."""
    with pytest.raises(MalformedBody):
        decode_body(b'{"v":1,"type":"status","id":"r-1","x":NaN}')


def test_decode_duplicate_key_is_invalid_with_the_request_id() -> None:
    """Given an object with a duplicate key, When decoded, Then it is
    InvalidMessage answering the request's id (duplicate keys are invalid)."""
    with pytest.raises(InvalidMessage) as rejected:
        decode_body(b'{"v":1,"type":"status","id":"r-1","id":"r-2"}')

    assert rejected.value.re == "r-1"


def test_decode_lone_surrogate_is_invalid() -> None:
    """Given a string holding a lone UTF-16 surrogate, When decoded, Then it is
    InvalidMessage (every string is a sequence of Unicode scalar values)."""
    with pytest.raises(InvalidMessage) as rejected:
        decode_body(b'{"v":1,"type":"search","id":"q","query":"\\ud800"}')

    assert rejected.value.re == "q"


def test_decode_schema_failure_with_unreadable_id_answers_null() -> None:
    """Given an object failing the schema whose id is not an Id, When decoded,
    Then InvalidMessage carries re None."""
    with pytest.raises(InvalidMessage) as rejected:
        decode_body(b'{"v":1,"type":"status","id":"bad id\\n"}')

    assert rejected.value.re is None


@given(json_values)
def test_decode_any_json_raises_only_contract_errors(value: object) -> None:
    """Given any JSON value, When decoded, Then the result is a message,
    MalformedBody or InvalidMessage -- never another exception."""
    try:
        decode_body(json.dumps(value).encode())
    except (MalformedBody, InvalidMessage):
        pass
