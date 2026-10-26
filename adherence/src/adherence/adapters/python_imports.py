"""adapters/python_imports.py -- Python import edges, resolved by grimp.

grimp finds packages through sys.path and sys.modules, so it never runs in
the engine's own process: a measured package named like one the engine
has loaded (`adherence`, when the engine measures itself) would resolve
to the engine. The packages are copied to a scratch directory and grimp
runs over them in an isolated child interpreter, with an allowlisted
environment, its working directory outside the repository, and the time
left before the deadline as its bound. A file outside any package (a
script, a test) has its absolute imports read with ast.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from adherence.domain.deadline import Deadline
from adherence.domain.model import ImportEdge, Unparsed
from adherence.domain.source import source_lines

# --- Constants ---------------------------------------------------------------

INIT = "__init__.py"
# Run in the child: argv[1] is a JSON map of each package name to the root
# holding it; one run never holds two packages of one name. No root joins
# sys.path. A finder answers for the measured names
# alone, from the root, with a loader that refuses to execute anything, so
# grimp can locate the packages but no measured module can run, even one
# named like a module grimp imports lazily. A measured name the child has
# already loaded (grimp, logging) would resolve to the loaded module, so it
# is reported as shadowed and not modelled.
GRIMP_RUNNER = """
import importlib.abc, importlib.machinery, json, sys
roots = json.loads(sys.argv[1])
names = sorted(roots)
import grimp

class Refuse(importlib.abc.Loader):
    def create_module(self, spec):
        return None
    def exec_module(self, module):
        raise ImportError("measured code is never run: " + module.__name__)

class Measured(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        top = fullname.split(".")[0]
        if top not in roots:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path or [roots[top]])
        if spec is not None:
            spec.loader = Refuse()
        return spec

shadowed = sorted(n for n in names if n in sys.modules)
names = [n for n in names if n not in sys.modules]
sys.meta_path.insert(0, Measured())
edges = []
if names:
    graph = grimp.build_graph(*names, include_external_packages=True, cache_dir=None)
    for importer in sorted(graph.modules):
        if importer.split(".")[0] not in names:
            continue
        for imported in sorted(graph.find_modules_directly_imported_by(importer)):
            for d in graph.get_import_details(importer=importer, imported=imported):
                edges.append([importer, imported, d["line_number"], d["line_contents"]])
json.dump({"edges": edges, "shadowed": shadowed}, sys.stdout)
"""
SHADOWED = "named like a module the import analyzer runs on; not modelled"


class ImportGraphFailed(Exception):
    """grimp could not build the graph, or ran past the deadline."""

    def __init__(self, reason: str, *, timed_out: bool = False) -> None:
        super().__init__(reason)
        self.timed_out = timed_out


@dataclass(frozen=True, slots=True)
class _Package:
    root: str  # the directory holding the top-level package, repository-relative
    name: str


# --- Pure helpers ------------------------------------------------------------


def _packages(sources: Mapping[str, bytes]) -> list[_Package]:
    """Every top-level package: a directory with __init__.py whose parent has none."""
    found: list[_Package] = []
    for path in sorted(sources):
        pure = PurePosixPath(path)
        if pure.name != INIT:
            continue
        parent = pure.parent.parent
        if (parent / INIT).as_posix() not in sources:
            found.append(_Package(parent.as_posix(), pure.parent.name))
    return found


def _module_of(path: str, root: str) -> str:
    relative = (
        PurePosixPath(path).relative_to(root) if root != "." else PurePosixPath(path)
    )
    parts = list(relative.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


Modules = dict[str, dict[str, str]]


def _modules(sources: Mapping[str, bytes], packages: list[_Package]) -> Modules:
    """Per root, module name -> source path, for every .py file inside a
    package. Keyed by root, because two roots may hold packages of one name."""
    found: Modules = {}
    for package in packages:
        prefix = PurePosixPath(package.root, package.name).as_posix()
        if package.root == ".":
            prefix = package.name
        for path in sources:
            if path.endswith(".py") and (
                path == prefix or path.startswith(prefix + "/")
            ):
                found.setdefault(package.root, {})[_module_of(path, package.root)] = (
                    path
                )
    return found


def _flat(modules: Modules) -> dict[str, str]:
    """Module name -> path across every root; the first root in order wins a
    name two roots share, which is what a script importing it would get."""
    flat: dict[str, str] = {}
    for root in sorted(modules):
        for name, path in modules[root].items():
            flat.setdefault(name, path)
    return flat


def beside(path: str, name: str, present: Collection[str]) -> str | None:
    """The source a script's import names in the script's own directory,
    which Python searches first: a module file, or a package's __init__."""
    base = PurePosixPath(path).parent.joinpath(*name.split("."))
    for candidate in (base.with_suffix(".py"), base / INIT):
        if candidate.as_posix() in present:
            return candidate.as_posix()
    return None


def _script_edges(
    path: str,
    tree: ast.Module,
    lines: list[str],
    modules: Mapping[str, str],
    present: Collection[str],
) -> list[ImportEdge]:
    """The absolute imports of a file outside any package, resolved first
    beside the file, then among the packages."""
    edges: list[ImportEdge] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [
                f"{node.module}.{alias.name}"
                if f"{node.module}.{alias.name}" in modules
                else node.module
                for alias in node.names
            ]
        else:
            continue
        text = lines[node.lineno - 1].strip()
        for name in dict.fromkeys(names):
            target = beside(path, name, present) or modules.get(name)
            edges.append(ImportEdge(path, name, node.lineno, text, target))
    return edges


