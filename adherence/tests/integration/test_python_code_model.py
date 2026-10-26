"""The Python CodeModelPort adapter over the fixture tree, one member at a
time (task-057), after the shared contract."""

from __future__ import annotations

import functools
from pathlib import Path

from adherence.adapters.python_ast import PythonCodeModel
from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.declaration import Declaration, parse_declaration
from adherence.domain.model import (
    AccessKind,
    Assertion,
    CodeModel,
    Definition,
    Layer,
    MemberKind,
    Parameter,
    ReferenceKind,
    Region,
    Signature,
    UnitKind,
)
from adherence.domain.parameters import Vocabulary
from adherence.ports.code_model import CodeModelPort
from tests import python_fixture
from tests.code_model_contract import CodeModelContract


class TestPythonCodeModel(CodeModelContract):
    def port(self) -> CodeModelPort:
        return PythonCodeModel()


# One model of the fixture for the whole module: building it spawns grimp's
# child interpreter, and the CodeModel is frozen, so sharing it cannot leak
# state between tests.
@functools.cache
def fixture_model() -> CodeModel:
    model = PythonCodeModel().model(
        python_fixture.sources(),
        python_fixture.declaration(),
        python_fixture.VOCABULARY,
        None,
    )
    assert isinstance(model, CodeModel), model
    return model


def test_units_are_each_definition_in_its_layer() -> None:
    """Given the fixture, When it is modelled, Then every function, method and
    class is a unit with its qualified symbol and the layer its file or its
    marker region puts it in."""
    units = {
        (u.path, u.symbol): (u.kind, u.layer)
        for u in fixture_model().units
        if u.kind is not UnitKind.FILE
    }

    assert units[("src/tool/domain/rules.py", "Order")] == (UnitKind.TYPE, Layer.DOMAIN)
    assert units[("src/tool/domain/rules.py", "Order.is_large")] == (
        UnitKind.FUNCTION,
        Layer.DOMAIN,
    )
    assert units[("src/tool/application/use.py", "close_order.helper")] == (
        UnitKind.FUNCTION,
        Layer.APPLICATION,
    )
    assert units[("src/tool/container.py", "build")] == (
        UnitKind.FUNCTION,
        Layer.COMPOSITION_ROOT,
    )
    assert units[("bin/onefile.py", "is_even")] == (UnitKind.FUNCTION, Layer.DOMAIN)
    assert units[("bin/onefile.py", "load")] == (UnitKind.FUNCTION, Layer.ADAPTERS)
    assert ("notes/uncovered.py", None) not in units


def test_regions_found_by_marker_are_in_the_model() -> None:
    """Given a marker file in the declaration, When it is modelled, Then its
    marker regions are part of the model."""
    regions = [(r.path, r.layer) for r in fixture_model().regions]

    assert regions == [
        ("bin/onefile.py", Layer.DOMAIN),
        ("bin/onefile.py", Layer.ADAPTERS),
    ]


def test_imports_are_resolved_with_their_line_and_target_file() -> None:
    """Given package, relative, plain-script and standard-library imports,
    When the fixture is modelled, Then each is an edge to the module it
    resolves to, with its line, and to its file when the file is a source."""
    edges = {
        (e.path, e.imported, e.line, e.imported_path)
        for e in fixture_model().imports
        if e.path
        in {
            "src/tool/application/use.py",
            "src/tool/container.py",
            "tests/test_use.py",
            "bin/onefile.py",
        }
    }

    assert edges == {
        ("src/tool/application/use.py", "time", 1, None),
        (
            "src/tool/application/use.py",
            "tool.domain.rules",
            3,
            "src/tool/domain/rules.py",
        ),
        (
            "src/tool/application/use.py",
            "tool.domain.rules",
            4,
            "src/tool/domain/rules.py",
        ),
        (
            "src/tool/application/use.py",
            "tool.ports.store",
            5,
            "src/tool/ports/store.py",
        ),
        (
            "src/tool/container.py",
            "tool.adapters.fs_store",
            1,
            "src/tool/adapters/fs_store.py",
        ),
        (
            "src/tool/container.py",
            "tool.application.use",
            3,
            "src/tool/application/use.py",
        ),
        ("tests/test_use.py", "tool.application.use", 1, "src/tool/application/use.py"),
        ("bin/onefile.py", "json", 3, None),
    }


