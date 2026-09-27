"""Every extension -> daemon request of contract v1 has a handler (contract/v1
README, Envelope: "Every request X is answered by exactly one frame: X.result
or error"; Message table). The wire union is enumerated from the daemon's
own models, and every valid golden example of a request is served: answered
with its result or an error other than ``invalid``.
"""

import json
from pathlib import Path

import pytest

from dynomark_daemon.adapters.dispatch import Dispatcher, Session
from dynomark_daemon.testing.clock import FakeClock, SequentialIds
from dynomark_daemon.testing.completion import ScriptedCompletion
from dynomark_daemon.testing.embedding import HashingEmbedding
from dynomark_daemon.testing.store import InMemoryCorpusStore
from dynomark_daemon.testing.transport import RecordingTransport
from dynomark_daemon.wire import messages as m
from dynomark_daemon.wire.messages import MESSAGE_MODELS
from tests import _wire as wire
from tests._factories import make_config
from tests.contract.golden import load_object, valid_files

pytestmark = pytest.mark.contract

EXTENSION_REQUESTS = frozenset(
    t for t, model in MESSAGE_MODELS.items() if "id" in model.model_fields
)


def _dispatcher() -> Dispatcher:
    return Dispatcher(
        make_config(),
        store=InMemoryCorpusStore(),
        embedding=HashingEmbedding(),
        completion=ScriptedCompletion(),
        clock=FakeClock(start_ms=1_000),
        ids=SequentialIds(),
        transport=RecordingTransport(),
    )


def _request_examples() -> list[Path]:
    return [
        path
        for path in valid_files()
        if str(load_object(path)["type"]) in EXTENSION_REQUESTS
    ]


def test_every_request_of_the_wire_union_has_a_handler() -> None:
    """Given the wire union's messages that carry a request id (the extension ->
    daemon requests), When the dispatcher's handlers are listed, Then there is
    exactly one per request type."""
    assert len(EXTENSION_REQUESTS) == 23
    assert _dispatcher().handled_types() == EXTENSION_REQUESTS


@pytest.mark.parametrize("path", _request_examples(), ids=lambda p: p.stem)
def test_every_valid_request_example_is_served(path: Path) -> None:
    """Given a full writer connection with a tree, When a valid golden request
    arrives, Then it is answered with its result or a served error (never
    invalid: nothing of contract v1 is left unserved)."""
    dispatcher, session = _dispatcher(), Session()
    dispatcher.handle(wire.hello(), session)
    dispatcher.handle(wire.tree_snapshot("t-0"), session)
    request = load_object(path)

    outcome = dispatcher.handle(json.dumps(request).encode("utf-8"), session)

    reply = outcome.reply
    assert reply is not None and getattr(reply, "re", None) == request["id"]
    if isinstance(reply, m.Error):
        assert reply.code != "invalid", reply.message
    else:
        assert reply.type == f"{request['type']}.result"
