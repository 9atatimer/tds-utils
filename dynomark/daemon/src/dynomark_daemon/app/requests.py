"""Request-id memory for the requests keyed on their id (contract/v1 README,
Envelope; the idempotency table: ``diff.propose``).
"""

import hashlib
from enum import StrEnum

from dynomark_daemon.app.errors import InvalidRequest
from dynomark_daemon.domain.ids import RequestId
from dynomark_daemon.ports.store import CorpusStorePort


class RequestRecall(StrEnum):
    NEW = "new"
    REPEAT = "repeat"


def _fingerprint(body: str) -> str:
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def recall_request(
    request_id: RequestId, body: str, *, store: CorpusStorePort
) -> RequestRecall:
    """Whether ``request_id`` is new (now remembered) or a retry of one seen.

    ``body`` is the request's canonical body, without its ``id``.

    Raises:
        InvalidRequest: the id is known with another body (``invalid``).
    """
    fingerprint = _fingerprint(body)
    known = store.get_request(request_id)
    if known is None:
        store.put_request(request_id, fingerprint)
        return RequestRecall.NEW
    if known != fingerprint:
        raise InvalidRequest(f"request {request_id} was sent with another body")
    return RequestRecall.REPEAT
