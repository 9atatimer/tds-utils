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
from dataclasses import dataclass, replace
from pathlib import Path

from adherence.adapters.decide import DecideDecision
from adherence.adapters.file_store import FileReportStore, default_store_dir
from adherence.adapters.git import GitRepository
from adherence.adapters.github_reviews import API, GitHubReviews
from adherence.adapters.jscpd import JscpdDuplication
from adherence.adapters.lizard import LizardComplexity
from adherence.adapters.markdown_records import MarkdownRecords
from adherence.adapters.no_judge import NoJudge
from adherence.adapters.no_reviews import NoReviews
from adherence.adapters.process_worker import ProcessWorker
from adherence.adapters.python_ast import PythonCodeModel
from adherence.adapters.tiered_store import TieredReportStore, Unprovisioned
from adherence.adapters.warehouse import (
    LedgerCredential,
    LedgerSettings,
    WarehouseReportStore,
)
from adherence.domain.model import CodeLanguage, Layer
from adherence.domain.parameters import Limits, Parameters, Vocabulary
from adherence.domain.questions import (
    DOES_IO,
    HAND_ROLLED_ID,
    IMPLEMENTED,
    INVARIANT_BROKEN,
    RULES_ELSEWHERE,
    SAME_CONCEPT,
    SCATTERED_POLICY,
    THEN_ASSERTED,
    TWO_JOBS,
    BandThreshold,
    ChoiceThreshold,
    ThresholdPolicy,
)
from adherence.ports.code_model import CodeModelPort
from adherence.ports.complexity import ComplexityPort
from adherence.ports.decision import DecisionPort
from adherence.ports.duplication import DuplicationPort
from adherence.ports.records import RecordsPort
from adherence.ports.report_store import ReportStore
from adherence.ports.repository import RepositoryPort
from adherence.ports.review import ReviewPort
from adherence.ports.worker import WorkerPort

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
    analyzer_bound=60.0,
    commit_time_bound=10.0,
)
# One entry per judged question, chosen from adherence/evals/ (its
# README.md). Provisional and conservative: the set is six examples per
# question, enough to catch a confidently wrong judge and not to support a
# rate, so a finding needs the judge at 0.9 (0.85 for the score and the
# choice) and the abstention band is wide.
CONSERVATIVE_BINARY = BandThreshold(finding_at=0.9, pass_below=0.35)
SHIPPED_THRESHOLDS = ThresholdPolicy(
    {
        TWO_JOBS.id: CONSERVATIVE_BINARY,
        DOES_IO.id: CONSERVATIVE_BINARY,
        SAME_CONCEPT.id: CONSERVATIVE_BINARY,
        SCATTERED_POLICY.id: CONSERVATIVE_BINARY,
        INVARIANT_BROKEN.id: CONSERVATIVE_BINARY,
        RULES_ELSEWHERE.id: CONSERVATIVE_BINARY,
        THEN_ASSERTED.id: BandThreshold(finding_at=0.85, pass_below=0.3),
        IMPLEMENTED.id: CONSERVATIVE_BINARY,
        HAND_ROLLED_ID: ChoiceThreshold(at=0.85),
    }
)
SHIPPED_PARAMETERS = Parameters(
    thresholds=SHIPPED_THRESHOLDS,
    vocabulary=SHIPPED_VOCABULARY,
    limits=SHIPPED_LIMITS,
)

# The engine's own node analyzers, installed beside its uv project by
# `npm ci --ignore-scripts` (adherence/package-lock.json).
JSCPD = Path(__file__).resolve().parents[2] / "node_modules" / ".bin" / "jscpd"

