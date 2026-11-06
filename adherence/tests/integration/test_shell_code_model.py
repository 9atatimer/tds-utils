"""The shell CodeModelPort adapter over the fixture tree, one member at a
time (task-070), after the shared contract."""

from __future__ import annotations

import functools
import sys
from collections.abc import Mapping
from pathlib import Path

from adherence.adapters.shell_astgrep import ShellCodeModel
from adherence.domain.deadline import TimedOut
from adherence.domain.model import CodeModel, Definition, Layer, Region, UnitKind
from adherence.domain.parameters import Vocabulary
from adherence.ports.code_model import CodeModelPort
from tests import shell_fixture
from tests.code_model_contract import SHELL_SOURCES, CodeModelContract


class TestShellCodeModel(CodeModelContract):
    sources: Mapping[str, bytes] = SHELL_SOURCES

    def port(self) -> CodeModelPort:
        return ShellCodeModel()


# One model of the fixture for the whole module: building it spawns
# ast-grep, and the CodeModel is frozen, so sharing it cannot leak state
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


def _model_of(sources: dict[str, bytes]) -> CodeModel:
    model = ShellCodeModel().model(
        sources, shell_fixture.declaration(), shell_fixture.VOCABULARY, None
    )
    assert isinstance(model, CodeModel), model
    return model


def test_units_are_each_function_in_its_layer() -> None:
    """Given the fixture, When it is modelled, Then every function, in
    either declaration form, is a unit with its lines and the layer its file
    or region puts it in, and a nested function carries its parent."""
    units = {
        (u.path, u.symbol): (u.kind, u.start, u.end, u.layer)
        for u in fixture_model().units
        if u.kind is not UnitKind.FILE
    }

    release = "bin/release.sh"
    assert units[(release, "fetch_line")] == (UnitKind.FUNCTION, 8, 10, Layer.ADAPTERS)
    assert units[(release, "head_of")] == (UnitKind.FUNCTION, 12, 14, Layer.ADAPTERS)
    assert units[(release, "release_unit")] == (
        UnitKind.FUNCTION,
        21,
        29,
        Layer.APPLICATION,
    )
    assert units[(release, "main")] == (
        UnitKind.FUNCTION,
        37,
        39,
        Layer.COMPOSITION_ROOT,
    )
    assert units[("lib/checks.sh", "is_ancestor")][3] is Layer.DOMAIN
    assert units[("test/release_test.sh", "test_release_needs_a_unit")][3] is (
        Layer.TEST
    )
    assert not any(path == "notes/uncovered.sh" for path, _ in units)

    nested = _model_of({"m.sh": b"outer() {\n    inner() { :; }\n    inner\n}\n"})
    assert [(d.unit.symbol, d.parent, d.nested) for d in nested.definitions] == [
        ("outer", None, False),
        ("outer.inner", "outer", True),
    ]


def test_regions_found_by_marker_are_in_the_model() -> None:
    """Given a script whose `# --- Section ---` markers the declaration
    names, When it is modelled, Then each marker's region is in the model,
    from its marker to the line before the next, in the layer the
    vocabulary maps it to."""
    assert tuple(r for r in fixture_model().regions if r.path == "bin/release.sh") == (
        Region("bin/release.sh", 7, 19, Layer.ADAPTERS),
        Region("bin/release.sh", 20, 35, Layer.APPLICATION),
        Region("bin/release.sh", 36, 41, Layer.COMPOSITION_ROOT),
    )


def _definition(path: str, symbol: str) -> Definition:
    [found] = [
        d
        for d in fixture_model().definitions
        if (d.unit.path, d.unit.symbol) == (path, symbol)
    ]
    return found


def test_bodies_carry_their_text_and_stub_markers() -> None:
    """Given a function whose body is only the `:` placeholder beside a
    comment, one that runs `:` for its expansion before real work, and an
    ordinary one, When the fixture is modelled, Then each body carries its
    text, and only the first is the placeholder it consists of."""
    rollback = _definition("bin/release.sh", "rollback").body
    ancestor = _definition("lib/checks.sh", "is_ancestor").body
    fetch = _definition("bin/release.sh", "fetch_line").body

    assert rollback.stub_markers == (":",)
    assert ancestor.stub_markers == ()
    assert fetch.stub_markers == ()
    assert fetch.text == '    git fetch --quiet origin "$1"'
    assert "git merge-base --is-ancestor" in ancestor.text


def test_stubs_come_from_the_vocabulary() -> None:
    """Given a vocabulary that counts no placeholder as a stub, When a
    `:`-only body is modelled with it, Then the body carries no stub marker."""
    model = ShellCodeModel().model(
        {"m.sh": b"later() {\n    :\n}\n"},
        shell_fixture.declaration(),
        Vocabulary(regions={}),
        None,
    )

    assert isinstance(model, CodeModel)
    assert [d.body.stub_markers for d in model.definitions] == [()]


def test_calls_are_every_command_run_with_the_function_it_sits_in() -> None:
    """Given a script that runs commands at the top, in functions, in a
    command substitution, a negated condition, a redirection and a
    pipeline, When the fixture is modelled, Then each command is a call
    naming its callee as written, its line, and the function it sits in;
    a declaration such as `local` is none."""
    calls = {
        (c.within, c.callee, c.line)
        for c in fixture_model().calls
        if c.path == "bin/release.sh"
    }

    assert calls == {
        (None, "set", 5),
        ("fetch_line", "git", 9),
        ("head_of", "git", 13),
        ("wait_for_lock", "sleep", 17),
        ("release_unit", "head_of", 23),
        ("release_unit", "is_ancestor", 24),
        ("release_unit", "echo", 25),
        ("release_unit", "return", 26),
        ("release_unit", "fetch_line", 28),
        ("release_unit", "tee", 28),
        ("rollback", ":", 33),
        ("main", "release_unit", 38),
        (None, "main", 41),
    }


