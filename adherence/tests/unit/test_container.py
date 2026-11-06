"""Architect behavior (testing skill): Wiring, with Swap's fake-per-port half.

The composition root builds, in every stage, with every port faked; it
takes an override for every Protocol under ports/; and every port has a
fake to pass it (ARCHITECTURE.ARCH-ADHERENCE.md, Module map: container.py).
"""

from __future__ import annotations

import importlib
import json
import pkgutil
from pathlib import Path
from typing import Protocol, get_args, get_type_hints

import pytest

import adherence.ports
from adherence.adapters.decide import DecideDecision
from adherence.adapters.fakes import (
    FakeCodeModel,
    FakeComplexity,
    FakeDecision,
    FakeDuplication,
    FakeRecords,
    FakeReportStore,
    FakeRepository,
    FakeReviews,
)
from adherence.adapters.github_reviews import GitHubReviews
from adherence.adapters.inline_worker import FakeWorker
from adherence.adapters.no_judge import NoJudge
from adherence.adapters.no_reviews import NoReviews
from adherence.container import JSCPD, Stage, build
from adherence.domain.declaration import ReviewsUnavailable, Unknown
from adherence.domain.model import CodeLanguage
from adherence.domain.questions import Availability, Unavailable
from adherence.ports.code_model import CodeModelPort
from adherence.ports.complexity import ComplexityPort
from adherence.ports.decision import DecisionPort
from adherence.ports.duplication import DuplicationPort
from adherence.ports.records import RecordsPort
from adherence.ports.report_store import ReportStore, StoreMiss
from adherence.ports.repository import RepositoryPort
from adherence.ports.review import ReviewPort
from adherence.ports.worker import WorkerPort
from tests.report_store_contract import IDENTITY, REPORT, REVISION

# Each port: the override build() takes for it, and the fake passed there
# (a port bound per language takes a mapping of fakes).
OVERRIDES: dict[type, tuple[str, object]] = {
    RepositoryPort: ("repository", FakeRepository({})),
    ReviewPort: ("reviews", FakeReviews()),
    CodeModelPort: ("analyzers", {CodeLanguage.PYTHON: FakeCodeModel()}),
    DecisionPort: ("judge", FakeDecision(Unavailable("faked"))),
    ComplexityPort: ("complexity", FakeComplexity()),
    DuplicationPort: ("duplication", FakeDuplication()),
    RecordsPort: ("records", FakeRecords({})),
    ReportStore: ("reports", FakeReportStore()),
    WorkerPort: ("worker", FakeWorker()),
}


def _ports() -> set[type]:
    found: set[type] = set()
    for module in pkgutil.iter_modules(adherence.ports.__path__):
        loaded = importlib.import_module(f"adherence.ports.{module.name}")
        for value in vars(loaded).values():
            if (
                isinstance(value, type)
                and Protocol in value.__mro__[1:]
                and value.__module__ == loaded.__name__
            ):
                found.add(value)
    return found


def _mentions(hint: object, port: type) -> bool:
    """Whether a type hint names the port, at any depth (Mapping[K, Port])."""
    return hint is port or any(_mentions(arg, port) for arg in get_args(hint))


def test_every_port_has_a_fake_and_an_override() -> None:
    """Given every Protocol under ports/, When the fakes and the composition
    root's overrides are listed, Then each port has a fake and an override."""
    ports = _ports()
    hints = get_type_hints(build)

    assert ports, "no ports found; the discovery is broken"
    assert ports == set(OVERRIDES), "a port without a fake, or a fake without a port"
    for port, (name, _fake) in OVERRIDES.items():
        assert name in hints and _mentions(hints[name], port), (
            f"build() takes no override for {port.__name__}"
        )


def test_build_with_every_port_faked_binds_the_fakes(tmp_path: Path) -> None:
    """Given a fake for every port, When the composition root is built for each
    stage, Then every port it binds is the fake passed in."""
    overrides = dict(OVERRIDES.values())

    for stage in Stage:
        built = build(stage, root=str(tmp_path), **overrides)
        for name, fake in overrides.items():
            assert getattr(built, name) is fake, (stage, name)


