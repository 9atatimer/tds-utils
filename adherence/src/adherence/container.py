"""container.py -- the composition root of the adhere CLI.

The one module that constructs concrete adapters and binds them by stage
(ARCHITECTURE.ARCH-ADHERENCE.md, Module map and Where it runs), and that
supplies the suite's shipped Parameters. It never imports the fakes; a
test passes them in through the overrides.
"""

from __future__ import annotations

import enum
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from adherence.adapters.file_store import FileReportStore, default_store_dir
from adherence.adapters.git import GitRepository
from adherence.adapters.jscpd import JscpdDuplication
from adherence.adapters.lizard import LizardComplexity
from adherence.adapters.markdown_records import MarkdownRecords
from adherence.adapters.no_judge import NoJudge
from adherence.adapters.no_reviews import NoReviews
from adherence.adapters.python_ast import PythonCodeModel
from adherence.domain.model import CodeLanguage, Layer
from adherence.domain.parameters import Limits, Parameters, Vocabulary
from adherence.domain.questions import ThresholdPolicy
from adherence.ports.code_model import CodeModelPort
from adherence.ports.complexity import ComplexityPort
from adherence.ports.decision import DecisionPort
from adherence.ports.duplication import DuplicationPort
from adherence.ports.records import RecordsPort
from adherence.ports.report_store import ReportStore
from adherence.ports.repository import RepositoryPort
from adherence.ports.review import ReviewPort

# --- Shipped parameters --------------------------------------------------------

# unittest's TestCase assertion methods; the Python analyzer resolves
# `self.<method>` in a TestCase subclass to `unittest.TestCase.<method>`.
UNITTEST_ASSERTIONS = frozenset(
    f"unittest.TestCase.{method}"
    for method in (
        "assertAlmostEqual",
        "assertCountEqual",
        "assertDictEqual",
        "assertEqual",
        "assertFalse",
        "assertGreater",
        "assertGreaterEqual",
        "assertIn",
        "assertIs",
        "assertIsInstance",
        "assertIsNone",
        "assertIsNot",
        "assertIsNotNone",
        "assertLess",
        "assertLessEqual",
        "assertListEqual",
        "assertLogs",
        "assertMultiLineEqual",
        "assertNoLogs",
        "assertNotAlmostEqual",
        "assertNotEqual",
        "assertNotIn",
        "assertNotIsInstance",
        "assertNotRegex",
        "assertRaises",
        "assertRaisesRegex",
        "assertRegex",
        "assertSequenceEqual",
        "assertSetEqual",
        "assertTrue",
        "assertTupleEqual",
        "assertWarns",
        "assertWarnsRegex",
        "fail",
    )
)

