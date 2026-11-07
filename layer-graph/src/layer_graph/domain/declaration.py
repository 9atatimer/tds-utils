"""adherence.toml declarations: what one file states, and how the governing
declarations of a path are read as one.

Format: tds-utils docs/design/DESIGN.ARCH-ADHERENCE.md, "The declaration".
Only [layers] and [runtimes] are read (plain or under [override]); every
other section is the engine's business and is ignored here.
"""

import posixpath
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass

from layer_graph.domain.errors import DeclarationUnreadable
from layer_graph.domain.glob import matches, specificity

# --- Constants ---------------------------------------------------------------

DECLARATION_NAME = "adherence.toml"
TEST_LAYER = "test"
# Outermost to innermost; the test layer sits outside all of them.
LAYER_ORDER = ("composition root", "adapters", "application", "ports", "domain")
KNOWN_LAYERS = frozenset((*LAYER_ORDER, TEST_LAYER))
# [layers] may also carry regions (file line ranges); a graph of files does
# not split a file, so they are skipped.
REGIONS_KEY = "regions"
OVERRIDE = "override"


# --- Values ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LayerGlob:
    """One layer pattern, resolved to a repository path."""

    layer: str
    pattern: str


@dataclass(frozen=True, slots=True)
class RuntimeGlob:
    """One runtime pattern, resolved to a repository path."""

    runtime: str
    pattern: str


@dataclass(frozen=True, slots=True)
class Declaration:
    """What one adherence.toml states, its patterns under its directory."""

    path: str
    directory: str
    layers: tuple[LayerGlob, ...]
    runtimes: tuple[RuntimeGlob, ...]
    overrides_layers: bool = False
    overrides_runtimes: bool = False

    def governs(self, path: str) -> bool:
        """Whether this declaration's subtree holds the path."""
        return is_under(path, self.directory)

    def layer_of(self, path: str) -> LayerGlob | None:
        """This declaration's own winning layer pattern for a path."""
        return winning_glob(self.layers, path)


# --- Predicates --------------------------------------------------------------


def is_under(path: str, directory: str) -> bool:
    """Whether a repository path lies in a directory ("" is the root)."""
    return directory == "" or path == directory or path.startswith(directory + "/")


def is_declaration_path(path: str) -> bool:
    """Whether a repository path is named like a declaration."""
    return posixpath.basename(path) == DECLARATION_NAME


def is_test_data(path: str, above: Sequence[Declaration]) -> bool:
    """Whether a file named like a declaration is test data: a declaration
    above it assigns its path to the test layer."""
    directory = posixpath.dirname(path)
    for declaration in above:
        if declaration.directory == directory or not declaration.governs(path):
            continue
        hit = declaration.layer_of(path)
        if hit is not None and hit.layer == TEST_LAYER:
            return True
    return False


# --- Pure helpers: one file --------------------------------------------------


def _under(directory: str, pattern: str, where: str) -> str:
    if pattern.startswith("/") or ".." in pattern.split("/"):
        raise DeclarationUnreadable(f"{where}: {pattern!r} leaves the directory")
    return pattern if directory == "" else f"{directory}/{pattern}"


def _patterns(value: object, where: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(p, str) for p in value):
        raise DeclarationUnreadable(f"{where} is a list of path patterns")
    return [str(p) for p in value]


def _layers(value: object, directory: str, name: str) -> tuple[LayerGlob, ...]:
    if not isinstance(value, dict):
        raise DeclarationUnreadable(f"{name}: layers is a table")
    globs: list[LayerGlob] = []
    for key, patterns in value.items():
        if key == REGIONS_KEY:
            continue
        if key not in KNOWN_LAYERS:
            raise DeclarationUnreadable(f"{name}: {key!r} is not a layer")
        for pattern in _patterns(patterns, f"{name}: layers.{key}"):
            globs.append(LayerGlob(key, _under(directory, pattern, name)))
    return tuple(globs)


