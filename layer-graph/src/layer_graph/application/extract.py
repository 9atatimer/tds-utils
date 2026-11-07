"""The use case: extract a repository's layer graph.

Reads every adherence.toml and the unit files they declare through the
RepoSource port, and returns the LayerGraph value. Every rule it applies is
a domain function; this module only sequences them over what it reads.
"""

import posixpath
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from layer_graph.domain.context import (
    Origin,
    context_for,
    package_of,
    qualified_contexts,
)
from layer_graph.domain.declaration import (
    LAYER_ORDER,
    TEST_LAYER,
    Declaration,
    declaration_order,
    effective_layers,
    effective_runtimes,
    governing,
    is_declaration_path,
    is_test_data,
    layer_depth,
    parse_declaration,
    runtime_names,
    runtimes_of,
    winning_glob,
)
from layer_graph.domain.errors import DeclarationUnreadable, NoDeclaration
from layer_graph.domain.glob import static_prefix
from layer_graph.domain.graph import cycles, direction
from layer_graph.domain.imports import python_imports, ts_specifiers, vue_scripts
from layer_graph.domain.report import Edge, LayerGraph, Node, Stats
from layer_graph.domain.resolve import (
    PathScope,
    Workspace,
    load_json,
    package_from_manifest,
    python_roots,
    resolve_python,
    resolve_ts,
    tsconfig_from,
)
from layer_graph.ports import RepoSource

__all__ = ["DeclarationUnreadable", "NoDeclaration", "extract"]

# --- Constants ---------------------------------------------------------------

SOURCE_EXTENSIONS = (".ts", ".tsx", ".js", ".mjs", ".vue", ".py")
PACKAGE_MANIFESTS = ("package.json", "pyproject.toml")
TSCONFIG_NAME = "tsconfig.json"


# --- Values ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Unit:
    """A source file the graph covers: its path, layer, origin and runtimes."""

    path: str
    origin: Origin
    runtimes: frozenset[str]


@dataclass(frozen=True, slots=True)
class Classified:
    """The repository's source files sorted into units and unassigned."""

    units: tuple[Unit, ...]
    unassigned: tuple[str, ...]


# --- Predicates --------------------------------------------------------------


def _is_source(path: str) -> bool:
    return path.endswith(SOURCE_EXTENSIONS)


# --- Flow: declarations ------------------------------------------------------


def read_declarations(
    files: Sequence[str], *, source: RepoSource
) -> tuple[Declaration, ...]:
    """Every declaration in the repository, root first; a file a declaration
    above assigns to the test layer is test data and skipped.

    Raises:
        NoDeclaration: there is no adherence.toml.
        DeclarationUnreadable: one cannot be read.
    """
    paths = sorted(filter(is_declaration_path, files), key=declaration_order)
    if not paths:
        raise NoDeclaration(f"no adherence.toml under {source.root}")
    read: list[Declaration] = []
    for path in paths:
        if is_test_data(path, read):
            continue
        text = source.read_text(path)
        if text is None:
            raise DeclarationUnreadable(f"{path}: cannot be read")
        read.append(parse_declaration(path, text))
    return tuple(read)


# --- Flow: the workspace ---------------------------------------------------------