# A top-level import name -> the distribution a radar names it by, where the
# two differ by more than case and separators.
DISTRIBUTIONS = {
    "attr": "attrs",
    "Bio": "biopython",
    "bs4": "beautifulsoup4",
    "cairo": "pycairo",
    "Crypto": "pycryptodome",
    "cv2": "opencv-python",
    "dateutil": "python-dateutil",
    "dns": "dnspython",
    "docx": "python-docx",
    "dotenv": "python-dotenv",
    "engineio": "python-engineio",
    "faiss": "faiss-cpu",
    "fitz": "PyMuPDF",
    "gi": "PyGObject",
    "git": "GitPython",
    "grpc": "grpcio",
    "jose": "python-jose",
    "jwt": "PyJWT",
    "kafka": "kafka-python",
    "ldap": "python-ldap",
    "Levenshtein": "python-Levenshtein",
    "magic": "python-magic",
    "markdown_it": "markdown-it-py",
    "mpl_toolkits": "matplotlib",
    "multipart": "python-multipart",
    "MySQLdb": "mysqlclient",
    "nacl": "PyNaCl",
    "OpenGL": "PyOpenGL",
    "OpenSSL": "pyOpenSSL",
    "PIL": "Pillow",
    "pkg_resources": "setuptools",
    "pptx": "python-pptx",
    "_pytest": "pytest",
    "pythoncom": "pywin32",
    "ruamel": "ruamel.yaml",
    "serial": "pyserial",
    "skimage": "scikit-image",
    "sklearn": "scikit-learn",
    "slugify": "python-slugify",
    "socketio": "python-socketio",
    "telegram": "python-telegram-bot",
    "umap": "umap-learn",
    "usb": "pyusb",
    "websocket": "websocket-client",
    "win32api": "pywin32",
    "win32com": "pywin32",
    "wx": "wxPython",
    "Xlib": "python-xlib",
    "yaml": "PyYAML",
    "zmq": "pyzmq",
}

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
    mechanism_calls=frozenset(
        {
            "open",
            "io.open",
            "__import__",
            "importlib.import_module",
            "importlib.__import__",
        }
    ),
    fakes=frozenset({"Fake", "InMemory"}),
    clocks=frozenset({"Clock"}),
    callables=frozenset({"Callable"}),
    wire_formats=frozenset(
        {
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
    abstract_markers=frozenset(
        {"Protocol", "ABC", "ABCMeta", "abstractmethod", "overload"}
    ),
    assertion_calls=frozenset(
        {
            "pytest.raises",
            "pytest.warns",
            "pytest.fail",
            "assert_called",
            "assert_called_once",
            "assert_called_with",
            "assert_called_once_with",
            "assert_any_call",
            "assert_has_calls",
            "assert_not_called",
        }
        | UNITTEST_ASSERTIONS
    ),
    placeholder_assertions=frozenset({"True", "False", "1", "0", "None"}),
    standard_library=frozenset(sys.stdlib_module_names),
    packages=DISTRIBUTIONS,
)
SHIPPED_LIMITS = Limits(
    evidence_bound=200,
    complexity_ceiling=15,
    duplication_ceiling=10,
    record_statuses=frozenset({"APPROVED", "IMPLEMENTED"}),
)
SHIPPED_PARAMETERS = Parameters(
    thresholds=ThresholdPolicy(), vocabulary=SHIPPED_VOCABULARY, limits=SHIPPED_LIMITS
)

# The engine's own node analyzers, installed beside its uv project by
# `npm ci --ignore-scripts` (adherence/package-lock.json).
JSCPD = Path(__file__).resolve().parents[2] / "node_modules" / ".bin" / "jscpd"

# --- Composition root ----------------------------------------------------------


class Stage(enum.Enum):
    """The places the one runtime runs in."""

    LAPTOP = "laptop"
    HOOK = "hook"
    CI = "ci"
    CLOUD = "cloud"


@dataclass(frozen=True, slots=True)
class Container:
    """The ports bound for one stage, and the parameters."""

    stage: Stage
    repository: RepositoryPort
    reviews: ReviewPort
    analyzers: Mapping[CodeLanguage, CodeModelPort]
    judge: DecisionPort
    complexity: ComplexityPort
    duplication: DuplicationPort
    records: RecordsPort
    reports: ReportStore
    parameters: Parameters


def build(
    stage: Stage,
    *,
    root: str,
    repository: RepositoryPort | None = None,
    reviews: ReviewPort | None = None,
    analyzers: Mapping[CodeLanguage, CodeModelPort] | None = None,
    judge: DecisionPort | None = None,
    complexity: ComplexityPort | None = None,
    duplication: DuplicationPort | None = None,
    records: RecordsPort | None = None,
    reports: ReportStore | None = None,
) -> Container:
    """Bind every port for the stage, over the repository at root.

    Every stage reads the repository through git; which target it reads
    (working tree, staged index, revisions) is the entry point's choice.
    Every stage binds no_judge until the decide adapter lands (task-064);
    the judged checks read as coverage meanwhile. Every stage binds
    no_reviews until github_reviews lands for ci (task-063), and the file
    cache in the per-user cache directory until the warehouse lands for ci
    (task-067).
    """
    bound = repository if repository is not None else GitRepository(root)
    return Container(
        stage=stage,
        repository=bound,
        reviews=reviews if reviews is not None else NoReviews(),
        analyzers=(
            analyzers
            if analyzers is not None
            else {CodeLanguage.PYTHON: PythonCodeModel()}
        ),
        judge=judge if judge is not None else NoJudge(),
        complexity=complexity if complexity is not None else LizardComplexity(),
        duplication=(
            duplication
            if duplication is not None
            else JscpdDuplication(command=(str(JSCPD),))
        ),
        records=records if records is not None else MarkdownRecords(bound),
        reports=(
            reports
            if reports is not None
            else FileReportStore(
                default_store_dir(os.environ, Path.home()), root=Path(root)
            )
        ),
        parameters=SHIPPED_PARAMETERS,
    )