def test_imports_resolve_against_the_sources_never_the_engine() -> None:
    """Given a measured package named like the engine's own, When it is
    modelled, Then its imports resolve inside the sources handed over."""
    sources = {
        "src/adherence/__init__.py": b"",
        "src/adherence/a.py": b"from adherence import b\n",
        "src/adherence/b.py": b"",
    }
    model = PythonCodeModel().model(
        sources, python_fixture.declaration(), python_fixture.VOCABULARY, None
    )

    assert isinstance(model, CodeModel)
    assert {(e.path, e.imported_path) for e in model.imports} == {
        ("src/adherence/a.py", "src/adherence/b.py")
    }


def _definition(path: str, symbol: str) -> Definition:
    [found] = [
        d
        for d in fixture_model().definitions
        if d.unit.path == path and d.unit.symbol == symbol
    ]
    return found


def test_definitions_carry_signature_bases_decorators_and_nesting() -> None:
    """Given functions, methods, a nested function, a dataclass and a Protocol,
    When the fixture is modelled, Then each definition carries its signature
    (parameters with annotation, keyword-only and default), its return
    annotation, its bases and decorators, and whether a function encloses it."""
    classify = _definition("src/tool/domain/rules.py", "classify")
    order = _definition("src/tool/domain/rules.py", "Order")
    store = _definition("src/tool/ports/store.py", "Store")
    helper = _definition("src/tool/application/use.py", "close_order.helper")
    method = _definition("src/tool/domain/rules.py", "Order.is_large")

    assert classify.signature == Signature(
        parameters=(
            Parameter("order", "Order", keyword_only=False, has_default=False),
            Parameter("strict", "bool", keyword_only=True, has_default=True),
        ),
        returns="str",
    )
    assert order.signature is None
    assert order.decorators == ("dataclass(frozen=True)",)
    assert store.bases == ("Protocol",)
    assert (helper.parent, helper.nested) == ("close_order", True)
    assert (method.parent, method.nested) == ("Order", False)


def test_bodies_carry_their_text_stub_markers_and_sleeps() -> None:
    """Given a body that is only `pass`, one that is only `...`, and one that
    sleeps, When the fixture is modelled, Then each body carries its text,
    the placeholder it consists of, and the lines it sleeps on."""
    unfinished = _definition("src/tool/domain/rules.py", "unfinished").body
    save = _definition("src/tool/ports/store.py", "Store.save").body
    close = _definition("src/tool/application/use.py", "close_order").body

    assert unfinished.stub_markers == ("pass",)
    assert save.stub_markers == ("...",)
    assert close.stub_markers == ()
    assert close.sleeps == (10,)
    assert "store.save(order)" in close.text


def test_references_are_names_and_string_literals_but_not_docstrings() -> None:
    """Given code naming a module attribute and quoting a model id, When the
    fixture is modelled, Then each name chain and string literal is a
    reference in the definition it sits in, and a docstring is none."""
    references = {
        (r.path, r.within, r.kind, r.text) for r in fixture_model().references
    }

    save = ("src/tool/adapters/fs_store.py", "FsStore.save")
    assert (*save, ReferenceKind.STRING, "claude-opus") in references
    assert (*save, ReferenceKind.NAME, "os.environ") in references
    assert (*save, ReferenceKind.NAME, "os") not in references
    assert (
        "src/tool/domain/rules.py",
        "Order.is_large",
        ReferenceKind.NAME,
        "LIMIT",
    ) in references
    assert not any(r[3] == "Rules." for r in references)


