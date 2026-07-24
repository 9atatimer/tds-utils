"""Exception hierarchy for orgmarks.

Two roots under ``OrgmarksError``: ``DomainError`` for rule/plan/invariant
violations in pure logic, ``InfrastructureError`` for edge failures (I/O,
provider unreachable) that the pipeline degrades around rather than crashing.
"""

from __future__ import annotations


class OrgmarksError(Exception):
    """Base class for every orgmarks error."""


class DomainError(OrgmarksError):
    """A violation of domain logic or an invariant."""


class InfrastructureError(OrgmarksError):
    """A failure at an edge: file I/O, a provider, an external process."""
