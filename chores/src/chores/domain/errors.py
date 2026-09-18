"""Error hierarchy for the chores domain (style-python: AppError -> DomainError)."""

from __future__ import annotations


class ChoresError(Exception):
    """Base of every error this package raises."""


class DomainError(ChoresError):
    """A rule of the problem was violated (bad definition, illegal transition)."""


class InfrastructureError(ChoresError):
    """A mechanism at an edge failed (network, process, filesystem, secrets)."""
