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
import posixpath
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
    stays_inside,
    syntax_errors,
    write_tree,
)
from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.declaration import Declaration, marker_regions
from adherence.domain.model import CodeModel, ImportEdge, Region, Unparsed
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
LEAVES = "the path leaves the repository; not read"
# dependency-cruiser names the file it could not extract on a line of its own.
CULPRIT_PREFIX = "... in "
CRUISER_HEADER = "ERROR:"


class CruiseFailed(Exception):
    """dependency-cruiser, or the node it runs on, could not answer, or ran
    past the deadline; with the source it could not read, when it names one."""

    def __init__(
        self, reason: str, *, timed_out: bool = False, culprit: str | None = None
    ) -> None:
        super().__init__(reason)
        self.timed_out = timed_out
        self.culprit = culprit


Resolved = dict[tuple[str, str], str]

# --- Pure helpers ------------------------------------------------------------


def _passed(deadline: Deadline | None, now: float) -> bool:
    return deadline is not None and deadline.epoch_seconds <= now


def _paths(unparsed: Sequence[Unparsed]) -> set[str]:
    return {u.path for u in unparsed}


def _without(files: Sequence[CodeModel], paths: set[str]) -> list[CodeModel]:
    """The per-file models but those of the paths given."""
    return [f for f in files if not ({u.path for u in f.units} & paths)]


def _readable(
    sources: Mapping[str, bytes],
) -> tuple[dict[str, bytes], list[Unparsed]]:
    """The sources inside the repository that are UTF-8, and why each other
    one is not read."""
    readable: dict[str, bytes] = {}
    unreadable: list[Unparsed] = []
    for path in sorted(sources):
        if not stays_inside(path):
            unreadable.append(Unparsed(path=path, reason=LEAVES))
            continue
        try:
            sources[path].decode("utf-8")
        except UnicodeDecodeError as error:
            unreadable.append(Unparsed(path=path, reason=f"not utf-8: {error}"))
            continue
        readable[path] = sources[path]
    return readable, unreadable


def culprit_of(complaint: Sequence[str]) -> str | None:
    """The repository path of the source dependency-cruiser says it could
    not extract (printed relative to the copy it ran in), if it names one
    inside the copy."""
    for line in complaint:
        if line.startswith(CULPRIT_PREFIX):
            path = posixpath.normpath(line.removeprefix(CULPRIT_PREFIX).strip())
            return path if stays_inside(path) else None
    return None


def cause_of(complaint: Sequence[str], culprit: str) -> str:
    """Why dependency-cruiser could not read a source, naming it."""
    causes = [
        line
        for line in complaint
        if not line.startswith((CULPRIT_PREFIX, CRUISER_HEADER))
    ]
    because = f": {causes[0]}" if causes else ""
    return f"dependency-cruiser could not read {culprit}{because}"


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


def _regions(
    sources: Mapping[str, bytes], declaration: Declaration, vocabulary: Vocabulary
) -> tuple[tuple[Region, ...], tuple[Region, ...]]:
    """The declaration's line regions of the files handed over, and the
    regions their section markers open."""
    declared = tuple(r for r in declaration.layers.regions if r.path in sources)
    found = tuple(
        region
        for path in declaration.layers.marker_files
        if path in sources
        for region in marker_regions(
            path, sources[path].decode("utf-8", "replace"), vocabulary
        )
    )
    return declared, found


def _file_models(
    parsed: Mapping[str, bytes],
    matches: Sequence[Match],
    declaration: Declaration,
    regions: Sequence[Region],
    vocabulary: Vocabulary,
) -> tuple[list[CodeModel], list[Unparsed]]:
    """Each parsed file's facts, and the files nested past the walk."""
    by_path: dict[str, list[Match]] = {path: [] for path in parsed}
    for match in matches:
        if match.path in by_path:
            by_path[match.path].append(match)
    files: list[CodeModel] = []
    deep: list[Unparsed] = []
    for path in sorted(parsed):
        try:
            files.append(
                file_model(
                    path, parsed[path], by_path[path], declaration, regions, vocabulary
                )
            )
        except RecursionError:
            deep.append(Unparsed(path=path, reason=NESTED_TOO_DEEPLY))
    return files, deep


# --- Effectful helpers -------------------------------------------------------


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
            complaint = [
                line.strip()
                for line in failed.stderr.decode("utf-8", "replace").splitlines()
                if line.strip()
            ]
            culprit = culprit_of(complaint)
            if culprit is not None:
                raise CruiseFailed(
                    cause_of(complaint, culprit), culprit=culprit
                ) from failed
            reason = complaint[0] if complaint else f"exit {failed.returncode}"
            raise CruiseFailed(f"dependency-cruiser failed: {reason}") from failed
    return _resolved(json.loads(done.stdout))


def _cruise_around(
    sources: Mapping[str, bytes],
    *,
    cruiser: Path,
    deadline: Deadline | None,
    clock: Callable[[], float],
) -> tuple[Resolved, list[Unparsed]]:
    """Where each import resolves, cruising again without each source the
    cruiser names as one it cannot read, and why each of those is not read;
    one such source never costs the rest their imports."""
    left = dict(sources)
    dropped: list[Unparsed] = []
    while left:
        try:
            return (
                _cruise(left, cruiser=cruiser, deadline=deadline, clock=clock),
                dropped,
            )
        except CruiseFailed as failure:
            if failure.culprit not in left:
                raise
            dropped.append(Unparsed(path=failure.culprit, reason=str(failure)))
            del left[failure.culprit]
    return {}, dropped


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
            unparsed.extend(
                Unparsed(path=path, reason=str(failure)) for path in readable
            )
            return CodeModel(unparsed=tuple(sorted(unparsed, key=lambda u: u.path)))
        declared, found = _regions(sources, declaration, vocabulary)
        errors = syntax_errors(matches)
        unparsed.extend(
            Unparsed(path=path, reason=f"not TypeScript: syntax error at line {line}")
            for path, line in sorted(errors.items())
        )
        parsed = {p: data for p, data in readable.items() if p not in errors}
        files, deep = _file_models(parsed, matches, declaration, found, vocabulary)
        unparsed.extend(deep)
        parsed = {p: data for p, data in parsed.items() if p not in _paths(deep)}
        edges = [edge for f in files for edge in f.imports]
        resolved: Resolved = {}
        try:
            if edges:
                resolved, unread = _cruise_around(
                    parsed, cruiser=self._cruiser, deadline=deadline, clock=self._clock
                )
                unparsed.extend(unread)
                files = _without(files, _paths(unread))
                edges = [e for e in edges if e.path not in _paths(unread)]
                parsed = {p: d for p, d in parsed.items() if p not in _paths(unread)}
        except CruiseFailed as failure:
            if failure.timed_out:
                return TimedOut(str(failure))
            unparsed.extend(Unparsed(path=path, reason=str(failure)) for path in parsed)
        return merged(
            files,
            imports=_resolve(edges, resolved, parsed),
            regions=declared + found,
            unparsed=tuple(sorted(unparsed, key=lambda u: u.path)),
        )
