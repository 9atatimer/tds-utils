"""Use case: a user move becomes feedback, daemon side (DYNOMARK.DESIGN.md,
The extension, "Record feedback"; contract/v1 ``move.observed``).
"""

from typing import Final

from dynomark_daemon.domain.placement import (
    Move,
    MoveFeedback,
    Placement,
    PlacementReason,
    feedback_of,
)
from dynomark_daemon.domain.roles import HostRole
from dynomark_daemon.domain.tree import OwnedRoots
from dynomark_daemon.ports.store import CorpusStorePort

USER_MODEL: Final = "user"
"""The ``model_id`` of a placement the user chose by moving the bookmark."""


def record_feedback(
    move: Move, role: HostRole, roots: OwnedRoots, *, store: CorpusStorePort
) -> MoveFeedback | None:
    """Record the move as ``MoveFeedback`` when it is one; a filed entry's
    placement follows a user move inside ``Dynomark``."""
    feedback = feedback_of(move, role, roots)
    if feedback is None:
        return None
    # No unit of work: a kill after the feedback leaves ``move.observed``
    # unanswered; its re-send (contract v1: requests are at-least-once)
    # records the feedback once (by ``feedback_id``) and moves the placement.
    store.put_feedback(feedback)
    placed = store.get_placement(feedback.identity)
    if placed is not None and feedback.to_path.is_inside(roots.dynomark):
        store.put_placement(
            Placement(
                identity=feedback.identity,
                reason=PlacementReason(
                    folder=feedback.to_path,
                    neighbours=(),
                    rationale="moved here by the user",
                    feedback_ids=(feedback.feedback_id,),
                    model_id=USER_MODEL,
                ),
                created_at=feedback.observed_at,
            )
        )
    return feedback
