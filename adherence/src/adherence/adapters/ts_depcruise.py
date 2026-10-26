"""adapters/ts_depcruise.py -- CodeModelPort for TypeScript and JavaScript.

The structural facts come from the shared ast-grep adapter's TypeScript
rules; which file each import resolves to comes from dependency-cruiser.
JavaScript is read with the TSX grammar, which parses it and JSX alike.

Both analyzers run as subprocesses over a copy of the sources in a scratch
directory, never the repository; dependency-cruiser runs with
`--no-config`, so no configuration the sources carry is ever loaded: a
root tsconfig.json's path aliases are read here and handed over as a
configuration of their own, pointing only inside the copy. It runs with
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
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath

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
# The sources that are code: every other source is never a unit.
CODE_SUFFIXES = frozenset(
    {".ts", ".mts", ".cts", ".tsx", ".js", ".mjs", ".cjs", ".jsx"}
)
# The TypeScript configuration whose path aliases resolve imports, and the
# copy of its aliases the cruiser is given in its place.
TSCONFIG = "tsconfig.json"
ALIASES = "adhere-tsconfig.json"
# The bounds on walking a tsconfig's extends chain: how deep a chain is
# followed, and how many configurations are read in all.
MAX_EXTENDS_DEPTH = 32
MAX_TSCONFIGS = 128
EXTENDS_TOO_DEEP = (
    f"extended deeper than {MAX_EXTENDS_DEPTH} configurations; not followed"
)
TOO_MANY_TSCONFIGS = f"extended past {MAX_TSCONFIGS} configurations; not followed"
TSCONFIG_UNREAD = "tsconfig not read, so it gives no aliases"
TREE = "tree"


class CruiseFailed(Exception):
    """dependency-cruiser, or the node it runs on, could not answer, or ran
    past the deadline; with the source it could not read, when it names one."""

    def __init__(
        self, reason: str, *, timed_out: bool = False, culprit: str | None = None
    ) -> None:
        super().__init__(reason)
        self.timed_out = timed_out
        self.culprit = culprit


class WalkTimedOut(Exception):
    """The deadline passed while a tsconfig's extends chain was walked."""


class TsconfigUnread(Exception):
    """A tsconfig file the JSON parser could not read, with why."""


Resolved = dict[tuple[str, str], str]

# --- Pure helpers ------------------------------------------------------------


def _passed(deadline: Deadline | None, now: float) -> bool:
    return deadline is not None and deadline.epoch_seconds <= now


def _paths(unparsed: Sequence[Unparsed]) -> set[str]:
    return {u.path for u in unparsed}


def is_code(path: str) -> bool:
    return PurePosixPath(path).suffix in CODE_SUFFIXES


def _string_end(text: str, at: int) -> int:
    """Where the JSON string opening at a quote ends, just past its close."""
    end = at + 1
    while end < len(text) and text[end] != '"':
        end += 2 if text[end] == "\\" else 1
    return end + 1


def without_comments(text: str) -> str:
    """JSON with comments, as tsconfig is written, without its comments;
    a string's text is kept whatever it holds."""
    kept: list[str] = []
    at = 0
    while at < len(text):
        if text[at] == '"':
            end = _string_end(text, at)
            kept.append(text[at:end])
            at = end
        elif text.startswith("//", at):
            line_end = text.find("\n", at)
            at = len(text) if line_end < 0 else line_end
        elif text.startswith("/*", at):
            close = text.find("*/", at + 2)
            at = len(text) if close < 0 else close + 2
        else:
            kept.append(text[at])
            at += 1
    return "".join(kept)


def without_trailing_commas(text: str) -> str:
    """JSON without the commas that close an object or array, as tsconfig
    allows; a string's text is kept whatever it holds."""
    kept: list[str] = []
    at = 0
    while at < len(text):
        if text[at] == '"':
            end = _string_end(text, at)
            kept.append(text[at:end])
            at = end
            continue
        closing = text[at + 1 :].lstrip()[:1] in ("}", "]")
        if not (text[at] == "," and closing):
            kept.append(text[at])
        at += 1
    return "".join(kept)


