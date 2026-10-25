"""The TypeScript code model over this repository's own lib/decide/ and its
tests (task-069's done condition), read as the use case would hand them
over: nothing is copied into the fixtures, so the model is checked against
the real tree as it stands."""

from __future__ import annotations

import re
from pathlib import Path

from adherence.adapters.ts_depcruise import TypeScriptCodeModel
from adherence.domain.declaration import Declaration, parse_declaration
from adherence.domain.model import CodeModel, Layer, UnitKind
from adherence.domain.parameters import Vocabulary
from tests import typescript_fixture

REPOSITORY = Path(__file__).resolve().parents[3]
DECLARATION = b'[layers]\ndomain = ["lib/decide/**"]\ntest = ["test/**"]\n'
VOCABULARY = Vocabulary(
    regions={},
    environment_reads=frozenset({"process.env"}),
    tests=frozenset({"test", "it"}),
    assertions=frozenset({"assert", "expect"}),
)
TEST_CALL = re.compile(r"^test\(", re.MULTILINE)
EXPORTED = re.compile(r"^export (?:async )?function (\w+)", re.MULTILINE)


def _sources() -> dict[str, bytes]:
    paths = sorted(REPOSITORY.glob("lib/decide/*.mjs")) + sorted(
        REPOSITORY.glob("test/decide_*.test.mjs")
    )
    return {p.relative_to(REPOSITORY).as_posix(): p.read_bytes() for p in paths}


def _model(sources: dict[str, bytes]) -> CodeModel:
    declaration = parse_declaration(DECLARATION)
    assert isinstance(declaration, Declaration)
    model = TypeScriptCodeModel().model(sources, declaration, VOCABULARY, None)
    assert isinstance(model, CodeModel), model
    return model


@typescript_fixture.needs_cruiser
def test_lib_decide_is_modelled_whole() -> None:
    """Given lib/decide/ and its node:test suites, When they are modelled,
    Then no file is Unparsed, each is a file unit in its layer, every
    exported function is a definition, every relative import between them
    resolves to its file, and every top-level test() is a test case."""
    sources = _sources()
    model = _model(sources)
    texts = {path: data.decode() for path, data in sources.items()}

    assert len(sources) >= 10, "lib/decide/ or its tests moved"
    assert model.unparsed == ()
    files = {u.path: u.layer for u in model.units if u.kind is UnitKind.FILE}
    assert files == {
        path: Layer.DOMAIN if path.startswith("lib/") else Layer.TEST
        for path in sources
    }
    defined = {(d.unit.path, d.unit.symbol) for d in model.definitions}
    for path, text in texts.items():
        for name in EXPORTED.findall(text):
            assert (path, name) in defined, (path, name)
    relative = [e for e in model.imports if e.imported.endswith(".mjs")]
    assert relative, "no relative import found"
    assert all(e.imported_path in sources for e in relative), relative
    tests = sum(len(TEST_CALL.findall(text)) for text in texts.values())
    assert len(model.test_cases) == tests
