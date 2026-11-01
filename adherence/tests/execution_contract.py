"""Design row "Repository code is never run" as one contract over every
adapter that spawns a process (ARCHITECTURE.ARCH-ADHERENCE.md, Security
mitigations): the code under measurement is bytes in, never run.

A subclass plants a repository whose every file would leave a mark if it
were executed -- a package `__init__`, a `conftest.py`, a `setup.py`, a
`sitecustomize.py`, a script, a module a test runner or an import would
load -- and runs its adapter over it, with a secret in the engine's own
environment. Every process the adapter spawns is watched at
`subprocess.run`, the standard library's door, and the contract holds
that:

- nothing the repository holds ran: the mark is never made;
- each process got the allowlisted environment -- PATH, LANG, and HOME and
  TMPDIR set to a scratch directory -- plus only the client's own named
  configuration, and never the engine's secret;
- no line of repository code reached a command line: code travels as
  files written outside the repository, or on standard input;
- each process ran outside the repository's working directory.

A subclass supplies `run` (and `prepare` when the repository must be more
than files on disk, and `own_configuration` for a client's own variables).
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import pytest

# The variables every spawned process may receive.
ALLOWLIST = frozenset({"PATH", "LANG", "HOME", "TMPDIR"})
# A secret in the engine's environment that no spawned process may see, under
# the names the ci job holds its tokens by: the judge's and the job's own.
SECRET = "adherence-contract-secret-value"
SECRET_NAMES = ("DECIDE_GATEWAY_TOKEN", "GITHUB_TOKEN", "ADHERENCE_CONTRACT_SECRET")
# A mark on every line of repository code planted, to find it on a command line.
MARK = "ADHERENCE-CONTRACT-MARK"


def planted(sentinel: Path) -> dict[str, bytes]:
    """A repository whose files each make `sentinel` exist if executed."""
    python = f"# {MARK}\nopen({str(sentinel)!r}, 'w').write('ran')\n"
    return {
        "src/pkg/__init__.py": python.encode(),
        "src/pkg/rules.py": (
            python
            + "def price(order):\n    if order:\n        return 1\n    return 2\n"
        ).encode(),
        "src/sitecustomize.py": python.encode(),
        "src/usercustomize.py": python.encode(),
        "conftest.py": python.encode(),
        "setup.py": python.encode(),
        "src/pkg/web.js": (
            f"// {MARK}\nrequire('fs').writeFileSync({json.dumps(str(sentinel))}, "
            "'ran');\nfunction f(x) { return x; }\n"
        ).encode(),
        "src/pkg/run.sh": f"# {MARK}\ntouch {sentinel}\n".encode(),
    }


@dataclass(frozen=True)
class Spawn:
    """One process an adapter started, as `subprocess.run` was asked."""

    argv: tuple[str, ...]
    env: Mapping[str, str]
    cwd: Path


@dataclass
class Spy:
    """Stands in for `subprocess.run`: keeps what each call was asked, then
    makes the call."""

    real: object
    spawns: list[Spawn] = field(default_factory=list)

    def __call__(self, args: object, *rest: object, **options: object) -> object:
        argv = tuple(str(a) for a in args) if isinstance(args, list | tuple) else ()
        env = options.get("env")
        cwd = options.get("cwd")
        self.spawns.append(
            Spawn(
                argv,
                dict(env) if isinstance(env, Mapping) else dict(os.environ),
                Path(str(cwd) if cwd is not None else os.getcwd()).resolve(),
            )
        )
        return self.real(args, *rest, **options)  # type: ignore[operator]


@dataclass(frozen=True)
class Ran:
    """What one run of the adapter over the planted repository left."""

    spawns: list[Spawn]
    sentinel: Path
    root: Path


class ExecutionContract:
    def own_configuration(self) -> frozenset[str]:
        """The client's own variables beside the allowlist; an analyzer has none."""
        return frozenset()

    def prepare(self, root: Path, files: Mapping[str, bytes]) -> None:
        """Make the repository at root: by default, the files on disk."""
        for path, data in files.items():
            (root / path).parent.mkdir(parents=True, exist_ok=True)
            (root / path).write_bytes(data)

    def run(self, root: Path, files: Mapping[str, bytes]) -> None:
        raise NotImplementedError("a contract subclass runs its adapter")

    @pytest.fixture
    def ran(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Ran:
        sentinel = tmp_path / "ran"
        root = tmp_path / "repository"
        root.mkdir()
        files = planted(sentinel)
        self.prepare(root, files)
        for name in SECRET_NAMES:
            monkeypatch.setenv(name, SECRET)
        spy = Spy(subprocess.run)
        monkeypatch.setattr(subprocess, "run", spy)
        self.run(root, files)
        return Ran(spy.spawns, sentinel, root.resolve())

    def test_run_over_planted_code_never_runs_it(self, ran: Ran) -> None:
        """Given a repository whose every file would leave a mark if run,
        When the adapter runs over it, Then it spawned its process and the
        mark was never made."""
        assert ran.spawns, "the adapter spawned nothing; the contract saw nothing"
        assert not ran.sentinel.exists(), "repository code was executed"

    def test_run_spawns_with_the_allowlisted_environment_only(self, ran: Ran) -> None:
        """Given a secret in the engine's environment, When the adapter runs,
        Then each process got only the allowlist and the client's own named
        configuration, its HOME and TMPDIR outside the repository and the
        user's home, and never the secret."""
        allowed = ALLOWLIST | self.own_configuration()
        for spawn in ran.spawns:
            assert set(spawn.env) <= allowed, spawn.env.keys() - allowed
            assert SECRET not in spawn.env.values()
            for name in ("HOME", "TMPDIR"):
                if name in spawn.env:
                    home = Path(spawn.env[name]).resolve()
                    assert not home.is_relative_to(ran.root), (name, home)
                    assert str(home) != os.path.expanduser("~"), (name, home)

    def test_run_puts_no_repository_code_on_a_command_line(self, ran: Ran) -> None:
        """Given repository code carrying a mark, When the adapter runs, Then
        no command line carries it: code reaches a process as files outside
        the repository or on standard input."""
        for spawn in ran.spawns:
            assert not any(MARK in arg for arg in spawn.argv), spawn.argv

    def test_run_spawns_outside_the_repository(self, ran: Ran) -> None:
        """Given the repository's working directory, When the adapter runs,
        Then no process runs in it or below it."""
        for spawn in ran.spawns:
            assert not spawn.cwd.is_relative_to(ran.root), spawn.cwd
