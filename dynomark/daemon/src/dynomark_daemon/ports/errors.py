"""Errors a port raises. Use cases classify them; adapters raise them."""


class PortError(Exception):
    """A port call failed; ``retryable`` feeds the job's ``RetryPolicy``."""

    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


class NotFound(LookupError):
    """A store write named a record that does not exist."""