# The fleet's decide client (docs/ops/decide.md), pinned to the model the
# shipped thresholds were chosen for: two models' probabilities are not
# interchangeable. Its spend is tagged with the suite's own tool name.
DECIDE = Path(__file__).resolve().parents[3] / "bin" / "decide"
DECIDE_COMMAND = (str(DECIDE), "run", "--model", "clef", "--tool", "adherence")
# The door's address on the laptop (DECIDE-ROUTE.DESIGN.md): it speaks the
# SystemOne contract decide's systemone backend sends, and holds the hosted
# credential itself.
DOOR = "DECIDE_URL"
# The hosted gateway and its token, from the CI job's (or cloud session's)
# environment; only the decide client's environment ever holds the token.
HOSTED = ("DECIDE_GATEWAY_URL", "DECIDE_GATEWAY_TOKEN")
# The adherence-ledger warehouse, from the ci job's environment, by the
# data warehouse's credential chain: the four the ledger activates on, the
# region (R2's is `auto`), and the lookup-write pair that only a
# default-branch run's environment carries. Until tds-internal Issue#276
# provisions them, ci binds no warehouse and says what is missing.
LEDGER = (
    "ADHERENCE_LEDGER_ENDPOINT",
    "ADHERENCE_LEDGER_BUCKET",
    "ADHERENCE_LEDGER_ACCESS_KEY_ID",
    "ADHERENCE_LEDGER_SECRET_ACCESS_KEY",
)
LEDGER_REGION = "ADHERENCE_LEDGER_REGION"
LEDGER_LOOKUP = (
    "ADHERENCE_LEDGER_LOOKUP_ACCESS_KEY_ID",
    "ADHERENCE_LEDGER_LOOKUP_SECRET_ACCESS_KEY",
)

# --- Composition root ----------------------------------------------------------


class Stage(enum.Enum):
    """The places the one runtime runs in."""

    LAPTOP = "laptop"
    HOOK = "hook"
    CI = "ci"
    CLOUD = "cloud"


# How many judged questions one run may ask, per stage (provisional: no run
# against the real judge has measured a typical change yet). The hook asks
# none; it binds no judge.
JUDGED_BUDGETS: Mapping[Stage, int] = {
    Stage.LAPTOP: 400,
    Stage.HOOK: 0,
    Stage.CI: 400,
    Stage.CLOUD: 400,
}


def _judge_for(stage: Stage, environment: Mapping[str, str]) -> DecisionPort:
    """The judge a stage asks (ARCHITECTURE.ARCH-ADHERENCE.md, Where it
    runs): the laptop through the door alone, holding no credential; ci,
    and cloud provisionally (Q3), the hosted gateway with its token; the
    hook none. A stage whose judge is not configured has no judge, and
    says what would configure it."""
    if stage is Stage.HOOK:
        return NoJudge("the hook asks no judge")
    if stage is Stage.LAPTOP:
        door = environment.get(DOOR, "").strip()
        if not door:
            return NoJudge(f"no door address is configured ({DOOR})")
        return DecideDecision(
            command=DECIDE_COMMAND,
            configuration={"DECIDE_BACKEND": "systemone", DOOR: door},
        )
    hosted = {k: environment.get(k, "").strip() for k in HOSTED}
    if not all(hosted.values()):
        return NoJudge(f"the hosted judge is not configured ({', '.join(HOSTED)})")
    return DecideDecision(
        command=DECIDE_COMMAND,
        configuration={"DECIDE_BACKEND": "cf-ai-gateway", **hosted},
    )


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
    worker: WorkerPort | None = None


def _reviews(stage: Stage, environ: Mapping[str, str]) -> ReviewPort:
    """github_reviews over the job's token and repository in `ci`;
    no_reviews, which answers Unknown, everywhere else."""
    if stage is not Stage.CI:
        return NoReviews()
    return GitHubReviews(
        repository=environ.get("GITHUB_REPOSITORY"),
        token=environ.get("GITHUB_TOKEN"),
        # A pull request's run judges its base branch; a push's, the branch.
        branch=environ.get("GITHUB_BASE_REF") or environ.get("GITHUB_REF_NAME"),
        api=environ.get("GITHUB_API_URL", API),
    )