def _runtimes(value: object, directory: str, name: str) -> tuple[RuntimeGlob, ...]:
    if not isinstance(value, dict):
        raise DeclarationUnreadable(f"{name}: runtimes is a table")
    globs: list[RuntimeGlob] = []
    for runtime, patterns in value.items():
        for pattern in _patterns(patterns, f"{name}: runtimes.{runtime}"):
            globs.append(RuntimeGlob(runtime, _under(directory, pattern, name)))
    return tuple(globs)


def _document(text: str, name: str) -> dict[str, object]:
    try:
        return tomllib.loads(text)
    except (tomllib.TOMLDecodeError, ValueError, RecursionError) as error:
        raise DeclarationUnreadable(f"{name}: {error}") from error


def parse_declaration(path: str, text: str) -> Declaration:
    """One adherence.toml's text, its patterns resolved under its directory.

    Raises:
        DeclarationUnreadable: the text is not TOML, or [layers] or
            [runtimes] is not the shape the format gives them.
    """
    document = _document(text, path)
    overriding = document.get(OVERRIDE, {})
    if not isinstance(overriding, dict):
        raise DeclarationUnreadable(f"{path}: override is a table of sections")
    directory = posixpath.dirname(path)
    layers_value = overriding.get("layers", document.get("layers", {}))
    runtimes_value = overriding.get("runtimes", document.get("runtimes", {}))
    return Declaration(
        path=path,
        directory=directory,
        layers=_layers(layers_value, directory, path),
        runtimes=_runtimes(runtimes_value, directory, path),
        overrides_layers="layers" in overriding,
        overrides_runtimes="runtimes" in overriding,
    )


# --- Pure helpers: the governing declarations read as one --------------------


def declaration_order(path: str) -> tuple[int, str]:
    """Root first, then by depth, then by name."""
    directory = posixpath.dirname(path)
    return (directory.count("/") + 1 if directory else 0, path)


def governing(declarations: Sequence[Declaration], path: str) -> list[Declaration]:
    """The declarations whose subtree holds a path, root first."""
    held = [d for d in declarations if d.governs(path)]
    return sorted(held, key=lambda d: declaration_order(d.path))


def effective_layers(chain: Sequence[Declaration]) -> tuple[LayerGlob, ...]:
    """The union of a root-first chain's layer patterns; an override voids
    everything above it."""
    globs: list[LayerGlob] = []
    for declaration in chain:
        if declaration.overrides_layers:
            globs = []
        globs.extend(declaration.layers)
    return tuple(globs)


def effective_runtimes(chain: Sequence[Declaration]) -> tuple[RuntimeGlob, ...]:
    """The union of a root-first chain's runtime patterns; an override voids
    everything above it."""
    globs: list[RuntimeGlob] = []
    for declaration in chain:
        if declaration.overrides_runtimes:
            globs = []
        globs.extend(declaration.runtimes)
    return tuple(globs)


def winning_glob(globs: Sequence[LayerGlob], path: str) -> LayerGlob | None:
    """The layer pattern that claims a path: a literal beats a glob, a longer
    pattern a shorter one; None when no pattern matches."""
    hits = [g for g in globs if matches(g.pattern, path)]
    if not hits:
        return None
    return max(hits, key=lambda g: specificity(g.pattern))


def runtimes_of(globs: Sequence[RuntimeGlob], path: str) -> frozenset[str]:
    """The runtimes whose patterns match a path."""
    return frozenset(g.runtime for g in globs if matches(g.pattern, path))


def runtime_names(declarations: Sequence[Declaration]) -> tuple[str, ...]:
    """Every runtime any declaration names, in first-seen order."""
    seen: dict[str, None] = {}
    for declaration in sorted(declarations, key=lambda d: declaration_order(d.path)):
        for glob in declaration.runtimes:
            seen.setdefault(glob.runtime, None)
    return tuple(seen)


def layer_depth(layer: str) -> int:
    """A layer's depth: 0 for the composition root, deeper inward; -1 for the
    test layer, outside all of them."""
    return LAYER_ORDER.index(layer) if layer in LAYER_ORDER else -1
