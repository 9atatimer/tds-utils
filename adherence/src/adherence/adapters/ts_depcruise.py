"""adapters/ts_depcruise.py -- CodeModelPort for TypeScript and JavaScript.

The structural facts come from the shared ast-grep adapter's TypeScript
rules; which file each import resolves to comes from dependency-cruiser.
JavaScript is read with the TSX grammar, which parses it and JSX alike.

Both analyzers run as subprocesses over a copy of the sources in a scratch
directory, never the repository; dependency-cruiser runs with
`--no-config`, so no configuration the sources carry is ever loaded, with
an allowlisted environment and the time left before the deadline as its
bound. Nothing in the sources is imported or run (ARCHITECTURE.ARCH-
ADHERENCE.md, Security mitigations).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path

from adherence.adapters.astgrep import (
    BINARY,
    Grammar,
    Match,
    file_model,
    merged,
    scan,
    write_tree,
)
from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.declaration import Declaration, marker_regions
from adherence.domain.model import CodeModel, ImportEdge
from adherence.domain.parameters import Vocabulary

# --- Constants ---------------------------------------------------------------

GRAMMAR = Grammar(
    rules="typescript.yml",
    languages={
        "TypeScript": (),
        "Tsx": ("*.js", "*.mjs", "*.cjs", "*.jsx"),
    },
)
# The node analyzers, installed from adherence/node/package-lock.json.
CRUISER = (
    Path(__file__).resolve().parents[3]
    / "node"
    / "node_modules"
    / "dependency-cruiser"
    / "bin"
    / "dependency-cruiser.mjs"
)

Resolved = dict[tuple[str, str], str]

# --- Helpers -----------------------------------------------------------------


def _passed(deadline: Deadline | None, now: float) -> bool:
    return deadline is not None and deadline.epoch_seconds <= now


def _resolved(answer: Mapping[str, object]) -> Resolved:
    """dependency-cruiser's JSON as (importing file, module as written) ->
    the file it resolves to."""
    found: Resolved = {}
    modules = answer.get("modules", [])
    assert isinstance(modules, list)
    for module in modules:
        for dependency in module.get("dependencies", []):
            found[(str(module["source"]), str(dependency["module"]))] = str(
                dependency["resolved"]
            )
    return found


def _resolve(
    edges: Sequence[ImportEdge], resolved: Resolved, sources: Mapping[str, bytes]
) -> tuple[ImportEdge, ...]:
    """Each edge with the source file its module resolves to, if any."""
    found: list[ImportEdge] = []
    for edge in edges:
        target = resolved.get((edge.path, edge.imported))
        inside = target is not None and target in sources
        found.append(replace(edge, imported_path=target if inside else None))
    return tuple(found)


def _cruise(
    sources: Mapping[str, bytes],
    *,
    cruiser: Path,
    deadline: Deadline | None,
    clock: Callable[[], float],
) -> Resolved:
    """Where each import of the sources resolves, by dependency-cruiser."""
    timeout = None if deadline is None else deadline.epoch_seconds - clock()
    with tempfile.TemporaryDirectory(prefix="adhere-depcruise-") as scratch:
        tree = Path(scratch, "tree")
        write_tree(tree, sources)
        environment = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "LANG": "C.UTF-8",
            "HOME": scratch,
            "TMPDIR": scratch,
        }
        node = shutil.which("node", path=environment["PATH"]) or "node"
        done = subprocess.run(
            [
                node,
                str(cruiser),
                "--no-config",
                "--ts-pre-compilation-deps",
                "--output-type",
                "json",
                ".",
            ],
            capture_output=True,
            check=True,
            cwd=tree,
            env=environment,
            timeout=timeout,
        )
    return _resolved(json.loads(done.stdout))


# --- Adapter -----------------------------------------------------------------


class TypeScriptCodeModel:
    """CodeModelPort over TypeScript and JavaScript sources. The clock is the
    edge's own, read before each step and handed to each analyzer."""

    def __init__(
        self,
        *,
        ast_grep: Path = BINARY,
        cruiser: Path = CRUISER,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._ast_grep = ast_grep
        self._cruiser = cruiser
        self._clock = clock

    def model(
        self,
        sources: Mapping[str, bytes],
        declaration: Declaration,
        vocabulary: Vocabulary,
        deadline: Deadline | None,
    ) -> CodeModel | TimedOut:
        if _passed(deadline, self._clock()):
            return TimedOut("model the TypeScript sources")
        matches = scan(
            sources,
            GRAMMAR,
            binary=self._ast_grep,
            deadline=deadline,
            clock=self._clock,
        )
        found = tuple(
            region
            for path in declaration.layers.marker_files
            if path in sources
            for region in marker_regions(
                path, sources[path].decode("utf-8", "replace"), vocabulary
            )
        )
        declared = tuple(r for r in declaration.layers.regions if r.path in sources)
        by_path: dict[str, list[Match]] = {path: [] for path in sources}
        for match in matches:
            by_path.setdefault(match.path, []).append(match)
        files = [
            file_model(
                path, sources[path], by_path[path], declaration, found, vocabulary
            )
            for path in sorted(sources)
        ]
        edges = [edge for f in files for edge in f.imports]
        resolved = (
            _cruise(
                sources, cruiser=self._cruiser, deadline=deadline, clock=self._clock
            )
            if edges
            else {}
        )
        return merged(
            files,
            imports=_resolve(edges, resolved, sources),
            regions=declared + found,
        )