def test_calls_name_their_callee_and_the_definition_they_sit_in() -> None:
    """Given function, method and constructor calls, When the fixture is
    modelled, Then each call names its callee as written, its line, and the
    definition it sits in."""
    calls = {(c.path, c.within, c.callee, c.line) for c in fixture_model().calls}

    use = "src/tool/application/use.py"
    assert (use, "close_order", "time.sleep", 10) in calls
    assert (use, "close_order", "store.save", 11) in calls
    assert (use, "close_order", "classify", 16) in calls
    assert ("src/tool/container.py", "build", "FsStore", 7) in calls


def test_accesses_are_environment_reads_and_declared_globals() -> None:
    """Given a read of the environment and a function that declares a global,
    When the fixture is modelled, Then each is an access of its kind in the
    definition it sits in."""
    accesses = {(a.path, a.within, a.kind, a.target) for a in fixture_model().accesses}

    assert accesses == {
        (
            "src/tool/adapters/fs_store.py",
            "FsStore.save",
            AccessKind.ENVIRONMENT,
            "os.environ",
        ),
        ("bin/onefile.py", "load", AccessKind.GLOBAL, "COUNTER"),
    }


def test_writes_are_field_assignments_with_the_unit_that_makes_them() -> None:
    """Given a use case assigning a domain value's field and a constructor
    assigning its own, When the fixture is modelled, Then each is a write of
    that field, on that object, by the definition it sits in."""
    writes = {(w.path, w.within, w.target, w.field) for w in fixture_model().writes}

    assert writes == {
        ("src/tool/application/use.py", "close_order", "order", "status"),
        ("src/tool/adapters/fs_store.py", "FsStore.__init__", "self", "root"),
    }


def test_conditionals_name_their_discriminant() -> None:
    """Given a branch on a value's field, When the fixture is modelled, Then
    the conditional names the expression it discriminates on, its line and
    the definition it sits in."""
    conditionals = {
        (c.path, c.within, c.discriminant, c.line) for c in fixture_model().conditionals
    }

    assert conditionals == {
        ("src/tool/domain/rules.py", "classify", "order.status", 18)
    }


def test_conditionals_see_through_bool_ops_matches_and_isinstance() -> None:
    """Given branches joined by `and`, a `match`, and an isinstance test,
    When they are modelled, Then each names what it discriminates on."""
    source = (
        b"def f(x, y, kind):\n"
        b"    if x.a == 1 and not y:\n"
        b"        pass\n"
        b"    match kind:\n"
        b"        case 1:\n"
        b"            pass\n"
        b"    if isinstance(x, int):\n"
        b"        pass\n"
    )
    model = PythonCodeModel().model(
        {"m.py": source}, python_fixture.declaration(), python_fixture.VOCABULARY, None
    )

    assert isinstance(model, CodeModel)
    assert sorted((c.line, c.discriminant) for c in model.conditionals) == [
        (2, "x.a"),
        (2, "y"),
        (4, "kind"),
        (7, "x"),
    ]


def test_members_are_each_types_fields_and_methods() -> None:
    """Given a dataclass, a Protocol and a class that sets a field in its
    constructor, When the fixture is modelled, Then each type's fields
    (declared, or assigned on self) and methods are its members."""
    members = {(m.path, m.owner, m.name, m.kind) for m in fixture_model().members}

    rules, store, fs = (
        "src/tool/domain/rules.py",
        "src/tool/ports/store.py",
        "src/tool/adapters/fs_store.py",
    )
    assert members == {
        (rules, "Order", "total", MemberKind.FIELD),
        (rules, "Order", "status", MemberKind.FIELD),
        (rules, "Order", "is_large", MemberKind.METHOD),
        (store, "Store", "save", MemberKind.METHOD),
        (fs, "FsStore", "__init__", MemberKind.METHOD),
        (fs, "FsStore", "save", MemberKind.METHOD),
        (fs, "FsStore", "root", MemberKind.FIELD),
    }


