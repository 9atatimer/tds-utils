"""without: the CodeModel a check that does not read a language is given
(task-070). Every fact of a dropped file is gone, every fact of a kept file
stays, and so a check never reads a script it says it does not read."""

from __future__ import annotations

import dataclasses

from adherence.domain.model import (
    Access,
    AccessKind,
    Binding,
    Body,
    Call,
    Clone,
    CodeModel,
    Complexity,
    Conditional,
    Definition,
    ImportEdge,
    Layer,
    Member,
    MemberKind,
    Metrics,
    Reference,
    ReferenceKind,
    Region,
    Span,
    TestCase,
    Unit,
    UnitKind,
    Unparsed,
    Write,
    without,
)

KEPT, DROPPED = "src/a.py", "bin/b.sh"


def _facts(path: str) -> CodeModel:
    """One fact of every family in one file."""
    unit = Unit(path, UnitKind.FUNCTION, "f", 1, 2, Layer.DOMAIN)
    return CodeModel(
        units=(Unit(path, UnitKind.FILE, None, 1, 9, Layer.DOMAIN), unit),
        imports=(ImportEdge(path, "os", 1, "import os", None),),
        definitions=(Definition(unit, None, Body("", (), ()), (), (), None, False),),
        references=(Reference(path, 1, "f", ReferenceKind.NAME, "x"),),
        calls=(Call(path, 1, "f", "g"),),
        accesses=(Access(path, 1, "f", AccessKind.ENVIRONMENT, "os.environ"),),
        writes=(Write(path, 1, "f", "self", "x"),),
        bindings=(Binding(path, 1, None, "Payload", "dict"),),
        conditionals=(Conditional(path, 1, "f", "x"),),
        members=(Member(path, "T", "x", MemberKind.FIELD, 1),),
        test_cases=(TestCase(path, "t", 1, (), ()),),
        regions=(Region(path, 1, 2, Layer.DOMAIN),),
        unparsed=(Unparsed(path, "why"),),
        metrics=Metrics(complexity=(Complexity(path, "f", 1, 3),)),
    )


def _paths(model: CodeModel) -> dict[str, set[str]]:
    """Each fact family's files, metrics included."""
    found: dict[str, set[str]] = {}
    for field in dataclasses.fields(CodeModel):
        if field.name == "metrics":
            continue
        found[field.name] = {
            fact.unit.path if isinstance(fact, Definition) else fact.path
            for fact in getattr(model, field.name)
        }
    found["complexity"] = {c.path for c in model.metrics.complexity}
    found["clones"] = {
        p for c in model.metrics.clones for p in (c.first.path, c.second.path)
    }
    return found


def _both() -> CodeModel:
    kept, dropped = _facts(KEPT), _facts(DROPPED)
    clones = (
        Clone(Span(KEPT, 1, 2), Span(KEPT, 5, 6), 2),
        Clone(Span(KEPT, 1, 2), Span(DROPPED, 1, 2), 2),
        Clone(Span(DROPPED, 1, 2), Span(KEPT, 5, 6), 2),
    )
    return dataclasses.replace(
        CodeModel(
            **{
                f.name: getattr(kept, f.name) + getattr(dropped, f.name)
                for f in dataclasses.fields(CodeModel)
                if f.name != "metrics"
            }
        ),
        metrics=Metrics(
            complexity=kept.metrics.complexity + dropped.metrics.complexity,
            clones=clones,
        ),
    )


def test_the_fixture_plants_a_fact_of_every_family() -> None:
    """Given the CodeModel's fields, When the fixture is built, Then every
    fact family holds a fact, so a family added later must be planted here
    before the restriction can be shown to filter it."""
    planted = _facts(KEPT)

    empty = [
        f.name
        for f in dataclasses.fields(CodeModel)
        if f.name != "metrics" and not getattr(planted, f.name)
    ]
    assert empty == []


def test_without_a_file_drops_every_fact_of_it_and_keeps_the_rest() -> None:
    """Given a model holding one fact of every family in each of two files,
    and clones within one file and across both, When the second file is
    dropped, Then every family holds only the first file's facts, and only
    the clone that touches no dropped file remains."""
    model = without(_both(), [DROPPED])

    paths = _paths(model)
    assert {family: files for family, files in paths.items()} == {
        family: {KEPT} for family in paths
    }
    assert model.metrics.clones == (Clone(Span(KEPT, 1, 2), Span(KEPT, 5, 6), 2),)


def test_without_nothing_is_the_model_unchanged() -> None:
    """Given a model, When no file is dropped, Then every fact remains."""
    model = _both()

    assert without(model, []) == model
