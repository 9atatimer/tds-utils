"""Request-id memory (contract/v1 README, Envelope: "The daemon remembers a
diff.propose id for as long as it keeps the diff; a known diff.propose id
arriving with a different body is answered error invalid"; the idempotency
table: diff.propose is keyed on the request id). Transport contract,
Delivery: "the delivery guarantee keys on RequestId" (DYNOMARK.DESIGN.md).
"""

import pytest

from dynomark_daemon.app.errors import InvalidRequest
from dynomark_daemon.app.requests import RequestRecall, recall_request
from dynomark_daemon.domain.ids import RequestId
from dynomark_daemon.testing.store import InMemoryCorpusStore

BODY = '{"kind":"audit"}'


def test_a_new_request_id_is_remembered_and_its_retry_is_a_repeat() -> None:
    """Given a request id seen for the first time, When it arrives again with
    the same body (an at-least-once retry), Then the first is NEW and the
    retry a REPEAT."""
    store = InMemoryCorpusStore()

    first = recall_request(RequestId("req-1"), BODY, store=store)
    retry = recall_request(RequestId("req-1"), BODY, store=store)

    assert (first, retry) == (RequestRecall.NEW, RequestRecall.REPEAT)


def test_a_known_request_id_with_another_body_is_invalid() -> None:
    """Given a remembered request id, When it arrives with a different body,
    Then it raises InvalidRequest (a reused id is never a new request)."""
    store = InMemoryCorpusStore()
    recall_request(RequestId("req-1"), BODY, store=store)

    with pytest.raises(InvalidRequest):
        recall_request(RequestId("req-1"), '{"kind":"rebuild"}', store=store)
