"""Barrel transparency: a barrel is a file whose statements are only
re-exports. An import that lands on one is redirected to the files it
re-exports, through nested barrels, cycle-safe."""

from collections.abc import Mapping, Sequence

# --- Pure helpers ------------------------------------------------------------


def through_barrels(
    targets: Sequence[str], barrels: Mapping[str, Sequence[str]]
) -> tuple[tuple[str, ...], bool]:
    """The non-barrel files a set of import targets reaches, in first-reached
    order, and whether any barrel was crossed on the way."""
    reached: dict[str, None] = {}
    crossed = False
    seen: set[str] = set()
    pending = list(reversed(targets))
    while pending:
        target = pending.pop()
        if target in seen:
            continue
        seen.add(target)
        if target in barrels:
            crossed = True
            pending.extend(reversed(barrels[target]))
        else:
            reached.setdefault(target, None)
    return tuple(reached), crossed
