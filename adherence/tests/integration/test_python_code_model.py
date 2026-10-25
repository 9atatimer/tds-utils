"""The Python CodeModelPort adapter over the fixture tree, one member at a
time (task-057), after the shared contract."""

from __future__ import annotations

import functools

from adherence.adapters.python_ast import PythonCodeModel
from adherence.domain.model import (
    AccessKind,
    CodeModel,
    Definition,
    Layer,
    MemberKind,
    Parameter,
    ReferenceKind,
    Signature,
    UnitKind,
)
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
            ("close_order is not None",),
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
        ("TestThing.test_it", ("run",), ("run() == 1",))
    ]
