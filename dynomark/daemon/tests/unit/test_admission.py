"""Request admission (contract/v1 README, Connection lifecycle, step 3: "the
daemon checks every request in this order, and the first rule that applies
decides the answer"; step 2's read-only set). Transport contract, "Identity
and version" (DYNOMARK.DESIGN.md): "On mismatch, write-producing flows
stop; search and chat continue only if the extension's version is newer".
"""

import pytest

from dynomark_daemon.domain.connection import HelloMode
from dynomark_daemon.wire.admission import READ_ONLY_REQUESTS, refusal
from dynomark_daemon.wire.base import CONTRACT_VERSION
from dynomark_daemon.wire.messages import MESSAGE_MODELS

V = CONTRACT_VERSION
REQUESTS = sorted(
    t for t, model in MESSAGE_MODELS.items() if "id" in model.model_fields
)


def test_the_read_only_set_is_the_contracts() -> None:
    """Given the contract's read-only set, When compared, Then it is exactly
    hello, status, events.replay, events.ack, index.pull, search, ask and
    placement.explain."""
    assert READ_ONLY_REQUESTS == {
        "hello",
        "status",
        "events.replay",
        "events.ack",
        "index.pull",
        "search",
        "ask",
        "placement.explain",
    }


@pytest.mark.parametrize("request_type", REQUESTS)
def test_before_hello_every_request_but_hello_is_hello_required(
    request_type: str,
) -> None:
    """Given no hello answered on the connection, When a request arrives, Then
    every type but hello is refused hello_required."""
    expected = None if request_type == "hello" else "hello_required"
    assert refusal(request_type, V, mode=None) == expected


@pytest.mark.parametrize("request_type", REQUESTS)
def test_each_mode_admits_its_requests_and_refuses_the_rest(request_type: str) -> None:
    """Given a greeted connection, When a request at the daemon's version
    arrives, Then full admits all, read_only only the read-only set, refused
    only hello; the rest are version_mismatch."""
    read_only = request_type in READ_ONLY_REQUESTS
    assert refusal(request_type, V, mode=HelloMode.FULL) is None
    assert refusal(request_type, V, mode=HelloMode.READ_ONLY) == (
        None if read_only else "version_mismatch"
    )
    assert refusal(request_type, V, mode=HelloMode.REFUSED) == (
        None if request_type == "hello" else "version_mismatch"
    )


def test_a_non_frozen_request_at_another_version_is_version_mismatch() -> None:
    """Given a full connection, When a non-frozen request carries a v other than
    the daemon's, Then it is version_mismatch; hello at any v is admitted."""
    assert refusal("search", V + 1, mode=HelloMode.FULL) == "version_mismatch"
    assert refusal("hello", V + 1, mode=HelloMode.FULL) is None


def test_an_unknown_type_or_unreadable_version_is_left_to_the_schema() -> None:
    """Given a type the contract does not know, or a v that is not an integer,
    When checked, Then admission lets it through to the schema (invalid)."""
    assert refusal("teleport", V, mode=HelloMode.FULL) is None
    assert refusal("search", None, mode=HelloMode.FULL) is None
