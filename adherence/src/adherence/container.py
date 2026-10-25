"""container.py -- the composition root of the adhere CLI.

The one module that constructs concrete adapters and binds them by stage
(ARCHITECTURE.ARCH-ADHERENCE.md, Module map and Where it runs), and that
supplies the suite's shipped Parameters. It never imports the fakes; a
test passes them in through the overrides.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass

from adherence.adapters.git import GitRepository
from adherence.adapters.no_judge import NoJudge
from adherence.adapters.python_ast import PythonCodeModel
from adherence.domain.model import CodeLanguage, Layer
from adherence.domain.parameters import Limits, Parameters, Vocabulary
from adherence.domain.questions import ThresholdPolicy
from adherence.ports.code_model import CodeModelPort
from adherence.ports.complexity import ComplexityPort
from adherence.ports.decision import DecisionPort
from adherence.ports.duplication import DuplicationPort
from adherence.ports.records import RecordsPort
from adherence.ports.repository import RepositoryPort

# --- Shipped parameters --------------------------------------------------------

SHIPPED_VOCABULARY = Vocabulary(
    regions={
        "predicates": Layer.DOMAIN,
        "pure helpers": Layer.DOMAIN,
        "action functions": Layer.ADAPTERS,
        "flow functions": Layer.APPLICATION,
        "entry points": Layer.COMPOSITION_ROOT,
        "main": Layer.COMPOSITION_ROOT,
    },
    environment_reads=frozenset(
        {"os.environ", "os.environb", "os.getenv", "os.getenvb", "os.putenv"}
    ),
    sleeps=frozenset({"sleep"}),
    stubs=frozenset({"pass", "...", "NotImplementedError"}),
    vendors=frozenset(
        {
            "os",
            "io",
            "pathlib",
            "shutil",
            "glob",
            "tempfile",
            "subprocess",
            "socket",
            "ssl",
            "http",
            "urllib",
            "requests",
            "httpx",
            "aiohttp",
            "boto3",
            "botocore",
            "anthropic",
            "openai",
            "google.cloud",
            "google.genai",
            "sqlite3",
        }
    ),
    model_ids=frozenset(
        {"claude-", "gpt-", "gemini-", "llama", "mistral-", "o1-", "o3-", "o4-"}
    ),
    fakes=frozenset({"Fake", "InMemory"}),
    callables=frozenset({"Callable"}),
    wire_formats=frozenset(
        {
            "dict",
            "Dict",
            "bytes",
            "bytearray",
            "memoryview",
            "Request",
            "Response",
            "HTTPResponse",
            "JSONResponse",
            "ClientResponse",
            "ClientSession",
            "Session",
            "Connection",
            "Cursor",
            "Namespace",
            "Popen",
            "CompletedProcess",
        }
    ),
    singletons=frozenset(
        {"sys.argv", "sys.stdin", "sys.stdout", "sys.stderr", "sys.modules", "sys.path"}
    ),
    plain_types=frozenset(
        {
            "str",
            "int",
            "float",
            "complex",
            "bool",
            "bytes",
            "bytearray",
            "object",
            "None",
            "type",
            "list",
            "dict",
            "set",
            "frozenset",
            "tuple",
            "Any",
            "Optional",
            "Union",
            "Literal",
            "Final",
            "ClassVar",
            "Annotated",
            "Self",
            "Never",
            "NoReturn",
            "TypeVar",
            "Generic",
            "Protocol",
            "Callable",
            "Awaitable",
            "Coroutine",
            "Iterable",
            "Iterator",
            "Generator",
            "AsyncIterable",
            "AsyncIterator",
            "Sequence",
            "MutableSequence",
            "Mapping",
            "MutableMapping",
            "Collection",
            "Container",
            "Set",
            "AbstractSet",
            "MutableSet",
            "Hashable",
            "Sized",
            "Reversible",
            "KeysView",
            "ValuesView",
            "ItemsView",
            "MappingView",
            "AsyncGenerator",
            "ContextManager",
            "AsyncContextManager",
            "AbstractContextManager",
            "AbstractAsyncContextManager",
            "Buffer",
            "SupportsInt",
            "SupportsFloat",
            "SupportsIndex",
            "SupportsAbs",
            "SupportsBytes",
            "SupportsComplex",
            "SupportsRound",
            "Dict",
            "List",
            "Tuple",
            "FrozenSet",
            "Type",
            "Text",
            "AnyStr",
            "DefaultDict",
            "OrderedDict",
            "Counter",
            "ChainMap",
            "Deque",
            "defaultdict",
            "deque",
            "NamedTuple",
            "TypedDict",
            "TypeAlias",
            "TypeGuard",
            "TypeIs",
            "TypeVarTuple",
            "ParamSpec",
            "Concatenate",
            "Required",
            "NotRequired",
            "ReadOnly",
            "Unpack",
            "LiteralString",
            "IO",
            "TextIO",
            "BinaryIO",
            "Pattern",
            "Match",
            "range",
            "slice",
            "memoryview",
            "Exception",
            "BaseException",
            "NoneType",
            "EllipsisType",
            "NotImplementedType",
            "datetime",
            "date",
            "time",
            "timedelta",
            "timezone",
            "tzinfo",
            "Decimal",
            "Fraction",
            "UUID",
            "Path",
            "PurePath",
            "PosixPath",
            "PurePosixPath",
            "WindowsPath",
            "PureWindowsPath",
            "Enum",
            "IntEnum",
            "StrEnum",
            "Flag",
            "IntFlag",
        }
    ),
)
SHIPPED_LIMITS = Limits(evidence_bound=200)
SHIPPED_PARAMETERS = Parameters(
    thresholds=ThresholdPolicy(), vocabulary=SHIPPED_VOCABULARY, limits=SHIPPED_LIMITS
)

# --- Composition root ----------------------------------------------------------


class Stage(enum.Enum):
    """The places the one runtime runs in."""

    LAPTOP = "laptop"
    HOOK = "hook"
    CI = "ci"
    CLOUD = "cloud"


@dataclass(frozen=True, slots=True)
class Container:
    """The ports bound for one stage, and the parameters. A port with no
    adapter in this suite version is None until a test passes a fake: the
    complexity and duplication adapters land in task-061, the records
    adapter in task-059."""

    stage: Stage
    repository: RepositoryPort
    analyzers: Mapping[CodeLanguage, CodeModelPort]
    judge: DecisionPort
    complexity: ComplexityPort | None
    duplication: DuplicationPort | None
    records: RecordsPort | None
    parameters: Parameters


def build(
    stage: Stage,
    *,
    root: str,
    repository: RepositoryPort | None = None,
    analyzers: Mapping[CodeLanguage, CodeModelPort] | None = None,
    judge: DecisionPort | None = None,
    complexity: ComplexityPort | None = None,
    duplication: DuplicationPort | None = None,
    records: RecordsPort | None = None,
) -> Container:
    """Bind every port for the stage, over the repository at root.

    Every stage reads the repository through git; which target it reads
    (working tree, staged index, revisions) is the entry point's choice.
    Every stage binds no_judge until the decide adapter lands (task-064);
    the judged checks read as coverage meanwhile.
    """
    return Container(
        stage=stage,
        repository=repository if repository is not None else GitRepository(root),
        analyzers=(
            analyzers
            if analyzers is not None
            else {CodeLanguage.PYTHON: PythonCodeModel()}
        ),
        judge=judge if judge is not None else NoJudge(),
        complexity=complexity,
        duplication=duplication,
        records=records,
        parameters=SHIPPED_PARAMETERS,
    )
