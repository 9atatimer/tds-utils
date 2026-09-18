"""Typed edge errors (CHORES.DESIGN.md Subsystem 4): the runner maps these to
run statuses without knowing which vendor raised them."""

from __future__ import annotations

from chores.domain.errors import InfrastructureError


class BackendError(InfrastructureError):
    """Base of every error a completion or agent adapter raises."""


class Unreachable(BackendError):
    """The backend could not be reached (connection refused, DNS, offline)."""


class Unauthorized(BackendError):
    """The backend rejected the credential."""


class RateLimited(BackendError):
    """The backend asked us to slow down."""


class BackendTimeout(BackendError):
    """The backend did not answer within the request's timeout."""


class ModelNotFound(BackendError):
    """The requested model is unknown to the backend."""


class SecretUnavailable(InfrastructureError):
    """A credential reference could not be resolved in time."""


class ProcessError(InfrastructureError):
    """A child process could not be started."""
