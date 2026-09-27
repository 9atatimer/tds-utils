"""Frames on both hops (contract/v1/README.md, Framing): a uint32
little-endian length, then that many bytes of JSON; length 0 is invalid;
limits are on the body (32 MiB inbound, 1 MiB outbound); a length over the
limit closes the connection without an answer.
"""

import asyncio

import pytest

from dynomark_daemon.adapters.framing import (
    MAX_INBOUND,
    MAX_OUTBOUND,
    FrameError,
    frame,
    read_frame,
)


def _read(data: bytes, limit: int = MAX_INBOUND) -> bytes | None:
    async def run() -> bytes | None:
        reader = asyncio.StreamReader()
        reader.feed_data(data)
        reader.feed_eof()
        return await read_frame(reader, limit=limit)

    return asyncio.run(run())


def test_frame_prefixes_the_body_with_its_little_endian_length() -> None:
    """Given a body, When framed, Then 4 little-endian length bytes lead it."""
    assert frame(b'{"a":1}') == b"\x07\x00\x00\x00" + b'{"a":1}'


def test_frame_refuses_an_empty_or_oversize_body() -> None:
    """Given an empty body or one over the outbound limit, When framed, Then
    FrameError: such a frame is never sent."""
    with pytest.raises(FrameError):
        frame(b"")
    with pytest.raises(FrameError):
        frame(b"x" * (MAX_OUTBOUND + 1))


def test_limits_are_the_contract_sizes() -> None:
    """The limits are 32 MiB extension -> daemon and 1 MiB daemon -> extension."""
    assert (MAX_INBOUND, MAX_OUTBOUND) == (33_554_432, 1_048_576)


def test_read_frame_returns_one_body_then_none_at_a_clean_end() -> None:
    """Given one frame then end of stream, When read twice, Then the body and
    then None (the peer closed between frames)."""
    data = frame(b'{"a":1}')

    async def run() -> tuple[bytes | None, bytes | None]:
        reader = asyncio.StreamReader()
        reader.feed_data(data)
        reader.feed_eof()
        return await read_frame(reader, limit=MAX_INBOUND), await read_frame(
            reader, limit=MAX_INBOUND
        )

    assert asyncio.run(run()) == (b'{"a":1}', None)


@pytest.mark.parametrize(
    "data",
    [
        b"\x00\x00\x00\x00",
        (MAX_INBOUND + 1).to_bytes(4, "little"),
        b"\x05\x00\x00\x00abc",
        b"\x05\x00",
    ],
    ids=["zero-length", "over-limit", "truncated-body", "truncated-header"],
)
def test_read_frame_refuses_a_bad_frame(data: bytes) -> None:
    """Given a zero length, a length over the limit, or a stream cut inside a
    frame, When read, Then FrameError (the receiver closes)."""
    with pytest.raises(FrameError):
        _read(data)
