"""The shell CodeModelPort adapter over the fixture tree, one member at a
time (task-070), after the shared contract."""

from __future__ import annotations

import functools
from collections.abc import Mapping
from pathlib import Path

from adherence.adapters.shell_astgrep import ShellCodeModel
from adherence.domain.declaration import Declaration, parse_declaration
from adherence.domain.model import Body, CodeModel, ImportEdge, Layer, UnitKind
from adherence.ports.code_model import CodeModelPort
from tests import shell_fixture
from tests.code_model_contract import SHELL_SOURCES, CodeModelContract

TOOL = "bin/tool"


class TestShellCodeModel(CodeModelContract):
    sources: Mapping[str, bytes] = SHELL_SOURCES

    def port(self) -> CodeModelPort:
        return ShellCodeModel()


# One model of the fixture for the whole module: building it spawns the
# analyzer, and the CodeModel is frozen, so sharing it cannot leak state
# between tests.
@functools.cache
def fixture_model() -> CodeModel:
    model = ShellCodeModel().model(
        shell_fixture.sources(),
        shell_fixture.declaration(),
        shell_fixture.VOCABULARY,
        None,
    )
    assert isinstance(model, CodeModel), model
    return model


def test_functions_are_units_in_the_layer_of_their_marker_region() -> None:
    """Given a one-file tool whose `# --- Section ---` markers the
    declaration names, When it is modelled, Then its marker regions are in
    the model and each function is a unit in the layer of its region, one
    before the first marker in none."""
    model = fixture_model()
    units = {
        (u.path, u.symbol): (u.kind, u.layer)
        for u in model.units
        if u.kind is not UnitKind.FILE
    }

    assert [(r.path, r.layer) for r in model.regions] == [
        (TOOL, Layer.ADAPTERS),
        (TOOL, Layer.APPLICATION),
        (TOOL, Layer.COMPOSITION_ROOT),
    ]
    function = UnitKind.FUNCTION
    assert units[(TOOL, "die")] == (function, None)
    assert units[(TOOL, "head_of")] == (function, Layer.ADAPTERS)
    assert units[(TOOL, "pending")] == (function, Layer.ADAPTERS)
    assert units[(TOOL, "advance")] == (function, Layer.APPLICATION)
    assert units[(TOOL, "main")] == (function, Layer.COMPOSITION_ROOT)
    assert units[("lib/common.sh", "log_line")] == (function, Layer.ADAPTERS)


def test_every_command_is_a_call_with_its_function() -> None:
    """Given the fixture, When it is modelled, Then every command run is a
    call to its name as written, in a pipeline or a substitution alike,
    with the function it sits in, or none at the top."""
    calls = {(c.within, c.callee, c.line) for c in fixture_model().calls}

    assert {
        ("head_of", "git", 17),
        ("check_clean", "git", 32),
        ("check_clean", "head", 32),
        ("check_clean", "die", 33),
        ("advance", "check_clean", 37),
        ("advance", "command", 40),
        ("advance", "head_of", 40),
        (None, "source", 9),
        (None, "main", 57),
    } <= calls


def test_bodies_are_their_text_with_stub_and_sleep() -> None:
    """Given functions that do work, wait, and are nothing but a no-op,
    When the fixture is modelled, Then each body is its text inside the
    braces, the no-op the Vocabulary counts is its stub marker, and a
    sleep's line is where it waits."""
    bodies = {
        d.unit.symbol: d.body
        for d in fixture_model().definitions
        if d.unit.path == TOOL
    }

    assert bodies["head_of"] == Body('    git -C "$1" rev-parse HEAD', (), ())
    assert bodies["wait_for_lock"] == Body("    sleep 1", (), (22,))
    assert bodies["pending"] == Body(":;", (":",), ())
    assert bodies["die"] == Body('echo "tool: $*" >&2; exit 1;', (), ())


def test_dependencies_are_the_commands_each_file_requires() -> None:
    """Given scripts that run tools, builtins and their own functions, When
    the fixture is modelled, Then each file's dependencies are the tools it
    runs, each once at its first use with its line's text, through
    `command` too; never a builtin, nor a function a source defines."""
    commands = {
        (e.path, e.imported, e.line, e.text)
        for e in fixture_model().imports
        if e.imported_path is None
    }

    assert commands == {
        (
            TOOL,
            "dirname",
            9,
            'source "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"',
        ),
        (TOOL, "git", 17, 'git -C "$1" rev-parse HEAD'),
        (TOOL, "sleep", 22, "sleep 1"),
        (TOOL, "head", 32, 'dirt="$(git -C "$1" status --porcelain | head -n 1)"'),
        (TOOL, "jq", 40, """command jq -n --arg h "$(head_of "$1")" '$h'"""),
        (
            "lib/common.sh",
            "tee",
            4,
            """printf '%s\\n' "$*" | tee -a "${LOG_FILE:-/dev/null}\"""",
        ),
    }