def _tsconfig_mappings(
    path: str, *, source: RepoSource
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """A tsconfig's paths with those of every config it extends or
    references; the first config to map a pattern wins."""
    found: dict[str, tuple[str, ...]] = {}
    queue = [path]
    seen: set[str] = set()
    while queue:
        current = queue.pop(0)
        if current in seen:
            continue
        seen.add(current)
        text = source.read_text(current)
        if text is None:
            continue
        config = tsconfig_from(current, load_json(text, comments=True))
        for pattern, targets in config.mappings:
            found.setdefault(pattern, targets)
        queue.extend((*config.references, *config.extends))
    return tuple(found.items())


def read_workspace(files: Sequence[str], *, source: RepoSource) -> Workspace:
    """The resolution context: workspace packages, tsconfig path scopes and
    Python roots."""
    packages = []
    scopes = []
    for path in files:
        name = posixpath.basename(path)
        if name == "package.json":
            text = source.read_text(path)
            package = package_from_manifest(
                posixpath.dirname(path), load_json(text) if text else None
            )
            if package is not None:
                packages.append(package)
        elif name == TSCONFIG_NAME:
            mappings = _tsconfig_mappings(path, source=source)
            if mappings:
                scopes.append(PathScope(posixpath.dirname(path), mappings))
    return Workspace(
        files=frozenset(files),
        packages=tuple(packages),
        scopes=tuple(scopes),
        python_roots=python_roots(files),
    )


# --- Flow: units -----------------------------------------------------------------


def classify(
    files: Sequence[str],
    declarations: Sequence[Declaration],
    *,
    include_tests: bool,
) -> Classified:
    """Each governed source file as a unit of its layer, or unassigned."""
    package_dirs = [
        posixpath.dirname(f)
        for f in files
        if posixpath.basename(f) in PACKAGE_MANIFESTS
    ]
    units: list[Unit] = []
    unassigned: list[str] = []
    for path in files:
        if not _is_source(path):
            continue
        chain = governing(declarations, path)
        if not chain:
            continue
        glob = winning_glob(effective_layers(chain), path)
        if glob is None:
            unassigned.append(path)
            continue
        if glob.layer == TEST_LAYER and not include_tests:
            continue
        prefix = static_prefix(glob.pattern)
        origin = Origin(
            glob.layer,
            prefix,
            context_for(glob.pattern, path),
            package_of(prefix, package_dirs),
        )
        units.append(Unit(path, origin, runtimes_of(effective_runtimes(chain), path)))
    return Classified(tuple(units), tuple(unassigned))


# --- Flow: imports -----------------------------------------------------------------


def _targets(
    path: str, *, source: RepoSource, workspace: Workspace
) -> list[tuple[str, ...]]:
    """Per import statement in a unit file, the repository files it reaches."""
    text = source.read_text(path) or ""
    if path.endswith(".py"):
        return [resolve_python(path, i, workspace) for i in python_imports(text)]
    if path.endswith(".vue"):
        text = vue_scripts(text)
    found = (resolve_ts(path, s, workspace) for s in ts_specifiers(text))
    return [(t,) if t else () for t in found]


# --- Flow: the use case ------------------------------------------------------------


def extract(*, source: RepoSource, include_tests: bool = False) -> LayerGraph:
    """A repository's layer graph: its nodes, the edges between them, and the
    findings (outward edges, cycles, unassigned files).

    Raises:
        NoDeclaration: the repository has no adherence.toml.
        DeclarationUnreadable: a declaration cannot be read.
    """
    files = source.files()
    declarations = read_declarations(files, source=source)
    workspace = read_workspace(files, source=source)
    classified = classify(files, declarations, include_tests=include_tests)
    names = qualified_contexts(u.origin for u in classified.units)
    node_of = {u.path: f"{u.origin.layer}/{names[u.origin]}" for u in classified.units}

    members: dict[str, list[Unit]] = defaultdict(list)
    for unit in classified.units:
        members[node_of[unit.path]].append(unit)

    counts: Counter[tuple[str, str]] = Counter()
    imports = unresolved = 0
    for unit in classified.units:
        for reached in _targets(unit.path, source=source, workspace=workspace):
            imports += 1
            if not reached:
                unresolved += 1
            targets = {node_of[t] for t in reached if t in node_of}
            for target in targets - {node_of[unit.path]}:
                counts[(node_of[unit.path], target)] += 1

    nodes = _nodes(members, names)
    layer_of = {n.id: n.layer for n in nodes}
    edges = tuple(
        Edge(s, t, n, direction(layer_of[s], layer_of[t]))
        for (s, t), n in sorted(counts.items())
    )
    repo, commit = source.identity()
    return LayerGraph(
        root=source.root,
        repo=repo,
        commit=commit,
        declarations=tuple(d.path for d in declarations),
        runtimes={
            name: tuple(n.id for n in nodes if name in n.runtimes)
            for name in runtime_names(declarations)
        },
        nodes=nodes,
        edges=edges,
        cycles=tuple(tuple(c) for c in cycles(counts)),
        unassigned=classified.unassigned,
        stats=Stats(len(classified.units), imports, unresolved),
    )


def _node_order(node: Node) -> tuple[int, str]:
    depth = layer_depth(node.layer)
    return (depth if depth >= 0 else len(LAYER_ORDER), node.context)


def _nodes(
    members: dict[str, list[Unit]], names: dict[Origin, str]
) -> tuple[Node, ...]:
    built = []
    for node_id, units in members.items():
        origin = units[0].origin
        built.append(
            Node(
                id=node_id,
                layer=origin.layer,
                context=names[origin],
                files=tuple(sorted(u.path for u in units)),
                runtimes=tuple(sorted(set().union(*(u.runtimes for u in units)))),
            )
        )
    return tuple(sorted(built, key=_node_order))