def read_tsconfig(text: str) -> dict[str, object]:
    """A tsconfig file's settings; none when it is not a JSON object.
    Raises TsconfigUnread when it does not parse, or nests deeper than the
    parser can walk."""
    try:
        parsed = json.loads(without_trailing_commas(without_comments(text)))
    except json.JSONDecodeError as error:
        raise TsconfigUnread(f"{TSCONFIG_UNREAD}: {error}") from error
    except RecursionError as error:
        raise TsconfigUnread(f"{TSCONFIG_UNREAD}: {NESTED_TOO_DEEPLY}") from error
    return parsed if isinstance(parsed, dict) else {}


def _inside(directory: str, relative: object) -> str | None:
    """A path written relative to a directory, as a repository path; None
    when it is not a string or it leaves the repository."""
    if not isinstance(relative, str) or relative.startswith("/"):
        return None
    path = posixpath.normpath(posixpath.join(directory, relative))
    return path if path == "." or stays_inside(path) else None


def _extended(path: str, written: object, sources: Mapping[str, str]) -> list[str]:
    """The configurations a tsconfig extends that are sources: relative,
    inside the repository; a package or a path leaving it is not followed."""
    names = written if isinstance(written, list) else [written]
    found: list[str] = []
    for name in names:
        if not (isinstance(name, str) and name.startswith(("./", "../"))):
            continue
        target = _inside(posixpath.dirname(path), name)
        if target is not None and target not in sources:
            target = f"{target}.json"
        if target is not None and target in sources:
            found.append(target)
    return found


@dataclass(frozen=True, slots=True)
class Aliases:
    """A tsconfig's import aliases: its baseUrl (a repository directory),
    its paths, and the directory those paths are written relative to when
    there is no baseUrl."""

    base_url: str | None = None
    paths: Mapping[str, object] | None = None
    paths_from: str = "."

    def over(self, base: Aliases) -> Aliases:
        """These aliases over those of a configuration this one extends."""
        if self.paths is None:
            return replace(
                self,
                paths=base.paths,
                paths_from=base.paths_from,
                base_url=self.base_url or base.base_url,
            )
        return replace(self, base_url=self.base_url or base.base_url)


def _own_aliases(path: str, settings: Mapping[str, object]) -> Aliases | None:
    """The aliases a tsconfig sets itself; None when it sets no options."""
    options = settings.get("compilerOptions")
    if not isinstance(options, dict):
        return None
    directory = posixpath.dirname(path) or "."
    paths = options.get("paths")
    return Aliases(
        base_url=_inside(directory, options.get("baseUrl")),
        paths=paths if isinstance(paths, dict) else None,
        paths_from=directory,
    )


class TsconfigWalk:
    """One walk of a tsconfig's extends chain: each configuration read at
    most once, the chain bounded in depth and in configurations read, and
    the deadline read before each; why each configuration was not read or
    not followed is kept, by path: one that does not parse gives no
    aliases."""

    def __init__(
        self,
        sources: Mapping[str, str],
        *,
        deadline: Deadline | None,
        clock: Callable[[], float],
    ) -> None:
        self._sources = sources
        self._deadline = deadline
        self._clock = clock
        self._done: dict[str, Aliases] = {}
        self._open: set[str] = set()
        self.unread: dict[str, str] = {}

    def aliases(self, path: str, depth: int = 0) -> Aliases:
        """A tsconfig's aliases, through the configurations it extends that
        are sources, in order; the nearer setting wins."""
        if _passed(self._deadline, self._clock()):
            raise WalkTimedOut("read the tsconfig extends chain")
        self._open.add(path)
        try:
            settings = read_tsconfig(self._sources[path])
        except TsconfigUnread as unread:
            self.unread[path] = str(unread)
            settings = {}
        inherited = Aliases()
        for base in _extended(path, settings.get("extends"), self._sources):
            found = self._base(base, depth + 1)
            if found is not None:
                inherited = found.over(inherited)
        self._open.discard(path)
        own = _own_aliases(path, settings)
        self._done[path] = inherited if own is None else own.over(inherited)
        return self._done[path]

    def _base(self, base: str, depth: int) -> Aliases | None:
        """An extended configuration's aliases: walked once, then
        remembered; None for a cycle back into the chain, or past a bound."""
        if base in self._done:
            return self._done[base]
        if base in self._open or base in self.unread:
            return None
        if depth > MAX_EXTENDS_DEPTH:
            self.unread[base] = EXTENDS_TOO_DEEP
            return None
        if len(self._done) + len(self._open) >= MAX_TSCONFIGS:
            self.unread[base] = TOO_MANY_TSCONFIGS
            return None
        return self.aliases(base, depth)