def test_test_cases_carry_their_calls_and_assertions() -> None:
    """Given a test that asserts and a test that only calls, When the fixture
    is modelled, Then each test case carries what it calls and what it
    asserts, so a test that cannot fail is visible."""
    cases = {
        (t.path, t.symbol, t.calls, t.assertions) for t in fixture_model().test_cases
    }

    assert cases == {
        (
            "tests/test_use.py",
            "test_close_order_saves",
            (),
            (Assertion("close_order is not None"),),
        ),
        ("tests/test_use.py", "test_nothing", ("close_order",), ()),
    }


def test_test_cases_include_methods_of_test_classes() -> None:
    """Given a test method in a Test class and a helper outside it, When they
    are modelled, Then the method is a test case and the helper is not."""
    source = (
        b"class TestThing:\n"
        b"    def test_it(self):\n"
        b"        assert run() == 1\n"
        b"def helper():\n"
        b"    assert True\n"
    )
    model = PythonCodeModel().model(
        {"tests/test_t.py": source},
        python_fixture.declaration(),
        python_fixture.VOCABULARY,
        None,
    )

    assert isinstance(model, CodeModel)
    assert [(t.symbol, t.calls, t.assertions) for t in model.test_cases] == [
        ("TestThing.test_it", ("run",), (Assertion("run() == 1"),))
    ]


def _model_of(sources: dict[str, bytes]) -> CodeModel:
    model = PythonCodeModel().model(
        sources, python_fixture.declaration(), python_fixture.VOCABULARY, None
    )
    assert isinstance(model, CodeModel), model
    return model


def test_measured_code_is_never_run_even_when_it_shadows_the_analyzer(
    tmp_path: Path,
) -> None:
    """Given measured packages named like modules the import analyzer itself
    runs on (grimp, logging), each of which would write a marker when
    executed, When they are modelled, Then no marker is written and those
    packages are Unparsed with the reason, never run."""
    marker = tmp_path / "ran"
    payload = f"open({str(marker)!r}, 'w').write('ran')\n".encode()
    sources = {
        "grimp/__init__.py": payload,
        "grimp/a.py": b"",
        "logging/__init__.py": payload,
        "logging/b.py": b"",
        "ok/__init__.py": b"",
        "ok/c.py": b"from ok import d\n",
        "ok/d.py": payload,
    }

    model = _model_of(sources)

    assert not marker.exists(), "measured code ran"
    assert {(e.path, e.imported_path) for e in model.imports} == {
        ("ok/c.py", "ok/d.py")
    }
    unparsed = {u.path for u in model.unparsed}
    assert {"grimp/__init__.py", "logging/b.py"} <= unparsed
    assert not unparsed & {"ok/c.py", "ok/d.py"}


def test_one_unparsable_file_leaves_the_rest_of_its_package_modelled() -> None:
    """Given a package with one file that is not Python, When it is modelled,
    Then only that file is Unparsed, the others keep their import edges, and
    the reason names the file by its repository path."""
    sources = {
        "pkg/__init__.py": b"",
        "pkg/a.py": b"from pkg import c\n",
        "pkg/bad.py": b"def (:\n",
        "pkg/c.py": b"",
    }

    model = _model_of(sources)

    assert [u.path for u in model.unparsed] == ["pkg/bad.py"]
    assert {(e.path, e.imported_path) for e in model.imports} == {
        ("pkg/a.py", "pkg/c.py")
    }


def test_same_named_packages_under_two_roots_are_each_modelled() -> None:
    """Given two top-level packages of one name under different roots, as a
    monorepo holds them, When they are modelled, Then each resolves its own
    imports inside its own root and neither is Unparsed."""
    sources = {
        "a/pkg/__init__.py": b"",
        "a/pkg/m.py": b"from . import z\n",
        "a/pkg/z.py": b"",
        "b/pkg/__init__.py": b"",
        "b/pkg/m.py": b"from pkg import r\n",
        "b/pkg/r.py": b"",
    }

    model = _model_of(sources)

    assert model.unparsed == ()
    assert {(e.path, e.imported_path) for e in model.imports} == {
        ("a/pkg/m.py", "a/pkg/z.py"),
        ("b/pkg/m.py", "b/pkg/r.py"),
    }


