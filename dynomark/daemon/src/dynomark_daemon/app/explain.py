"""Use case: a placement is explained (DYNOMARK.DESIGN.md, Behaviors and
Interfaces; contract/v1 ``placement.explain``, the "why here" view).
"""

from dynomark_daemon.app.errors import UnknownRecord
from dynomark_daemon.domain.bookmark import Identity
from dynomark_daemon.domain.placement import Placement
from dynomark_daemon.ports.store import CorpusStorePort


def explain_placement(identity: Identity, *, store: CorpusStorePort) -> Placement:
    """The recorded placement of ``identity``: its folder and the reason
    (neighbours, rationale, feedback ids, model id).

    Raises:
        UnknownRecord: the identity has no placement (``not_found``).
    """
    placement = store.get_placement(identity)
    if placement is None:
        raise UnknownRecord(f"{identity.value} has no placement")
    return placement
