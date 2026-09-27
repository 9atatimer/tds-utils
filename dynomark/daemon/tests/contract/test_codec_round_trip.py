"""Every valid golden file survives decode -> encode unchanged.

contract/v1/README.md, Envelope: "optional fields are omitted, never
null; null appears only where the schema says null". What the daemon
sends must be what the extension's zod schemas accept, so a decoded
message re-encodes to the same JSON document.
"""

import json
from pathlib import Path

import pytest

from dynomark_daemon.wire.codec import decode_body, encode_message
from tests.contract.golden import valid_files

pytestmark = pytest.mark.contract


@pytest.mark.parametrize("path", valid_files(), ids=[p.name for p in valid_files()])
def test_encode_decoded_valid_example_reproduces_the_document(path: Path) -> None:
    """Given a valid golden file, When decoded and re-encoded, Then the JSON is
    the same document (no optional field gains a null, none is dropped)."""
    raw = path.read_bytes()

    encoded = encode_message(decode_body(raw))

    assert json.loads(encoded) == json.loads(raw)
