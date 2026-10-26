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
from adherence.adapters.no_judge import NoJudge
from adherence.container import JSCPD, Stage, build
from adherence.domain.model import CodeLanguage
from adherence.domain.questions import Unavailable
from adherence.ports.code_model import CodeModelPort
from adherence.ports.complexity import ComplexityPort
from adherence.ports.decision import DecisionPort
from adherence.ports.duplication import DuplicationPort
from adherence.ports.records import RecordsPort
from adherence.ports.report_store import ReportStore
from adherence.ports.repository import RepositoryPort
from adherence.ports.review import ReviewPort

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
    built = build(Stage.HOOK, root=str(tmp_path), environment={**DOOR, **HOSTED})

    assert isinstance(built.judge, NoJudge)
    assert built.parameters.limits.judged_budget == 0


def test_build_stages_that_judge_ship_a_judged_budget(tmp_path: Path) -> None:
    """Given the laptop, ci and cloud stages, When each is built, Then its
    parameters carry a judged-check budget, so a judge bound there is asked."""
    for stage in (Stage.LAPTOP, Stage.CI, Stage.CLOUD):
        parameters = build(stage, root=str(tmp_path), environment={}).parameters

        assert parameters.limits.judged_budget > 0, stage