def _alias_targets(targets: object, base: str) -> list[str]:
    """Each target of one alias, written relative to the base directory,
    that stays inside the repository."""
    if not isinstance(targets, list):
        return []
    return [
        posixpath.relpath(inside, base)
        for target in targets
        if (inside := _inside(base, target)) is not None
    ]


def aliases_config(
    sources: Mapping[str, str],
    *,
    deadline: Deadline | None = None,
    clock: Callable[[], float] = time.time,
) -> tuple[str | None, list[Unparsed]] | TimedOut:
    """The tsconfig the cruiser is given: only the root tsconfig.json's path
    aliases and baseUrl, each pointing inside the copy, never a setting
    that reaches outside it; None when there are none. Paths with no
    baseUrl are read from their configuration's directory, which is then
    the baseUrl too: the cruiser applies no paths without one. With it,
    each configuration not read or not followed, and why; TimedOut when the
    deadline passes in the walk."""
    if TSCONFIG not in sources:
        return None, []
    walk = TsconfigWalk(sources, deadline=deadline, clock=clock)
    try:
        found = walk.aliases(TSCONFIG)
    except WalkTimedOut as passed:
        return TimedOut(str(passed))
    cut = [Unparsed(path=path, reason=reason) for path, reason in walk.unread.items()]
    if found.base_url is None and found.paths is None:
        return None, cut
    base = found.paths_from if found.base_url is None else found.base_url
    options: dict[str, object] = {"baseUrl": posixpath.join(TREE, base)}
    if found.paths is not None:
        options["paths"] = {
            str(alias): _alias_targets(targets, base)
            for alias, targets in found.paths.items()
        }
    return json.dumps({"compilerOptions": options}), cut


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
    aliases: str | None,
    deadline: Deadline | None,
    clock: Callable[[], float],
) -> Resolved:
    """Where each import of the sources resolves, by dependency-cruiser,
    with the path aliases given as its only TypeScript configuration."""
    timeout = None if deadline is None else deadline.epoch_seconds - clock()
    if timeout is not None and timeout <= 0:
        raise CruiseFailed("resolve the imports", timed_out=True)
    with tempfile.TemporaryDirectory(prefix="adhere-depcruise-") as scratch:
        tree = Path(scratch, TREE)
        write_tree(tree, sources)
        configured: list[str] = []
        if aliases is not None:
            Path(scratch, ALIASES).write_text(aliases)
            configured = ["--ts-config", str(Path(scratch, ALIASES))]
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
                    *configured,
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
    aliases: str | None,
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
                _cruise(
                    left,
                    cruiser=cruiser,
                    aliases=aliases,
                    deadline=deadline,
                    clock=clock,
                ),
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
        texts = {p: data.decode("utf-8") for p, data in readable.items()}
        readable = {p: data for p, data in readable.items() if is_code(p)}
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
        configured = (
            aliases_config(texts, deadline=deadline, clock=self._clock)
            if edges
            else (None, [])
        )
        if isinstance(configured, TimedOut):
            return configured
        aliases, cut = configured
        unparsed.extend(cut)
        try:
            if edges:
                resolved, unread = _cruise_around(
                    parsed,
                    cruiser=self._cruiser,
                    aliases=aliases,
                    deadline=deadline,
                    clock=self._clock,
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
