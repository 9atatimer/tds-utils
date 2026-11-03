"""The shell code model over this repository's own scripts, and `adhere
measure` over the shell fixture (task-070's done condition). Nothing is
copied into the fixtures for the first, so the model is checked against
the real tree as it stands.

bin/ itself has no script the suite can read yet: its two `.sh` files are
symbolic links, which the git adapter refuses, and the rest carry no
extension, so no analyzer is registered for them (Issue#638). The scripts
here are the links' targets and the repository's own smoke tests."""

from __future__ import annotations

import functools
import json
import re
from pathlib import Path

from click.testing import CliRunner

from adherence.adapters.fakes import FakeComplexity, FakeDuplication, FakeRecords
from adherence.adapters.shell_astgrep import ShellCodeModel
from adherence.cli.main import main
from adherence.container import SHIPPED_VOCABULARY, build
from adherence.domain.declaration import Declaration, parse_declaration
from adherence.domain.model import CodeModel, UnitKind
from tests import shell_fixture

REPOSITORY = Path(__file__).resolve().parents[3]
DECLARATION = b'[layers]\nadapters = ["log-hoarder/**"]\ntest = ["test/**"]\n'
DEFINED = re.compile(r"^\s*(?:function\s+([\w-]+)|([\w-]+)\s*\(\s*\))", re.MULTILINE)
BASH = re.compile(rb"\A#!\s*(?:/usr/bin/env\s+bash|/bin/bash)\b")
HEREDOC = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?")
ANATOMY_SUBJECT = (
    "the adapters region at line 12 follows the composition root region at line 7"
)


def outside_heredocs(text: str) -> str:
    """The script's lines but those inside a here-document, whose text is
    data the script writes, not code it defines."""
    kept: list[str] = []
    ending: str | None = None
    for line in text.splitlines():
        if ending is not None:
            if line.strip() == ending:
                ending = None
            continue
        kept.append(line)
        opened = HEREDOC.search(line)
        if opened:
            ending = opened.group(1)
    return "\n".join(kept)


def _sources() -> dict[str, bytes]:
    paths = sorted(REPOSITORY.glob("log-hoarder/*.sh")) + sorted(
        REPOSITORY.glob("test/*.sh")
    )
    return {
        p.relative_to(REPOSITORY).as_posix(): data
        for p in paths
        if not p.is_symlink() and BASH.match(data := p.read_bytes())
    }


def test_the_repositorys_bash_scripts_are_modelled_whole() -> None:
    """Given this repository's Bash smoke tests and log-hoarder scripts, When
    they are modelled, Then each is a file unit or Unparsed with a reason,
    never dropped, and every function a parsed file defines is a definition."""
    sources = _sources()
    declaration = parse_declaration(DECLARATION)
    assert isinstance(declaration, Declaration)

    model = ShellCodeModel().model(sources, declaration, SHIPPED_VOCABULARY, None)

    assert isinstance(model, CodeModel), model
    assert len(sources) >= 20, "test/ or log-hoarder/ moved"
    files = {u.path for u in model.units if u.kind is UnitKind.FILE}
    unparsed = {u.path for u in model.unparsed}
    assert files | unparsed == set(sources)
    assert not files & unparsed
    assert len(files) > len(unparsed)
    defined = {
        (d.unit.path, d.unit.symbol.rpartition(".")[2])
        for d in model.definitions
        if d.unit.symbol
    }
    checked = 0
    for path in files:
        for match in DEFINED.finditer(outside_heredocs(sources[path].decode())):
            name = match.group(1) or match.group(2)
            assert (path, name) in defined, (path, name)
            checked += 1
    assert checked >= 100, "too few functions found to check the model against"


def test_measure_over_the_shell_fixture_says_which_checks_do_not_read_it() -> None:
    """Given the shell fixture, one of whose scripts puts its entry point
    above its functions, When `adhere measure --json` runs over it, Then the
    run is not refused, no script is in a language no analyzer measures,
    Anatomy reads the scripts and finds the one out of order, Stub reads
    them and finds the `:` placeholder and the sleep, and every other check
    that ran reports each script as "does not read shell"."""
    builder = functools.partial(
        build,
        records=FakeRecords({}),
        complexity=FakeComplexity(),
        duplication=FakeDuplication(),
    )

    result = CliRunner().invoke(
        main, ["measure", "--root", str(shell_fixture.ROOT), "--json"], obj=builder
    )

    assert result.exit_code == 0, result.output
    document = json.loads(result.output)
    assert document["not_run"] is None
    reasons = {(c["check"], c["path"]): c["reason"] for c in document["coverage"]}
    assert not any("no analyzer" in r for r in reasons.values()), reasons
    ran = {name for q in document["qualities"] for name in q["ran"]}
    assert {"Grep", "Anatomy", "Stub"} <= ran
    found = {
        (f["check"], f["path"], f["symbol"], f["subject"])
        for q in document["qualities"]
        for f in q["findings"]
    }
    assert found == {
        ("Anatomy", "bin/backwards.sh", None, ANATOMY_SUBJECT),
        ("Stub", "bin/release.sh", "rollback", ":"),
        ("Stub", "bin/release.sh", "wait_for_lock", "sleep"),
    }
    scripts = ("bin/backwards.sh", "bin/release.sh", "lib/checks.sh")
    for check in ("Anatomy", "Stub"):
        for script in scripts:
            assert (check, script) not in reasons, reasons[(check, script)]
    for check in ran - {"Anatomy", "Stub"}:
        for script in scripts:
            assert reasons[(check, script)] == "does not read shell", (check, script)
