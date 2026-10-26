"""Drive `measure` by its signature with a fake behind every port.

A test names the files the repository holds, the facts the code model
answers with, and the declaration; everything else defaults to a port
that answers plainly (no complexity, no clones, no records, no judge).
"""

from __future__ import annotations

from collections.abc import Mapping

from adherence.adapters.fakes import (
    FakeCodeModel,
    FakeComplexity,
    FakeDecision,
    FakeDuplication,
    FakeRecords,
    FakeRepository,
)
from adherence.application.measure import measure
from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.declaration import (
    Declaration,
    DeclarationUnreadable,
    parse_declaration,
)
from adherence.domain.model import CodeLanguage, CodeModel, Layer
from adherence.domain.parameters import Limits, Parameters, Vocabulary
from adherence.domain.questions import ThresholdPolicy, Unavailable
from adherence.domain.records import DesignRecords, Radar, RecordsUnavailable
from adherence.domain.report import Report
from adherence.domain.target import Head
from adherence.ports.code_model import CodeModelPort
from adherence.ports.repository import Refused

HEAD = Head.working_tree()

VOCABULARY = Vocabulary(
    regions={"predicates": Layer.DOMAIN},
    environment_reads=frozenset({"os.environ", "os.getenv"}),
    stubs=frozenset({"pass", "...", "NotImplementedError"}),
    vendors=frozenset({"requests", "os", "boto3"}),
    model_ids=frozenset({"claude-", "gpt-"}),
    mechanism_calls=frozenset({"open", "__import__", "importlib.import_module"}),
    fakes=frozenset({"Fake"}),
    abstract_markers=frozenset({"Protocol", "ABC", "abstractmethod"}),
    assertion_calls=frozenset({"pytest.raises"}),
    placeholder_assertions=frozenset({"True", "False", "1"}),
    standard_library=frozenset({"__future__", "dataclasses", "os"}),
    packages={"markdown_it": "markdown-it-py"},
    callables=frozenset({"Callable"}),
    wire_formats=frozenset({"dict", "Response"}),
    singletons=frozenset({"sys.argv"}),
    plain_types=frozenset({"Sequence", "tuple", "None", "str", "int", "list"}),
)
LIMITS = Limits(evidence_bound=200)

HEXAGON = b"""
[layers]
domain = ["src/app/domain/**"]
application = ["src/app/application/**"]
ports = ["src/app/ports/**"]
adapters = ["src/app/adapters/**"]
"composition root" = ["src/app/container.py"]
test = ["tests/**"]
"""


def declared(text: bytes = HEXAGON) -> Declaration:
    parsed = parse_declaration(text)
    assert isinstance(parsed, Declaration), parsed
    return parsed


def parameters(
    *, vocabulary: Vocabulary = VOCABULARY, limits: Limits = LIMITS
) -> Parameters:
    return Parameters(
        thresholds=ThresholdPolicy(), vocabulary=vocabulary, limits=limits
    )


def measure_with(
    files: Mapping[str, bytes | Refused | TimedOut],
    facts: CodeModel | None = None,
    declaration: Declaration | DeclarationUnreadable | None = None,
    *,
    records: DesignRecords | RecordsUnavailable | TimedOut | None = None,
    radar: Radar | RecordsUnavailable | TimedOut | None = None,
    analyzers: Mapping[CodeLanguage, CodeModelPort] | None = None,
    limits: Limits = LIMITS,
    vocabulary: Vocabulary = VOCABULARY,
    complexity: FakeComplexity | None = None,
    duplication: FakeDuplication | None = None,
    deadline: Deadline | None = None,
    unlisted: Refused | TimedOut | None = None,
) -> Report:
    """measure over a repository holding `files` at the working tree, whose
    Python analyzer answers with `facts`."""
    return measure(
        HEAD,
        declaration if declaration is not None else declared(),
        repository=FakeRepository({HEAD: files}, unlisted=unlisted),
        analyzers=(
            analyzers
            if analyzers is not None
            else {CodeLanguage.PYTHON: FakeCodeModel(facts=facts or CodeModel())}
        ),
        complexity=complexity or FakeComplexity(),
        duplication=duplication or FakeDuplication(),
        records=FakeRecords(
            {} if records is None else {HEAD: records},
            radar={} if radar is None else {HEAD: radar},
        ),
        judge=FakeDecision(Unavailable("no judge in the unit tier")),
        parameters=parameters(vocabulary=vocabulary, limits=limits),
        deadline=deadline,
    )