def test_build_binds_an_analyzer_for_every_measured_language(tmp_path: Path) -> None:
    """Given no analyzer override, When the composition root is built, Then
    every language the suite measures has an analyzer, and TypeScript and
    JavaScript share one, so an import from one to the other resolves."""
    built = build(Stage.LAPTOP, root=str(tmp_path))

    assert set(built.analyzers) == set(CodeLanguage)
    assert (
        built.analyzers[CodeLanguage.TYPESCRIPT]
        is built.analyzers[CodeLanguage.JAVASCRIPT]
    )


def test_jscpd_runs_from_the_node_package_that_pins_it() -> None:
    """jscpd is spawned from the one node package CI installs, the one
    whose manifest and lock pin it (architecture, Security mitigations)."""
    package = JSCPD.parents[2]
    manifest = json.loads((package / "package.json").read_text())
    lock = json.loads((package / "package-lock.json").read_text())

    assert manifest["dependencies"]["jscpd"] == "5.4.1"
    assert lock["packages"]["node_modules/jscpd"]["integrity"]
    assert lock["packages"][""]["dependencies"]["dependency-cruiser"]


def test_build_binds_github_reviews_in_ci_and_no_reviews_elsewhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Given the job's GITHUB_TOKEN and GITHUB_REPOSITORY, When the composition
    root is built, Then `ci` binds github_reviews over them and every other
    stage binds no_reviews, which answers Unknown."""
    monkeypatch.setenv("GITHUB_TOKEN", "job-token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "example-org/example")
    # A push event sets GITHUB_BASE_REF empty and names the branch pushed.
    monkeypatch.setenv("GITHUB_BASE_REF", "")
    monkeypatch.setenv("GITHUB_REF_NAME", "master")

    for stage in Stage:
        # Injected: the hook's git adapter would spawn git to find its base.
        repository = FakeRepository({})
        reviews = build(stage, root=str(tmp_path), repository=repository).reviews
        if stage is Stage.CI:
            assert isinstance(reviews, GitHubReviews), stage
            answer = reviews.approvals("not-an-object-id", None)
            assert isinstance(answer, ReviewsUnavailable)
            assert "object id" in answer.reason, (
                "the token, repository or branch is lost"
            )
        else:
            assert isinstance(reviews, NoReviews), stage
            assert isinstance(reviews.approvals("a" * 40, None), Unknown)


def test_build_in_ci_without_the_token_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Given a `ci` job with no GITHUB_TOKEN, When a landing's approvals are
    asked for, Then the answer is unavailable naming the token, so the walk
    counts no approval rather than letting the landed declaration stand."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_REPOSITORY", "example-org/example")

    answer = build(Stage.CI, root=str(tmp_path)).reviews.approvals("a" * 40, None)

    assert isinstance(answer, ReviewsUnavailable)
    assert "GITHUB_TOKEN" in answer.reason


def test_build_in_ci_without_a_branch_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Given a `ci` job that names no branch, When a landing's approvals are
    asked for, Then the answer is unavailable naming the variables, since
    no pull request can be told to have landed on the judged branch."""
    monkeypatch.setenv("GITHUB_TOKEN", "job-token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "example-org/example")
    monkeypatch.delenv("GITHUB_BASE_REF", raising=False)
    monkeypatch.delenv("GITHUB_REF_NAME", raising=False)

    answer = build(Stage.CI, root=str(tmp_path)).reviews.approvals("a" * 40, None)

    assert isinstance(answer, ReviewsUnavailable)
    assert "GITHUB_BASE_REF" in answer.reason


# --- The judge, bound by stage (ARCHITECTURE.ARCH-ADHERENCE.md, Where it runs) --

DOOR = {"DECIDE_URL": "http://127.0.0.1:8787"}
HOSTED = {
    "DECIDE_GATEWAY_URL": "https://gateway.example/v1/account/gateway",
    "DECIDE_GATEWAY_TOKEN": "a-token",
}


def _judge(stage: Stage, environment: dict[str, str], root: Path) -> object:
    return build(stage, root=str(root), environment=environment).judge


def test_build_laptop_asks_through_the_door_and_holds_no_credential(
    tmp_path: Path,
) -> None:
    """Given the door's address, and beside it a hosted configuration, When
    the laptop stage is built, Then the judge is the decide client through
    the door alone: the hosted token never reaches it. With no address the
    laptop has no judge, and says which variable would give it one."""
    judge = _judge(Stage.LAPTOP, {**DOOR, **HOSTED}, tmp_path)
    alone = _judge(Stage.LAPTOP, HOSTED, tmp_path)

    assert isinstance(judge, DecideDecision)
    assert judge.configuration == {
        "DECIDE_BACKEND": "systemone",
        "DECIDE_URL": DOOR["DECIDE_URL"],
    }
    assert isinstance(alone, NoJudge)
    assert "DECIDE_URL" in alone.reason


def test_build_ci_and_cloud_ask_the_hosted_judge_when_configured(
    tmp_path: Path,
) -> None:
    """Given the hosted gateway and its token, When the ci and cloud stages
    are built, Then each judge is the decide client on the hosted gateway
    with that token; without both, each has no judge, naming what is
    missing (cloud provisional, architecture Q3)."""
    for stage in (Stage.CI, Stage.CLOUD):
        judge = _judge(stage, HOSTED, tmp_path)
        missing = _judge(stage, {"DECIDE_GATEWAY_URL": "x"}, tmp_path)

        assert isinstance(judge, DecideDecision), stage
        assert judge.configuration == {"DECIDE_BACKEND": "cf-ai-gateway", **HOSTED}
        assert isinstance(missing, NoJudge), stage
        assert "DECIDE_GATEWAY_TOKEN" in missing.reason


def test_build_hook_never_asks_a_judge(tmp_path: Path) -> None:
    """Given every judge configured, When the hook stage is built, Then it
    has no judge and a judged-check budget of none."""
    built = build(
        Stage.HOOK,
        root=str(tmp_path),
        environment={**DOOR, **HOSTED},
        repository=FakeRepository({}),
    )

    assert isinstance(built.judge, NoJudge)
    assert built.parameters.limits.judged_budget == 0


def test_build_binds_a_judge_whose_availability_is_the_stages(tmp_path: Path) -> None:
    """Given a stage with its judge configured and one without, When each is
    built, Then the bound judge says it is available only where one is
    configured: the availability a report's identity carries comes from
    the composition root, never from the domain reading the environment
    (Issue#627)."""
    configured = build(Stage.LAPTOP, root=str(tmp_path), environment=DOOR)
    unconfigured = build(Stage.LAPTOP, root=str(tmp_path), environment={})
    hook = build(
        Stage.HOOK,
        root=str(tmp_path),
        environment={**DOOR, **HOSTED},
        repository=FakeRepository({}),
    )

    assert configured.judge.availability() is Availability.AVAILABLE
    assert unconfigured.judge.availability() is Availability.UNAVAILABLE
    assert hook.judge.availability() is Availability.UNAVAILABLE


def test_build_stages_that_judge_ship_a_judged_budget(tmp_path: Path) -> None:
    """Given the laptop, ci and cloud stages, When each is built, Then its
    parameters carry a judged-check budget, so a judge bound there is asked."""
    for stage in (Stage.LAPTOP, Stage.CI, Stage.CLOUD):
        parameters = build(stage, root=str(tmp_path), environment={}).parameters

        assert parameters.limits.judged_budget > 0, stage


# --- The report store, bound by stage (ARCHITECTURE.ARCH-ADHERENCE.md, Where
# it runs) --


def test_build_ci_keeps_reports_in_the_file_cache_until_the_warehouse_exists(
    tmp_path: Path,
) -> None:
    """Given a ci job before the warehouse is provisioned, When a report is
    put and then asked for as a base, Then it is kept in the per-user file
    cache, the notice says it is kept there only and names tds-internal
    Issue#276, and no base is read back from the runner's cache."""
    cache = tmp_path / "cache"
    reports = build(
        Stage.CI,
        root=str(tmp_path / "repo"),
        environment={"XDG_CACHE_HOME": str(cache)},
        repository=FakeRepository({}),
    ).reports

    recorded = reports.put(REPORT)
    answer = reports.get("example", REVISION, IDENTITY.digest, None)

    assert list((cache / "adherence" / "scan" / "example").iterdir())
    assert not recorded.kept
    assert recorded.notice is not None
    assert "file cache only" in recorded.notice.message
    assert "tds-internal Issue#276" in recorded.notice.message
    assert "ADHERENCE_LEDGER_ENDPOINT" in recorded.notice.message
    assert isinstance(answer, StoreMiss)


def test_build_ci_with_part_of_the_warehouse_configuration_binds_none(
    tmp_path: Path,
) -> None:
    """Given a ci job whose environment carries the ledger's credential but
    not its endpoint or bucket, When a report is put, Then no warehouse is
    bound: the report is kept in the file cache only and the notice names
    what is missing and never the secret."""
    environment = {
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "ADHERENCE_LEDGER_ACCESS_KEY_ID": "key-id",
        "ADHERENCE_LEDGER_SECRET_ACCESS_KEY": "the-secret",
    }
    reports = build(
        Stage.CI, root=str(tmp_path / "repo"), environment=environment
    ).reports

    recorded = reports.put(REPORT)

    assert not recorded.kept
    assert recorded.notice is not None
    assert "file cache only" in recorded.notice.message
    assert "ADHERENCE_LEDGER_ENDPOINT" in recorded.notice.message
    assert "ADHERENCE_LEDGER_BUCKET" in recorded.notice.message
    assert "the-secret" not in recorded.notice.message


def test_build_other_stages_keep_and_read_the_file_cache(tmp_path: Path) -> None:
    """Given the laptop, hook and cloud stages, When a report is put and asked
    for, Then each keeps it in the file cache and reads it back."""
    for stage in (Stage.LAPTOP, Stage.HOOK, Stage.CLOUD):
        cache = tmp_path / stage.value
        reports = build(
            stage,
            root=str(tmp_path / "repo"),
            environment={"XDG_CACHE_HOME": str(cache)},
            repository=FakeRepository({}),
        ).reports

        assert reports.put(REPORT).kept, stage
        assert reports.get("example", REVISION, IDENTITY.digest, None) == REPORT, stage


@pytest.mark.parametrize(
    "endpoint",
    ["r2.example.com", "https://", "ftp://r2.example.com", "http://r2.example.com"],
)
def test_build_ci_with_an_endpoint_that_names_no_https_host_binds_none(
    tmp_path: Path, endpoint: str
) -> None:
    """Given a ci job whose ledger endpoint is not an `https://` URL with a
    host (boto3 refuses a scheme-less one with a ValueError), When a report
    is put, Then no warehouse is bound: the report is kept in the file cache
    only and the notice names ADHERENCE_LEDGER_ENDPOINT and never the
    secret."""
    environment = {
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "ADHERENCE_LEDGER_ENDPOINT": endpoint,
        "ADHERENCE_LEDGER_BUCKET": "adherence-ledger",
        "ADHERENCE_LEDGER_ACCESS_KEY_ID": "key-id",
        "ADHERENCE_LEDGER_SECRET_ACCESS_KEY": "the-secret",
    }
    reports = build(
        Stage.CI,
        root=str(tmp_path / "repo"),
        environment=environment,
        repository=FakeRepository({}),
    ).reports

    recorded = reports.put(REPORT)

    assert not recorded.kept
    assert recorded.notice is not None
    assert "file cache only" in recorded.notice.message
    assert "ADHERENCE_LEDGER_ENDPOINT" in recorded.notice.message
    assert "the-secret" not in recorded.notice.message


# --- The repository's name, by stage (per-repository key isolation) --


def test_build_ci_names_the_repository_owner_and_name_from_the_job(
    tmp_path: Path,
) -> None:
    """Given a ci job whose environment carries GITHUB_REPOSITORY, When the
    composition root is built over a checkout of any directory name, Then
    the repository is named `owner/repo`, so two same-named repositories
    of two owners never share a ledger prefix."""
    container = build(
        Stage.CI,
        root=str(tmp_path / "example"),
        environment={"GITHUB_REPOSITORY": "someone/example"},
        repository=FakeRepository({}),
    )

    assert container.name == "someone/example"


def test_build_names_the_repository_by_its_directory_elsewhere(
    tmp_path: Path,
) -> None:
    """Given GITHUB_REPOSITORY in the environment, When the laptop, hook and
    cloud stages are built, and when ci is built without it, Then each names
    the repository by its checkout's directory."""
    named = {"GITHUB_REPOSITORY": "someone/elsewhere"}
    for stage in (Stage.LAPTOP, Stage.HOOK, Stage.CLOUD):
        container = build(
            stage,
            root=str(tmp_path / "example"),
            environment=named,
            repository=FakeRepository({}),
        )
        assert container.name == "example", stage

    unnamed = build(
        Stage.CI,
        root=str(tmp_path / "example"),
        environment={},
        repository=FakeRepository({}),
    )
    assert unnamed.name == "example"
