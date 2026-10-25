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
    Scanned,
    merged,
    structure,
    write_tree,
)
from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.declaration import Declaration
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


class CruiseFailed(Exception):
    """dependency-cruiser, or the node it runs on, could not answer, or ran
    past the deadline."""

    def __init__(self, reason: str, *, timed_out: bool = False) -> None:
        super().__init__(reason)
        self.timed_out = timed_out


Resolved = dict[tuple[str, str], str]

# --- Pure helpers ------------------------------------------------------------


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
        scanned = structure(
            sources,
            declaration,
            vocabulary,
            deadline,
            grammar=GRAMMAR,
            language="TypeScript",
            binary=self._ast_grep,
            clock=self._clock,
        )
        if isinstance(scanned, TimedOut):
            return scanned
        return self._resolved_model(scanned, deadline)

    def _resolved_model(
        self, scanned: Scanned, deadline: Deadline | None
    ) -> CodeModel | TimedOut:
        """The structural pass with each import resolved to its file by
        dependency-cruiser; a failure leaves every parsed file unparsed."""
        unparsed = list(scanned.unparsed)
        edges = [edge for f in scanned.files for edge in f.imports]
        resolved: Resolved = {}
        try:
            if edges:
                resolved = _cruise(
                    scanned.parsed,
                    cruiser=self._cruiser,
                    deadline=deadline,
                    clock=self._clock,
                )
        except CruiseFailed as failure:
            if failure.timed_out:
                return TimedOut(str(failure))
            unparsed.extend(
                Unparsed(path=path, reason=str(failure)) for path in scanned.parsed
            )
        return merged(
            scanned.files,
            imports=_resolve(edges, resolved, scanned.parsed),
            regions=scanned.regions,
            unparsed=tuple(sorted(unparsed, key=lambda u: u.path)),
        )
