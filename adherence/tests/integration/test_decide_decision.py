"""The decide DecisionPort adapter: the shared contract over the real
`bin/decide` client, run as a subprocess against a stand-in SystemOne
server on the loopback (tests/decide_stub.py), plus what only this adapter
does -- a label-only answer is uncalibrated, a schema past decide's
per-record limit is split -- and the real-model run, marked integration
and skipped unless a judge is configured. Skipped, never faked, without
node.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from adherence.adapters.decide import DecideDecision
from adherence.domain.questions import TWO_JOBS, Decision, Schema
from adherence.ports.decision import DecisionPort
from tests.decide_stub import LABEL, StubServer, stub_server
from tests.decision_contract import SCHEMA, STATE, DecisionContract

DECIDE = Path(__file__).resolve().parents[3] / "bin" / "decide"
COMMAND = (str(DECIDE), "run", "--model", "clef", "--tool", "adherence")
NODE_ABSENT = shutil.which("node") is None
needs_node = pytest.mark.skipif(NODE_ABSENT, reason="node runs bin/decide")
# A judge the real-model run may ask: the hosted gateway with its token, or
# a SystemOne server (the door, a local arena).
HOSTED = ("DECIDE_GATEWAY_URL", "DECIDE_GATEWAY_TOKEN")
CONFIGURED = all(os.environ.get(k) for k in HOSTED) or bool(
    os.environ.get("DECIDE_URL")
)
# The discard port on the loopback: nothing listens there.
NOWHERE = "http://127.0.0.1:9"


def _through(url: str) -> DecideDecision:
    return DecideDecision(
        command=COMMAND,
        configuration={"DECIDE_BACKEND": "systemone", "DECIDE_URL": url},
    )


@pytest.fixture
def stub() -> Iterator[StubServer]:
    with stub_server() as server:
        yield server


@needs_node
class TestDecideDecision(DecisionContract):
    @pytest.fixture(autouse=True)
    def _serve(self, stub: StubServer) -> None:
        self.stub = stub

    def port(self) -> DecisionPort:
        return _through(self.stub.url)

    def unreachable(self) -> DecisionPort:
        self.stub.mode = "402"
        return _through(self.stub.url)


@needs_node
def test_decide_sends_one_record_naming_the_model_with_the_unit_as_state(
    stub: StubServer,
) -> None:
    """Given a schema, When the decide adapter asks, Then the server receives
    one request naming the pinned model, the unit's text inside the state
    and every question under its key."""
    answer = _through(stub.url).decide(STATE, SCHEMA, None)

    assert isinstance(answer, Decision), answer
    (body,) = stub.received
    assert body["model"] == "clef"
    assert body["state"]["text"] == STATE.text  # type: ignore[index]
    assert set(body["questions"]) == set(SCHEMA.questions)  # type: ignore[arg-type]


@needs_node
def test_decide_label_only_answer_is_uncalibrated(stub: StubServer) -> None:
    """Given a server answering each yes/no with a bare label, When the
    adapter asks, Then those questions are marked uncalibrated, so no
    threshold is ever met on them."""
    stub.mode = LABEL

    answer = _through(stub.url).decide(STATE, SCHEMA, None)

    assert isinstance(answer, Decision), answer
    assert answer.uncalibrated == frozenset({"two_jobs.1"})


@needs_node
def test_decide_schema_past_the_record_limit_is_split_and_answered_whole(
    stub: StubServer,
) -> None:
    """Given a schema of seventy questions, past decide's sixty-four per
    record, When the adapter asks, Then it sends two records and every
    question is answered."""
    schema = Schema({f"two_jobs.{n}": TWO_JOBS for n in range(1, 71)})

    answer = _through(stub.url).decide(STATE, schema, None)

    assert isinstance(answer, Decision), answer
    assert set(answer.probabilities) == set(schema.questions)
    assert [len(b["questions"]) for b in stub.received] == [64, 6]  # type: ignore[arg-type]


@needs_node
def test_decide_with_no_client_to_run_is_unavailable() -> None:
    """Given a decide command that does not exist, When the adapter asks,
    Then the answer is unavailable and names the client."""
    port = DecideDecision(
        command=("/nonexistent/adherence-decide", "run"),
        configuration={"DECIDE_BACKEND": "systemone", "DECIDE_URL": NOWHERE},
    )

    answer = port.decide(STATE, SCHEMA, None)

    assert not isinstance(answer, Decision)
    assert "decide" in getattr(answer, "reason", "")


def test_decide_refuses_configuration_that_is_not_the_clients_own() -> None:
    """Given configuration naming a variable outside decide's own (DECIDE_*),
    When the adapter is built, Then it is refused: nothing else reaches the
    client's environment."""
    with pytest.raises(ValueError, match="HOME"):
        DecideDecision(command=COMMAND, configuration={"HOME": "/tmp"})


def _real() -> DecideDecision:
    if all(os.environ.get(k) for k in HOSTED):
        return DecideDecision(
            command=COMMAND,
            configuration={
                "DECIDE_BACKEND": "cf-ai-gateway",
                **{k: os.environ[k] for k in HOSTED},
            },
        )
    return _through(os.environ["DECIDE_URL"])


@pytest.mark.integration
@needs_node
@pytest.mark.skipif(not CONFIGURED, reason="no judge configured (DECIDE_* unset)")
class TestDecideRealModel(DecisionContract):
    """The contract against the real model, on demand: it spends against the
    judge's budget and needs its credential, so it never runs unconfigured."""

    def port(self) -> DecisionPort:
        return _real()

    def unreachable(self) -> DecisionPort:
        return _through(NOWHERE)
