"""Request admission before the schema (contract/v1 README, Connection
lifecycle, step 3, rules 3 and 4; the read-only set of step 2).

Rules 1-2 (a body that is not a JSON object; reading ``id``) belong to the
codec, rule 5 (the full schema) to the models.
"""

from typing import Final

from dynomark_daemon.domain.connection import HelloMode
from dynomark_daemon.wire.base import CONTRACT_VERSION
from dynomark_daemon.wire.messages import MESSAGE_MODELS
from dynomark_daemon.wire.values import ErrorCode

FROZEN: Final = frozenset({"hello", "hello.result", "error"})
"""Messages that keep their v1 shape in every version and accept any v."""

READ_ONLY_REQUESTS: Final = frozenset(
    {
        "hello",
        "status",
        "events.replay",
        "events.ack",
        "index.pull",
        "search",
        "ask",
        "placement.explain",
    }
)
"""What continues in ``read_only``: the design's "search and chat continue"."""

REQUESTS: Final = frozenset(
    t for t, model in MESSAGE_MODELS.items() if "id" in model.model_fields
)


def _is_other_version(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v != CONTRACT_VERSION


def _outside_mode(message_type: str, mode: HelloMode) -> bool:
    match mode:
        case HelloMode.FULL:
            return False
        case HelloMode.READ_ONLY:
            return message_type not in READ_ONLY_REQUESTS
        case HelloMode.REFUSED:
            return message_type != "hello"


def refusal(
    message_type: str, v: object, *, mode: HelloMode | None
) -> ErrorCode | None:
    """The error code a request is refused with before the schema runs, or
    ``None`` to go on. ``mode`` is ``None`` until a hello is answered on the
    connection; ``v`` is the frame's ``v`` as read (any JSON value)."""
    if mode is None:
        return None if message_type == "hello" else "hello_required"
    if message_type not in REQUESTS:
        return None
    if message_type not in FROZEN and _is_other_version(v):
        return "version_mismatch"
    return "version_mismatch" if _outside_mode(message_type, mode) else None
