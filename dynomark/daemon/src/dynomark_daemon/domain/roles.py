"""Who may write: the host role and the result a reader gets."""

from dataclasses import dataclass
from enum import StrEnum


class HostRole(StrEnum):
    WRITER = "writer"
    READER = "reader"


@dataclass(frozen=True, slots=True)
class NotWriter:
    """The non-retryable result of a write-producing use case on a reader."""

    use_case: str