def _warehouse(
    root: str, environ: Mapping[str, str]
) -> WarehouseReportStore | Unprovisioned:
    """The warehouse over the ledger the environment configures, for the
    repository at root (named as the report names it); Unprovisioned,
    naming what is missing, when any of the four is absent."""
    values = {name: environ.get(name, "").strip() for name in LEDGER}
    missing = [name for name, value in values.items() if not value]
    if missing:
        return Unprovisioned(
            "the adherence-ledger warehouse is not configured "
            f"({', '.join(missing)} unset; tds-internal Issue#276 provisions it)"
        )
    endpoint, bucket, key_id, secret = values.values()
    lookup_id, lookup_secret = (environ.get(n, "").strip() for n in LEDGER_LOOKUP)
    return WarehouseReportStore(
        repository=Path(root).resolve().name,
        ledger=LedgerSettings(
            endpoint=endpoint,
            bucket=bucket,
            region=environ.get(LEDGER_REGION, "").strip() or "auto",
            scan=LedgerCredential(key_id, secret),
            lookup=(
                LedgerCredential(lookup_id, lookup_secret)
                if lookup_id and lookup_secret
                else None
            ),
        ),
    )


def _reports(stage: Stage, root: str, environ: Mapping[str, str]) -> ReportStore:
    """The file cache in the per-user cache directory; in `ci`, the tiered
    store over it and the warehouse, which reads no base from the runner's
    cache and, with no warehouse configured, keeps the report there only
    and says so."""
    cache = FileReportStore(default_store_dir(environ, Path.home()), root=Path(root))
    if stage is not Stage.CI:
        return cache
    return TieredReportStore(warehouse=_warehouse(root, environ), cache=cache)


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
    environment: Mapping[str, str] | None = None,
    reports: ReportStore | None = None,
    worker: WorkerPort | None = None,
) -> Container:
    """Bind every port for the stage, over the repository at root.

    Every stage reads the repository through git; which target it reads
    (working tree, staged index, revisions) is the entry point's choice.
    The judge is the stage's (`_judge_for`), configured from `environment`
    (the process environment when none is given); the judged-check budget
    is the stage's. `ci` binds github_reviews over the job's GITHUB_TOKEN,
    GITHUB_REPOSITORY and branch, read here from `environment` and never by
    the adapter; every other stage binds no_reviews. Every stage keeps
    reports in the file cache in the per-user cache directory (also read
    from `environment`); ci through the tiered store over the warehouse the
    environment configures (`_reports`). The hook
    binds process_worker to end its run at the commit-time bound; the other
    stages are unbounded and bind no worker.
    """
    bound = repository if repository is not None else GitRepository(root)
    env = os.environ if environment is None else environment
    return Container(
        stage=stage,
        repository=bound,
        reviews=reviews if reviews is not None else _reviews(stage, env),
        analyzers=(
            analyzers
            if analyzers is not None
            else {CodeLanguage.PYTHON: PythonCodeModel()}
        ),
        judge=judge if judge is not None else _judge_for(stage, env),
        complexity=(
            complexity
            if complexity is not None
            else LizardComplexity(bound=SHIPPED_LIMITS.analyzer_bound)
        ),
        duplication=(
            duplication
            if duplication is not None
            else JscpdDuplication(
                command=(str(JSCPD),), bound=SHIPPED_LIMITS.analyzer_bound
            )
        ),
        records=records if records is not None else MarkdownRecords(bound),
        parameters=replace(
            SHIPPED_PARAMETERS,
            limits=replace(SHIPPED_LIMITS, judged_budget=JUDGED_BUDGETS[stage]),
        ),
        reports=reports if reports is not None else _reports(stage, root, env),
        worker=(
            worker
            if worker is not None
            else ProcessWorker()
            if stage is Stage.HOOK
            else None
        ),
    )