def test_a_sourced_file_is_an_edge_to_it_when_it_is_a_source() -> None:
    """Given scripts that source files by a relative path, by a path from
    the root, through an expansion, and from outside the repository, When
    they are modelled, Then each file sourced that is a source is an edge to
    it, the path as written, and one outside is no edge at all."""
    script = (
        b"#!/bin/bash\n"
        b". ./helpers.sh\n"
        b'source "$HOME/.profile"\n'
        b"source lib/x.sh\n"
        b'source "$(dirname "$0")/../lib/y.sh"\n'
    )
    model = ShellCodeModel().model(
        {"bin/a": script, "bin/helpers.sh": b"", "lib/x.sh": b"", "lib/y.sh": b""},
        shell_fixture.declaration(),
        shell_fixture.VOCABULARY,
        None,
    )

    assert isinstance(model, CodeModel)
    sourced = {e for e in model.imports if e.imported != "dirname"}
    assert sourced == {
        ImportEdge("bin/a", "./helpers.sh", 2, ". ./helpers.sh", "bin/helpers.sh"),
        ImportEdge("bin/a", "lib/x.sh", 4, "source lib/x.sh", "lib/x.sh"),
        ImportEdge(
            "bin/a",
            '$(dirname "$0")/../lib/y.sh',
            5,
            'source "$(dirname "$0")/../lib/y.sh"',
            "lib/y.sh",
        ),
    }


def test_a_file_the_grammar_cannot_read_is_unparsed_with_the_reason() -> None:
    """Given a zsh nested expansion the Bash grammar cannot parse, bytes
    that are not UTF-8, and a path leaving the repository, When they are
    modelled, Then each is unparsed with its reason and no unit, and a
    readable file beside them is still modelled."""
    model = ShellCodeModel().model(
        {
            "bin/nested": b'#!/bin/zsh\nok() { :; }\nx="${${HOME}}/log"\n',
            "bin/latin1": b"#!/bin/sh\necho caf\xe9\n",
            "../outside.sh": b"echo hi\n",
            "bin/fine": b"#!/bin/sh\necho fine\n",
        },
        shell_fixture.declaration(),
        shell_fixture.VOCABULARY,
        None,
    )

    assert isinstance(model, CodeModel)
    reasons = {u.path: u.reason for u in model.unparsed}
    assert reasons["bin/nested"] == "not shell: syntax error at line 3"
    assert reasons["bin/latin1"].startswith("not utf-8")
    assert reasons["../outside.sh"] == "the path leaves the repository; not read"
    assert {u.path for u in model.units} == {"bin/fine"}


def test_the_repository_s_own_bin_is_modelled() -> None:
    """Given every shell tool under this repository's bin/, by extension or
    shebang, and a declaration naming bin/tds-release's markers, When they
    are modelled, Then each tool is a file unit or unparsed with a reason,
    and tds-release's functions sit in the layers its markers open, with
    git among the tools it requires."""
    bin_dir = Path(__file__).resolve().parents[3] / "bin"
    sources = {
        f"bin/{path}": data
        for path, data in shell_fixture.sources_under(bin_dir).items()
    }
    declaration = parse_declaration(
        b'[layers]\nregions = [{ file = "bin/tds-release" }]\n'
    )
    assert isinstance(declaration, Declaration)

    model = ShellCodeModel().model(sources, declaration, shell_fixture.VOCABULARY, None)

    assert isinstance(model, CodeModel), model
    files = {u.path for u in model.units if u.kind is UnitKind.FILE}
    unparsed = {u.path for u in model.unparsed if u.reason}
    assert "bin/tds-release" in files
    assert files | unparsed == set(sources)
    release = "bin/tds-release"
    layers = {u.symbol: u.layer for u in model.units if u.path == release}
    assert layers["repo_root"] is Layer.ADAPTERS
    assert layers["check_worktree_clean"] is Layer.APPLICATION
    assert layers["main"] is Layer.COMPOSITION_ROOT
    assert "git" in {e.imported for e in model.imports if e.path == release}


def modelled(sources: Mapping[str, bytes]) -> CodeModel:
    """The fixture declaration's model of the sources given."""
    model = ShellCodeModel().model(
        sources, shell_fixture.declaration(), shell_fixture.VOCABULARY, None
    )
    assert isinstance(model, CodeModel), model
    return model


def test_a_sourced_path_s_literal_tail_follows_its_last_expansion() -> None:
    """Given paths built by an unbraced variable, a braced one, a command
    substitution and backticks, and paths that are nothing but an
    expansion, When they are modelled, Then each is an edge to the source
    its literal tail names, the variable's name never part of it, and one
    with no literal part after its last expansion is no edge at all."""
    script = (
        b"#!/bin/bash\n"
        b'source "$DIR/lib/c.sh"\n'
        b'source "${DIR}/lib/c.sh"\n'
        b'source "$(dirname "$0")/lib/c.sh"\n'
        b'source "`dirname $0`/lib/c.sh"\n'
        b'source "$o"\n'
        b"source ${o}\n"
        b'source "$DIR/lib/$name"\n'
    )
    model = modelled({"bin/a": script, "lib/c.sh": b"f() { echo hi; }\n", "bin/o": b""})

    sourced = {(e.line, e.imported_path) for e in model.imports if e.imported_path}
    assert sourced == {
        (2, "lib/c.sh"),
        (3, "lib/c.sh"),
        (4, "lib/c.sh"),
        (5, "lib/c.sh"),
    }