def test_a_file_nested_past_the_walk_is_unparsed_and_the_rest_modelled() -> None:
    """Given a file that parses but nests deeper than the analyzer can walk,
    When it is modelled with another file, Then that file is Unparsed and
    the other is modelled; the run does not end."""
    deep = b"x = " + b"+".join([b"1"] * 5000) + b"\n"

    model = _model_of({"deep.py": deep, "fine.py": b"def f() -> int:\n    return 1\n"})

    assert [u.path for u in model.unparsed] == ["deep.py"]
    assert any(d.unit.symbol == "f" for d in model.definitions)


def test_model_past_the_deadline_between_files_times_out() -> None:
    """Given a deadline that passes after the run has started, When the
    files are modelled, Then the answer is TimedOut rather than an overrun."""
    clock = iter([0.0, 10.0, 20.0, 30.0])
    model = PythonCodeModel(clock=lambda: next(clock, 99.0)).model(
        {"a.py": b"x = 1\n", "b.py": b"y = 2\n"},
        python_fixture.declaration(),
        python_fixture.VOCABULARY,
        Deadline(epoch_seconds=5.0),
    )

    assert isinstance(model, TimedOut)


def test_environment_reads_sleeps_and_stubs_come_from_the_vocabulary() -> None:
    """Given a vocabulary that counts `settings.env` as an environment read,
    `pause` as a sleep and only `pass` as a stub, When code is modelled with
    it, Then the model follows that vocabulary, not a fixed list."""
    vocabulary = Vocabulary(
        regions={},
        environment_reads=frozenset({"settings.env"}),
        sleeps=frozenset({"pause"}),
        stubs=frozenset({"pass"}),
    )
    source = (
        b"def a():\n"
        b"    return settings.env\n"
        b"def b():\n"
        b"    pause(1)\n"
        b"    time.sleep(1)\n"
        b"def c():\n"
        b"    ...\n"
        b"def d():\n"
        b"    pass\n"
    )
    model = PythonCodeModel().model(
        {"m.py": source}, python_fixture.declaration(), vocabulary, None
    )

    assert isinstance(model, CodeModel)
    assert [(a.within, a.target) for a in model.accesses] == [("a", "settings.env")]
    bodies = {d.unit.symbol: d.body for d in model.definitions}
    assert bodies["b"].sleeps == (4,)
    assert (bodies["c"].stub_markers, bodies["d"].stub_markers) == ((), ("pass",))


def test_an_environment_read_through_a_method_is_an_access() -> None:
    """Given `os.environ.get(...)`, `os.environ[...]` and `os.getenv(...)`,
    When they are modelled, Then each is an environment access, the first
    included though its chain runs past the vocabulary's name."""
    source = (
        b"import os\na = os.environ.get('A')\nb = os.environ['B']\nc = os.getenv('C')\n"
    )

    model = _model_of({"m.py": source})

    assert sorted((a.line, a.target) for a in model.accesses) == [
        (2, "os.environ.get"),
        (3, "os.environ"),
        (4, "os.getenv"),
    ]


def test_a_file_without_a_final_newline_ends_on_its_last_line() -> None:
    """Given files with and without a final newline, When they are modelled,
    Then each file unit ends on its own last line."""
    model = _model_of({"a.py": b"x = 1\ny = 2", "b.py": b"x = 1\ny = 2\n", "c.py": b""})

    ends = {u.path: u.end for u in model.units if u.kind is UnitKind.FILE}
    assert ends == {"a.py": 2, "b.py": 2, "c.py": 1}