def module_names(sources: Mapping[str, bytes]) -> dict[str, str]:
    """Module name -> source path for every module inside a package, the
    first root in order winning a name two roots share."""
    return _flat(_modules(sources, _packages(sources)))


def modules_of(sources: Mapping[str, bytes]) -> dict[str, str]:
    """Source path -> module name for every module inside a package."""
    return {
        path: name
        for table in _modules(sources, _packages(sources)).values()
        for name, path in table.items()
    }


# --- Effectful helpers -------------------------------------------------------


def _runs(packages: list[_Package]) -> list[list[_Package]]:
    """The packages split into as few grimp runs as possible, no run holding
    two packages of one name, so imports cross roots and same names stay apart."""
    runs: list[list[_Package]] = []
    for package in sorted(packages, key=lambda p: (p.root, p.name)):
        for run in runs:
            if all(other.name != package.name for other in run):
                run.append(package)
                break
        else:
            runs.append([package])
    return runs


def _grimp_edges(
    sources: Mapping[str, bytes],
    packages: list[_Package],
    modules: Modules,
    deadline: Deadline | None,
    clock: Callable[[], float],
) -> tuple[list[ImportEdge], list[tuple[str, str]]]:
    """The packages' import edges, and the (root, name) of packages grimp
    could not model because they shadow a module it runs on."""
    edges: list[ImportEdge] = []
    shadowed: list[tuple[str, str]] = []
    in_packages = {path for table in modules.values() for path in table.values()}
    with tempfile.TemporaryDirectory(prefix="adhere-imports-") as scratch:
        tree = Path(scratch, "tree")
        for path, data in sources.items():
            if path in in_packages:
                target = tree / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
        for run in _runs(packages):
            roots = {p.name: str(tree / p.root) for p in run}
            found, skipped = _run_grimp(Path(scratch), roots, deadline, clock)
            root_of = {p.name: p.root for p in run}
            shadowed.extend((root_of[name], name) for name in skipped)
            table = {
                name: path
                for package in run
                for name, path in modules.get(package.root, {}).items()
                if name.split(".")[0] == package.name
            }
            for importer, imported, line, text in found:
                importer_path = table.get(importer)
                if importer_path is not None:
                    edges.append(
                        ImportEdge(
                            importer_path, imported, line, text, table.get(imported)
                        )
                    )
    return edges, shadowed


def _run_grimp(
    scratch: Path,
    roots: Mapping[str, str],
    deadline: Deadline | None,
    clock: Callable[[], float],
) -> tuple[list[tuple[str, str, int, str]], list[str]]:
    timeout = None
    if deadline is not None:
        timeout = deadline.epoch_seconds - clock()
        if timeout <= 0:
            raise ImportGraphFailed("build the import graph", timed_out=True)
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": "C.UTF-8",
        "HOME": str(scratch),
        "TMPDIR": str(scratch),
    }
    try:
        done = subprocess.run(
            [sys.executable, "-I", "-c", GRIMP_RUNNER, json.dumps(dict(roots))],
            capture_output=True,
            check=True,
            cwd=scratch,
            env=environment,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as expired:
        raise ImportGraphFailed("build the import graph", timed_out=True) from expired
    except subprocess.CalledProcessError as failed:
        complaint = failed.stderr.decode("utf-8", "replace").strip().splitlines()
        reason = complaint[-1] if complaint else f"exit {failed.returncode}"
        reason = reason.replace(f"{scratch}/tree/", "")
        raise ImportGraphFailed(f"the import graph failed: {reason}") from failed
    answer = json.loads(done.stdout)
    edges = [
        (str(importer), str(imported), int(line), str(text))
        for importer, imported, line, text in answer["edges"]
    ]
    return edges, [str(name) for name in answer["shadowed"]]


# --- Entry point -------------------------------------------------------------


def import_edges(
    sources: Mapping[str, bytes],
    trees: Mapping[str, ast.Module],
    deadline: Deadline | None,
    clock: Callable[[], float],
) -> tuple[list[ImportEdge], list[Unparsed]]:
    """Every import edge of the parsed sources (grimp for package modules,
    ast for the rest) and the package files that could not be modelled.
    Raises ImportGraphFailed when grimp cannot answer."""
    # Only what parsed goes to grimp: one file that is not Python must not
    # fail the graph of every file beside it.
    parsed = {path: sources[path] for path in trees}
    packages = _packages(parsed)
    modules = _modules(parsed, packages)
    edges, shadowed = (
        _grimp_edges(parsed, packages, modules, deadline, clock)
        if packages
        else ([], [])
    )
    unparsed = [
        Unparsed(path, SHADOWED)
        for root, table in modules.items()
        for name, path in table.items()
        if (root, name.split(".")[0]) in shadowed
    ]
    in_packages = {path for table in modules.values() for path in table.values()}
    flat = _flat(modules)
    for path, tree in trees.items():
        if path not in in_packages:
            lines = source_lines(sources[path].decode("utf-8", "replace"))
            edges.extend(_script_edges(path, tree, lines, flat, parsed.keys()))
    return sorted(edges, key=lambda e: (e.path, e.line, e.imported)), unparsed