def test_bodies_carry_the_lines_they_sleep_on() -> None:
    """Given a function that runs `sleep`, and a one-line body that sleeps
    inside a list of commands, When they are modelled, Then each body
    carries the line it sleeps on and no other body does."""
    model = _model_of({"m.sh": b"nap() { sleep 1; jq -r . | sort; }\nf() {\n  g\n}\n"})

    assert _definition("bin/release.sh", "wait_for_lock").body.sleeps == (17,)
    assert _definition("bin/release.sh", "fetch_line").body.sleeps == ()
    assert {d.unit.symbol: d.body.sleeps for d in model.definitions} == {
        "nap": (1,),
        "f": (),
    }


def test_a_file_the_grammar_cannot_read_is_unparsed_and_the_rest_modelled() -> None:
    """Given a script with an unclosed function body, a zsh script using a
    nested expansion the Bash grammar has no rule for, one that is not
    UTF-8, and one that reads, When they are modelled, Then the first three
    are Unparsed with why, saying where the grammar stopped rather than that
    the file is not shell, none is a unit, and the fourth is modelled."""
    model = _model_of(
        {
            "bad.sh": b"f() { echo x\n",
            "nested.zsh": b'x=1\ny="${${x:-$HOME}}/z"\n',
            "latin.sh": b"echo \xff\n",
            "ok.sh": b"g() { :; }\n",
        }
    )

    assert [(u.path, u.reason) for u in model.unparsed if u.path != "latin.sh"] == [
        ("bad.sh", "the Bash grammar cannot read it from line 1"),
        ("nested.zsh", "the Bash grammar cannot read it from line 2"),
    ]
    assert [u.reason.split(":")[0] for u in model.unparsed if u.path == "latin.sh"] == [
        "not utf-8"
    ]
    assert {(u.path, u.symbol) for u in model.units} == {
        ("ok.sh", None),
        ("ok.sh", "g"),
    }


def test_a_function_defined_twice_keeps_each_body() -> None:
    """Given a script that defines a function once per branch of an `if`,
    a `:` placeholder in one and real work that sleeps in the other, When it
    is modelled, Then each definition carries its own body, stub marker and
    sleep lines, not the other's."""
    model = _model_of(
        {
            "m.sh": b'if [ "$(uname)" = Darwin ]; then\n'
            b"  open_it() { :; }\n"
            b"else\n"
            b'  open_it() { xdg-open "$1"; sleep 1; }\n'
            b"fi\n"
        }
    )

    assert [
        (d.unit.start, d.body.text, d.body.stub_markers, d.body.sleeps)
        for d in model.definitions
    ] == [
        (2, ":;", (":",), ()),
        (4, 'xdg-open "$1"; sleep 1;', (), (4,)),
    ]


def test_an_empty_here_document_does_not_make_a_script_unreadable() -> None:
    """Given scripts whose here-document body is empty, blank, or only a
    command substitution, all valid Bash, When they are modelled, Then each
    is a file unit with its function, and none is Unparsed."""
    sources = {
        "empty.sh": b"f() {\n  cat <<EOF\nEOF\n}\n",
        "blank.sh": b"f() {\n  cat <<'EOF'\n\nEOF\n}\n",
        "substituted.sh": b"f() {\n  cat <<T\n$(echo x)\nT\n}\n",
    }

    model = _model_of(sources)

    assert model.unparsed == ()
    assert {(d.unit.path, d.unit.symbol) for d in model.definitions} == {
        (path, "f") for path in sources
    }


def test_a_script_with_no_extension_is_read_as_its_sh_copy_is() -> None:
    """Given a script with no extension and the same script named `.sh`,
    When both are modelled, Then each has the same functions, calls and
    stub markers; and a broken script with no extension is Unparsed, never
    a bare, clean file."""
    text = (shell_fixture.ROOT / "bin" / "rollout").read_bytes()

    def facts(path: str) -> tuple[object, ...]:
        model = _model_of({path: text})
        return (
            sorted(u.symbol or "" for u in model.units),
            sorted(c.callee for c in model.calls),
            model.unparsed,
        )

    assert facts("bin/rollout") == facts("bin/rollout.sh")
    assert facts("bin/rollout")[0] == ["", "announce", "main"]
    broken = _model_of({"bin/broken": b"#!/bin/bash\nf() { echo x\n"})
    assert [u.path for u in broken.unparsed] == ["bin/broken"]


SLEEPER = Path(__file__).resolve().parents[1] / "sleeper_analyzer.py"


def sleeping_binary(directory: Path) -> Path:
    """An executable that stands in for ast-grep and never answers in time."""
    binary = directory / "ast-grep"
    binary.write_text(f"#!/bin/sh\nexec {sys.executable} -I {SLEEPER}\n")
    binary.chmod(0o755)
    return binary


def test_model_by_an_analyzer_past_its_bound_with_no_deadline_times_out(
    tmp_path: Path,
) -> None:
    """Given an ast-grep that sleeps far past the analyzer bound and no
    deadline (the laptop, CI), When the sources are modelled, Then it is
    ended at its bound and the answer is TimedOut."""
    port = ShellCodeModel(ast_grep=sleeping_binary(tmp_path), bound=0.5)

    model = port.model(
        shell_fixture.sources(),
        shell_fixture.declaration(),
        shell_fixture.VOCABULARY,
        None,
    )

    assert isinstance(model, TimedOut), model
