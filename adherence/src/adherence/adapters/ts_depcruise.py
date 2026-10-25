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
    ScanFailed,
    file_model,
    merged,
    scan,
    syntax_errors,
    write_tree,
)
from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.declaration import Declaration, marker_regions
from adherence.domain.model import CodeModel, ImportEdge, Unparsed
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

NESTED_TOO_DEEPLY = "nested deeper than the analyzer can walk"


class CruiseFailed(Exception):
    """dependency-cruiser, or the node it runs on, could not answer, or ran
    past the deadline."""

    def __init__(self, reason: str, *, timed_out: bool = False) -> None:
        super().__init__(reason)
        self.timed_out = timed_out


Resolved = dict[tuple[str, str], str]

# --- Helpers -----------------------------------------------------------------


def _passed(deadline: Deadline | None, now: float) -> bool:
    return deadline is not None and deadline.epoch_seconds <= now


def _paths(unparsed: Sequence[Unparsed]) -> set[str]:
    return {u.path for u in unparsed}


def _readable(
    sources: Mapping[str, bytes],
) -> tuple[dict[str, bytes], list[Unparsed]]:
    """The sources that are UTF-8, and why each other one is not read."""
    readable: dict[str, bytes] = {}
    unreadable: list[Unparsed] = []
    for path in sorted(sources):
        try:
            sources[path].decode("utf-8")
        except UnicodeDecodeError as error:
            unreadable.append(Unparsed(path, f"not utf-8: {error}"))
            continue
        readable[path] = sources[path]
    return readable, unreadable


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
    if timeout is not None and timeout <= 0:
        raise CruiseFailed("resolve the imports", timed_out=True)
    with tempfile.TemporaryDirectory(prefix="adhere-depcruise-") as scratch:
        tree = Path(scratch, "tree")
        write_tree(tree, sources)
        environment = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "LANG": "C.UTF-8",
            "HOME": scratch,
            "TMPDIR": scratch,
        }
        node = shutil.which("node", path=environment["PATH"])
        if node is None:
            raise CruiseFailed(
                "node is not installed, so dependency-cruiser cannot run"
            )
        if not cruiser.is_file():
            raise CruiseFailed(
                f"dependency-cruiser is not installed at {cruiser}: "
                "npm ci --ignore-scripts in adherence/node"
            )
        try:
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
        except subprocess.TimeoutExpired as expired:
            raise CruiseFailed("resolve the imports", timed_out=True) from expired
        except subprocess.CalledProcessError as failed:
            complaint = failed.stderr.decode("utf-8", "replace").strip().splitlines()
            reason = complaint[0] if complaint else f"exit {failed.returncode}"
            raise CruiseFailed(f"dependency-cruiser failed: {reason}") from failed
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
        readable, unparsed = _readable(sources)
        try:
            matches = scan(
                readable,
                GRAMMAR,
                binary=self._ast_grep,
                deadline=deadline,
                clock=self._clock,
            )
        except ScanFailed as failure:
            if failure.timed_out:
                return TimedOut(str(failure))
            unparsed.extend(Unparsed(path, str(failure)) for path in readable)
            return CodeModel(unparsed=tuple(sorted(unparsed, key=lambda u: u.path)))
        found = tuple(
            region
            for path in declaration.layers.marker_files
            if path in sources
            for region in marker_regions(
                path, sources[path].decode("utf-8", "replace"), vocabulary
            )
        )
        declared = tuple(r for r in declaration.layers.regions if r.path in sources)
        errors = syntax_errors(matches)
        unparsed.extend(
            Unparsed(path, f"not TypeScript: syntax error at line {line}")
            for path, line in sorted(errors.items())
        )
        parsed = {p: data for p, data in readable.items() if p not in errors}
        by_path: dict[str, list[Match]] = {path: [] for path in parsed}
        for match in matches:
            if match.path in by_path:
                by_path[match.path].append(match)
        files: list[CodeModel] = []
        for path in sorted(parsed):
            try:
                files.append(
                    file_model(
                        path,
                        parsed[path],
                        by_path[path],
                        declaration,
                        found,
                        vocabulary,
                    )
                )
            except RecursionError:
                unparsed.append(Unparsed(path, NESTED_TOO_DEEPLY))
        parsed = {p: data for p, data in parsed.items() if p not in _paths(unparsed)}
        edges = [edge for f in files for edge in f.imports]
        resolved: Resolved = {}
        try:
            if edges:
                resolved = _cruise(
                    parsed, cruiser=self._cruiser, deadline=deadline, clock=self._clock
                )
        except CruiseFailed as failure:
            if failure.timed_out:
                return TimedOut(str(failure))
            unparsed.extend(Unparsed(path, str(failure)) for path in parsed)
        return merged(
            files,
            imports=_resolve(edges, resolved, parsed),
            regions=declared + found,
            unparsed=tuple(sorted(unparsed, key=lambda u: u.path)),
        )