def test_a_form_feed_shifts_no_line_numbers() -> None:
    """Given a script with a form feed inside an early line, When it is
    modelled, Then bodies and import edges keep the lines Python gives them."""
    source = b"# page one\x0c\nimport os\n\ndef f():\n    return 42\n"

    model = _model_of({"s.py": source})

    [edge] = model.imports
    assert (edge.line, edge.text) == (2, "import os")
    [definition] = model.definitions
    assert definition.body.text == "    return 42"


def test_field_writes_through_unpacking_and_loop_targets_are_writes() -> None:
    """Given fields assigned by tuple unpacking, a starred target, a for
    target and a with target, When they are modelled, Then each is a write
    and the fields set on self are members."""
    source = (
        b"class T:\n"
        b"    def __init__(self, o):\n"
        b"        self.a, (self.b, *self.c) = 1, (2, 3)\n"
        b"        for self.d in []:\n"
        b"            pass\n"
        b"        with open('x') as o.e:\n"
        b"            pass\n"
    )

    model = _model_of({"m.py": source})

    assert sorted((w.target, w.field) for w in model.writes) == [
        ("o", "e"),
        ("self", "a"),
        ("self", "b"),
        ("self", "c"),
        ("self", "d"),
    ]
    assert {m.name for m in model.members} == {"__init__", "a", "b", "c", "d"}


def test_a_standalone_module_resolves_its_sibling() -> None:
    """Given a flat layout with no packages, where a.py imports its sibling
    b.py, When it is modelled, Then the edge names b.py as its target."""
    model = _model_of({"a.py": b"import b\n", "b.py": b"", "tools/c.py": b"import b\n"})

    assert {(e.path, e.imported, e.imported_path) for e in model.imports} == {
        ("a.py", "b", "b.py"),
        ("tools/c.py", "b", None),
    }


def test_a_package_resolves_imports_into_a_package_under_another_root() -> None:
    """Given a tests/ package importing tool.domain.rules from src/, and two
    same-named packages elsewhere, When they are modelled, Then the edge
    names the exact module and its file, and the same-named packages still
    resolve each inside its own root."""
    sources = {
        "src/tool/__init__.py": b"",
        "src/tool/domain/__init__.py": b"",
        "src/tool/domain/rules.py": b"",
        "tests/__init__.py": b"",
        "tests/test_rules.py": b"from tool.domain import rules\n",
        "a/pkg/__init__.py": b"",
        "a/pkg/m.py": b"from . import z\n",
        "a/pkg/z.py": b"",
        "b/pkg/__init__.py": b"",
        "b/pkg/m.py": b"from pkg import r\n",
        "b/pkg/r.py": b"",
    }

    model = _model_of(sources)

    assert model.unparsed == ()
    assert {(e.path, e.imported, e.imported_path) for e in model.imports} == {
        ("tests/test_rules.py", "tool.domain.rules", "src/tool/domain/rules.py"),
        ("a/pkg/m.py", "pkg.z", "a/pkg/z.py"),
        ("b/pkg/m.py", "pkg.r", "b/pkg/r.py"),
    }


def test_declared_line_regions_are_in_the_model() -> None:
    """Given a declaration that assigns a region by lines, When its file is
    modelled, Then that region is in the model beside the layer it gives,
    and a region of a file not handed over is not."""
    declaration = parse_declaration(
        b"[layers]\nregions = [\n"
        b'  { file = "m.py", layer = "domain", lines = [1, 2] },\n'
        b'  { file = "absent.py", layer = "domain", lines = [1, 2] },\n'
        b"]\n"
    )
    assert isinstance(declaration, Declaration)

    model = PythonCodeModel().model(
        {"m.py": b"def f():\n    return 1\n"},
        declaration,
        python_fixture.VOCABULARY,
        None,
    )

    assert isinstance(model, CodeModel)
    assert model.regions == (Region("m.py", 1, 2, Layer.DOMAIN),)
    assert [d.unit.layer for d in model.definitions] == [Layer.DOMAIN]


