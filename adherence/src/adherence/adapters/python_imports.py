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
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from adherence.domain.deadline import Deadline
from adherence.domain.model import ImportEdge

# --- Constants ---------------------------------------------------------------

INIT = "__init__.py"
# Run in the child: argv is the root to search, then the package names.
GRIMP_RUNNER = """
import json, sys
root, names = sys.argv[1], sys.argv[2:]
sys.path.insert(0, root)
import grimp
graph = grimp.build_graph(*names, include_external_packages=True, cache_dir=None)
edges = []
for importer in sorted(graph.modules):
    if importer.split(".")[0] not in names:
        continue
    for imported in sorted(graph.find_modules_directly_imported_by(importer)):
        for detail in graph.get_import_details(importer=importer, imported=imported):
            edges.append(
                [importer, imported, detail["line_number"], detail["line_contents"]]
            )
json.dump(edges, sys.stdout)
"""


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


def _modules(sources: Mapping[str, bytes], packages: list[_Package]) -> dict[str, str]:
    """Module name -> source path, for every .py file inside a package."""
    found: dict[str, str] = {}
    for package in packages:
        prefix = PurePosixPath(package.root, package.name).as_posix()
        if package.root == ".":
            prefix = package.name
        for path in sources:
            if path.endswith(".py") and (
                path == prefix or path.startswith(prefix + "/")
            ):
                found[_module_of(path, package.root)] = path
    return found


def _script_edges(
    path: str, tree: ast.Module, lines: list[str], modules: Mapping[str, str]
) -> list[ImportEdge]:
    """The absolute imports of a file outside any package."""
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
            edges.append(ImportEdge(path, name, node.lineno, text, modules.get(name)))
    return edges


# --- Effectful helpers -------------------------------------------------------


def _grimp_edges(
    sources: Mapping[str, bytes],
    packages: list[_Package],
    modules: Mapping[str, str],
    deadline: Deadline | None,
) -> list[ImportEdge]:
    edges: list[ImportEdge] = []
    roots: dict[str, list[str]] = {}
    for package in packages:
        roots.setdefault(package.root, []).append(package.name)
    with tempfile.TemporaryDirectory(prefix="adhere-imports-") as scratch:
        for path, data in sources.items():
            if path in modules.values():
                target = Path(scratch, "tree", path)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
        for root, names in roots.items():
            for importer, imported, line, text in _run_grimp(
                Path(scratch), Path(scratch, "tree", root), names, deadline
            ):
                importer_path = modules.get(importer)
                if importer_path is not None:
                    edges.append(
                        ImportEdge(
                            importer_path, imported, line, text, modules.get(imported)
                        )
                    )
    return edges


def _run_grimp(
    scratch: Path, root: Path, names: list[str], deadline: Deadline | None
) -> list[tuple[str, str, int, str]]:
    timeout = None
    if deadline is not None:
        timeout = deadline.epoch_seconds - time.time()
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
            [sys.executable, "-I", "-c", GRIMP_RUNNER, str(root), *names],
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
        raise ImportGraphFailed(f"the import graph failed: {reason}") from failed
    return [
        (str(importer), str(imported), int(line), str(text))
        for importer, imported, line, text in json.loads(done.stdout)
    ]


# --- Entry point -------------------------------------------------------------


def import_edges(
    sources: Mapping[str, bytes],
    trees: Mapping[str, ast.Module],
    deadline: Deadline | None,
) -> list[ImportEdge]:
    """Every import edge of the parsed sources: grimp for package modules,
    ast for the rest. Raises ImportGraphFailed when grimp cannot answer."""
    packages = _packages(sources)
    modules = _modules(sources, packages)
    edges = _grimp_edges(sources, packages, modules, deadline) if packages else []
    in_packages = set(modules.values())
    for path, tree in trees.items():
        if path not in in_packages:
            lines = sources[path].decode("utf-8", "replace").splitlines()
            edges.extend(_script_edges(path, tree, lines, modules))
    return sorted(edges, key=lambda e: (e.path, e.line, e.imported))
