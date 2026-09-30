"""Frames on both hops (contract/v1/README.md, Framing).

A frame is a uint32 little-endian body length, then that many bytes of
UTF-8 JSON. Length 0 is invalid; limits count the body only: at most
32 MiB from the extension, at most 1 MiB to it. A receiver that reads a bad
length closes the connection without answering.
"""

import asyncio
from typing import Final

HEADER_BYTES: Final = 4
MAX_INBOUND: Final = 33_554_432
"""Extension -> daemon: a full ``Snapshot`` travels this way."""
MAX_OUTBOUND: Final = 1_048_576
"""Daemon -> extension: Chrome's limit for a message from a native host."""


class FrameError(ValueError):
    """A frame that must not be sent, or that closes the connection."""


def frame(body: bytes, *, limit: int = MAX_OUTBOUND) -> bytes:
    """``body`` with its length header.

    Raises:
        FrameError: the body is empty or over ``limit``.
    """
    if not body or len(body) > limit:
        raise FrameError(f"a {len(body)}-byte body cannot be framed (limit {limit})")
    return len(body).to_bytes(HEADER_BYTES, "little") + body


def body_length(header: bytes, *, limit: int) -> int:
    """The body length a header announces.

    Raises:
        FrameError: zero, or over ``limit``.
    """
    length = int.from_bytes(header, "little")
    if length == 0 or length > limit:
        raise FrameError(f"frame length {length} is outside 1..{limit}")
    return length


async def read_frame(reader: asyncio.StreamReader, *, limit: int) -> bytes | None:
    """The next frame's body, or ``None`` when the stream ends between frames.

    Raises:
        FrameError: a bad length, or the stream ends inside a frame.
    """
    try:
        header = await reader.readexactly(HEADER_BYTES)
    except asyncio.IncompleteReadError as error:
        if not error.partial:
            return None
        raise FrameError("stream ended inside a frame header") from error
    length = body_length(header, limit=limit)
    try:
        return await reader.readexactly(length)
    except asyncio.IncompleteReadError as error:
        raise FrameError("stream ended inside a frame body") from error