def test_a_body_raising_a_stub_exception_after_other_statements_is_a_stub() -> None:
    """Given functions that do something and then raise NotImplementedError,
    and one that raises it only on one branch, When they are modelled, Then
    the two whose body raises it are stubs whatever precedes the raise, and
    the branching one is not (Self-review R8)."""
    source = (
        b"def later():\n"
        b"    x = 0\n"
        b"    raise NotImplementedError('later')\n"
        b"def logged(log):\n"
        b"    log('called')\n"
        b"    raise NotImplementedError\n"
        b"def partial(mode):\n"
        b"    if mode:\n"
        b"        raise NotImplementedError\n"
        b"    return 1\n"
    )

    model = _model_of({"src/tool/domain/later.py": source})

    markers = {d.unit.symbol: d.body.stub_markers for d in model.definitions}
    assert markers == {
        "later": ("NotImplementedError",),
        "logged": ("NotImplementedError",),
        "partial": (),
    }


def test_a_sleep_imported_under_another_name_is_a_sleep() -> None:
    """Given functions that sleep through `from time import sleep as nap`
    and `import time as clock`, When they are modelled, Then each body names
    the line it sleeps on (Self-review R8)."""
    source = (
        b"import time as clock\n"
        b"from time import sleep as nap\n"
        b"def napping():\n"
        b"    nap(1)\n"
        b"def clocked():\n"
        b"    clock.sleep(1)\n"
    )

    model = _model_of({"src/tool/application/wait.py": source})

    sleeps = {d.unit.symbol: d.body.sleeps for d in model.definitions}
    assert sleeps == {"napping": (4,), "clocked": (6,)}


def test_calls_resolve_through_imports_definitions_and_bases() -> None:
    """Given calls through an aliased import, a relative import, a package's
    re-export, the file's own function, a method of the test type, a method
    a unittest TestCase carries, and a method of a local variable, When they
    are modelled, Then each call names what it resolves to -- the
    repository's definition by path and symbol, or the dotted name outside
    it -- and the local variable's method resolves to nothing."""
    sources = {
        "src/app/__init__.py": b"",
        "src/app/domain/__init__.py": b"from .rules import price\n",
        "src/app/domain/rules.py": b"def price():\n    return 1\n",
        "src/app/application/__init__.py": b"",
        "src/app/application/use.py": (
            b"from ..domain.rules import price as cost\ndef run():\n    return cost()\n"
        ),
        "tests/test_use.py": (
            b"import unittest\n"
            b"from time import sleep as nap\n"
            b"from app.domain import price\n"
            b"def helper():\n"
            b"    nap(0)\n"
            b"class TestUse(unittest.TestCase):\n"
            b"    def check(self):\n"
            b"        pass\n"
            b"    def test_it(self):\n"
            b"        double = object()\n"
            b"        helper()\n"
            b"        self.check()\n"
            b"        self.assertEqual(price(), 1)\n"
            b"        double.run()\n"
        ),
    }

    model = _model_of(sources)

    targets = {
        (c.within, c.callee): None
        if c.target is None
        else (c.target.name, c.target.path, c.target.symbol)
        for c in model.calls
    }
    rules = "src/app/domain/rules.py"
    test = "tests/test_use.py"
    assert targets[("run", "cost")] == ("app.domain.rules.price", rules, "price")
    assert targets[("helper", "nap")] == ("time.sleep", None, None)
    assert targets[("TestUse.test_it", "helper")] == ("helper", test, "helper")
    assert targets[("TestUse.test_it", "self.check")] == (
        "TestUse.check",
        test,
        "TestUse.check",
    )
    assert targets[("TestUse.test_it", "self.assertEqual")] == (
        "unittest.TestCase.assertEqual",
        None,
        None,
    )
    assert targets[("TestUse.test_it", "price")] == (
        "app.domain.rules.price",
        rules,
        "price",
    )
    assert targets[("TestUse.test_it", "double.run")] is None
