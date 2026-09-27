"""Opaque identifiers of the ubiquitous language.

Every id is compared byte-for-byte and never parsed (contract v1, Envelope).
``Identity`` is not here: it is a value with its own meaning (bookmark.py).
"""

from typing import NewType

NodeId = NewType("NodeId", str)
"""A browser bookmark node id, per profile; opaque to the daemon."""

ProfileId = NewType("ProfileId", str)
"""The browser profile a connection, job, batch and event belong to."""

HostId = NewType("HostId", str)
"""The daemon host's id from its ``Config``."""

RequestId = NewType("RequestId", str)
"""The caller-chosen id of one transport request."""

JobId = NewType("JobId", str)
BatchId = NewType("BatchId", str)
EventId = NewType("EventId", str)
DiffId = NewType("DiffId", str)
ItemId = NewType("ItemId", str)
"""A ``DiffItem`` id."""

FeedbackId = NewType("FeedbackId", str)
"""A ``MoveFeedback`` id."""

SnapshotId = NewType("SnapshotId", str)
