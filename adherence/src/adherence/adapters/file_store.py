"""adapters/file_store.py -- ReportStore over a local file cache.

The laptop's, the hook's and the cloud's store, and the file cache behind
the warehouse in CI (ARCHITECTURE.ARCH-ADHERENCE.md, Module map and
Persistence). Every report put is written for the scan, under
`scan/<repository>/`, stamped with the time it was kept; a report of a
revision named by its object id is also written under the lookup key
`by-rev/<repository>/<revision>/<identity>.json` that `get` reads. The
cache is a per-user data directory, never under the checkout: a directory
inside the repository it measures is refused. A key part that could
leave its directory is refused too. The adapter compares the Deadline to
its own clock and answers TimedOut rather than overrun it.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from collections.abc import Callable, Mapping
from pathlib import Path

from adherence.domain.coverage import Coverage
from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.finding import Evidence, Finding, Notice, Provenance
from adherence.domain.model import Layer, Unit, UnitKind
from adherence.domain.qualities import CheckKind, catalog_check, check_named
from adherence.domain.report import (
    BodyDigest,
    Recorded,
    Report,
    ReportIdentity,
    Verdict,
)
from adherence.domain.target import is_object_id
from adherence.ports.report_store import StoreMiss

# --- Constants ---------------------------------------------------------------

APP = "adherence"
FORMAT = 1
# A repository's name as a key part: one path segment, never `.` or `..`.
KEY_PART = re.compile(r"[A-Za-z0-9_.-]+")
INSIDE_REFUSAL = "the report cache lies inside the repository it measures"

JSON = dict[str, object]

# --- Predicates --------------------------------------------------------------


def is_key_part(text: str | None) -> bool:
    """Whether text can name one directory of the cache and nothing else."""
    return (
        text is not None
        and KEY_PART.fullmatch(text) is not None
        and text not in {".", ".."}
    )


# --- Pure helpers ------------------------------------------------------------


def default_store_dir(environ: Mapping[str, str], home: Path) -> Path:
    """The per-user cache directory: $XDG_CACHE_HOME/adherence when that is
    an absolute path, else ~/.cache/adherence."""
    cache = environ.get("XDG_CACHE_HOME", "")
    base = Path(cache) if cache and Path(cache).is_absolute() else home / ".cache"
    return base / APP


def _optional(value: Layer | Provenance | None) -> str | None:
    return value.value if value is not None else None


def _unit_data(unit: Unit) -> JSON:
    return {
        "path": unit.path,
        "kind": unit.kind.value,
        "symbol": unit.symbol,
        "start": unit.start,
        "end": unit.end,
        "layer": _optional(unit.layer),
    }


def _finding_data(finding: Finding) -> JSON:
    return {
        "check": finding.check.name,
        "unit": _unit_data(finding.unit),
        "layer": _optional(finding.layer),
        "subject": finding.subject,
        "evidence": {
            "path": finding.evidence.path,
            "line": finding.evidence.line,
            "text": finding.evidence.text,
        },
        "reached": _optional(finding.reached),
        "kind": finding.kind.value,
        "provenance": _optional(finding.provenance),
    }


def _identity_data(identity: ReportIdentity | None) -> JSON | None:
    if identity is None:
        return None
    return {
        "suite": identity.suite,
        "parameters": identity.parameters,
        "declaration": identity.declaration,
        "analyzers": list(identity.analyzers),
        "judge": identity.judge,
    }


def report_data(report: Report) -> JSON:
    """The report as plain data, every field kept."""
    return {
        "format": FORMAT,
        "ran": [c.name for c in report.ran],
        "findings": [_finding_data(f) for f in report.findings],
        "notices": [n.message for n in report.notices],
        "coverage": [
            {"reason": c.reason, "check": c.check, "path": c.path}
            for c in report.coverage
        ],
        "not_run": report.not_run_reason,
        "units": [_unit_data(u) for u in report.units],
        "verdict": report.verdict.value if report.verdict is not None else None,
        "reasons": list(report.reasons),
        "removed": [_finding_data(f) for f in report.removed],
        "bodies": [
            {"path": b.path, "symbol": b.symbol, "digest": b.digest}
            for b in report.bodies
        ],
        "identity": _identity_data(report.identity),
        "repository": report.repository,
        "revision": report.revision,
    }


class _Malformed(Exception):
    """A kept document that is not a report this suite wrote."""


def _text(data: Mapping[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise _Malformed(f"{key} is not text")
    return value


def _maybe_text(data: Mapping[str, object], key: str) -> str | None:
    value = data.get(key)
    if value is not None and not isinstance(value, str):
        raise _Malformed(f"{key} is not text")
    return value


def _number(data: Mapping[str, object], key: str) -> int:
    value = data.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise _Malformed(f"{key} is not a number")
    return value


def _table(value: object) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise _Malformed("an entry is not a table")
    return value


def _list(data: Mapping[str, object], key: str) -> list[object]:
    value = data.get(key)
    if not isinstance(value, list):
        raise _Malformed(f"{key} is not a list")
    return value


def _layer(value: str | None) -> Layer | None:
    return Layer(value) if value is not None else None


def _unit(value: object) -> Unit:
    data = _table(value)
    return Unit(
        path=_text(data, "path"),
        kind=UnitKind(_text(data, "kind")),
        symbol=_maybe_text(data, "symbol"),
        start=_number(data, "start"),
        end=_number(data, "end"),
        layer=_layer(_maybe_text(data, "layer")),
    )


def _finding(value: object) -> Finding:
    data = _table(value)
    evidence = _table(data.get("evidence"))
    check = check_named(_text(data, "check"))
    if check is None:
        raise _Malformed("a finding names no check of this suite")
    provenance = _maybe_text(data, "provenance")
    return Finding(
        check=check,
        unit=_unit(data.get("unit")),
        layer=_layer(_maybe_text(data, "layer")),
        subject=_text(data, "subject"),
        evidence=Evidence(
            _text(evidence, "path"), _number(evidence, "line"), _text(evidence, "text")
        ),
        reached=_layer(_maybe_text(data, "reached")),
        kind=CheckKind(_text(data, "kind")),
        provenance=Provenance(provenance) if provenance is not None else None,
    )


def _identity(value: object) -> ReportIdentity | None:
    if value is None:
        return None
    data = _table(value)
    analyzers = _list(data, "analyzers")
    if not all(isinstance(a, str) for a in analyzers):
        raise _Malformed("analyzers is not a list of text")
    return ReportIdentity(
        suite=_text(data, "suite"),
        parameters=_text(data, "parameters"),
        declaration=_text(data, "declaration"),
        analyzers=tuple(str(a) for a in analyzers),
        judge=_text(data, "judge"),
    )


def _coverage(value: object) -> Coverage:
    data = _table(value)
    return Coverage(
        _text(data, "reason"), _maybe_text(data, "check"), _maybe_text(data, "path")
    )


def _body(value: object) -> BodyDigest:
    data = _table(value)
    return BodyDigest(_text(data, "path"), _text(data, "symbol"), _text(data, "digest"))


def report_from_data(data: Mapping[str, object]) -> Report:
    """The report a document holds; _Malformed when it holds none."""
    if data.get("format") != FORMAT:
        raise _Malformed("not a report in this suite's format")
    verdict = _maybe_text(data, "verdict")
    names = _list(data, "ran")
    if not all(isinstance(n, str) and check_named(n) for n in names):
        raise _Malformed("ran names a check that is not this suite's")
    notices = _list(data, "notices")
    reasons = _list(data, "reasons")
    if not all(isinstance(t, str) for t in (*notices, *reasons)):
        raise _Malformed("a notice or reason is not text")
    return Report(
        ran=tuple(catalog_check(str(n)) for n in names),
        findings=tuple(_finding(f) for f in _list(data, "findings")),
        notices=tuple(Notice(str(n)) for n in notices),
        coverage=tuple(_coverage(c) for c in _list(data, "coverage")),
        not_run_reason=_maybe_text(data, "not_run"),
        units=tuple(_unit(u) for u in _list(data, "units")),
        verdict=Verdict(verdict) if verdict is not None else None,
        reasons=tuple(str(r) for r in reasons),
        removed=tuple(_finding(f) for f in _list(data, "removed")),
        bodies=tuple(_body(b) for b in _list(data, "bodies")),
        identity=_identity(data.get("identity")),
        repository=_maybe_text(data, "repository"),
        revision=_maybe_text(data, "revision"),
    )


# --- Adapter -----------------------------------------------------------------


class FileReportStore:
    """ReportStore over the cache directory `directory`, refusing to keep
    anything when that directory lies inside the repository at `root`."""

    def __init__(
        self,
        directory: Path,
        *,
        root: Path,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._directory = directory.resolve()
        self._inside = self._directory.is_relative_to(root.resolve())
        self._clock = clock

    def _lookup(self, repository: str, revision: str, identity: str) -> Path:
        return self._directory / "by-rev" / repository / revision / f"{identity}.json"

    def get(
        self, repository: str, revision: str, identity: str, deadline: Deadline | None
    ) -> Report | StoreMiss | TimedOut:
        if deadline is not None and deadline.epoch_seconds <= self._clock():
            return TimedOut("read a kept report")
        if self._inside:
            return StoreMiss(INSIDE_REFUSAL)
        if not (
            is_key_part(repository) and is_object_id(revision) and is_key_part(identity)
        ):
            return StoreMiss(f"no report is kept for {repository} at {revision}")
        path = self._lookup(repository, revision, identity)
        try:
            return report_from_data(_table(json.loads(path.read_bytes())))
        except FileNotFoundError:
            return StoreMiss(f"no report kept at {path}")
        except (OSError, ValueError, _Malformed) as error:
            return StoreMiss(f"{path} cannot be read: {error}")

    def _write(self, path: Path, document: JSON) -> None:
        """Write the document whole or not at all."""
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=path.parent, suffix=".part")
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            json.dump(document, out, indent=1)
        os.replace(temporary, path)

    def put(self, report: Report) -> Recorded:
        if self._inside:
            return Recorded(False, Notice(f"report not kept: {INSIDE_REFUSAL}"))
        if report.identity is None or not is_key_part(report.repository):
            return Recorded(
                False,
                Notice("report not kept: it names no repository or identity to key"),
            )
        repository = str(report.repository)
        identity = report.identity.digest
        kept_at = self._clock()
        document = {**report_data(report), "kept_at": kept_at}
        scan = (
            self._directory
            / "scan"
            / repository
            / f"{int(kept_at * 1000)}-{identity}.json"
        )
        try:
            self._write(scan, document)
            if report.revision is not None and is_object_id(report.revision):
                self._write(
                    self._lookup(repository, report.revision, identity), document
                )
        except OSError as error:
            return Recorded(False, Notice(f"report not kept: {error}"))
        return Recorded(True)
