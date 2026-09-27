"""A connection's standing: the contract version each side speaks and what
that lets continue (DYNOMARK.DESIGN.md, Transport contract, "Identity and
version"; contract/v1 README, Connection lifecycle)."""

from enum import StrEnum


class HelloMode(StrEnum):
    """What a connection may do after the handshake."""

    FULL = "full"
    READ_ONLY = "read_only"
    REFUSED = "refused"
