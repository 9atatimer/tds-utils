"""Errors a use case raises for a request it cannot serve.

Each maps to one contract error code in the transport adapter; the use
cases never name a code.
"""


class UseCaseError(Exception):
    """A request the daemon cannot act on."""


class UnknownRecord(UseCaseError, LookupError):
    """The request names a job, batch or other record the store does not hold."""


class TreeNotReady(UseCaseError):
    """No ``tree.snapshot`` holds what the use case must resolve yet; it runs
    again after the next one."""
