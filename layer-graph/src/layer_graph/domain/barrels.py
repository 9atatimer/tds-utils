"""Barrel transparency: a barrel is a file whose statements are only
re-exports. An import that lands on one is redirected to the files that
declare what it names, through nested barrels, cycle-safe; a whole-module
import is redirected to every file the barrel re-exports."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

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


# --- Values ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Surface:
    """A module's exports with re-export specifiers resolved to repository
    files (None where a specifier reached no file)."""

    local: frozenset[str]
    named: tuple[tuple[str, str, str | None], ...]
    stars: tuple[str, ...]


# --- Pure helpers: by symbol -------------------------------------------------


def _provides(
    path: str, name: str, surfaces: Mapping[str, Surface], seen: set[str]
) -> bool:
    """Whether a module exports a name, itself or through its stars."""
    if path in seen:
        return False
    seen.add(path)
    surface = surfaces.get(path)
    if surface is None:
        return False
    if name in surface.local or any(e == name for e, _, _ in surface.named):
        return True
    return name != "default" and any(
        _provides(star, name, surfaces, seen) for star in surface.stars
    )


def _declaring(
    path: str,
    name: str,
    tables: tuple[Mapping[str, Surface], Mapping[str, Sequence[str]]],
    seen: set[tuple[str, str]],
) -> tuple[str, ...] | None:
    surfaces, barrels = tables
    if (path, name) in seen:
        return None
    seen.add((path, name))
    surface = surfaces.get(path)
    if path not in barrels:
        if surface is None or _provides(path, name, surfaces, set()):
            return (path,)
        return None
    if surface is None:
        return None
    for exported, imported, target in surface.named:
        if exported != name:
            continue
        if target is None:
            return None
        if imported == "*":
            return through_barrels((target,), barrels)[0]
        return _declaring(target, imported, tables, seen)
    if name == "default":
        return None
    for star in surface.stars:
        found = _declaring(star, name, tables, seen)
        if found:
            return found
    return None


def declaring_files(
    path: str,
    name: str,
    surfaces: Mapping[str, Surface],
    barrels: Mapping[str, Sequence[str]],
) -> tuple[str, ...] | None:
    """The files that declare a name imported from a module: through a
    barrel's named re-exports, its `export * as` (the whole namespaced file)
    and its stars, nested barrels included; the module itself when it is
    not a barrel. None when the name cannot be found (`export *` never
    carries `default`)."""
    return _declaring(path, name, (surfaces, barrels), set())


def redirected(
    targets: Sequence[str],
    names: Sequence[str] | None,
    surfaces: Mapping[str, Surface],
    barrels: Mapping[str, Sequence[str]],
) -> tuple[tuple[str, ...], bool]:
    """The files an import statement reaches once barrels are seen through,
    and whether it fell back to every file behind a barrel: a whole-module
    import, or a name that cannot be found."""
    reached: dict[str, None] = {}
    fell_back = False
    for target in targets:
        if target not in barrels:
            reached.setdefault(target, None)
            continue
        found = [declaring_files(target, n, surfaces, barrels) for n in names or ()]
        if names is None or any(f is None for f in found):
            fell_back = True
            reached.update(dict.fromkeys(through_barrels((target,), barrels)[0]))
        for files in found:
            reached.update(dict.fromkeys(files or ()))
    return tuple(reached), fell_back
