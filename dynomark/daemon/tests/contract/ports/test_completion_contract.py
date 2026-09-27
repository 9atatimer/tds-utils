"""The scripted CompletionPort fake: answers exactly what a test scripts.

Design: Goal 3, "with a fake CompletionPort returning a fixed answer, two
calls give one placement"; Behaviors "A failed enrichment is retried, then
parked" (a completion that errors RetryPolicy.attempts times), "An entry
is placed" (a fake completion echoing a folder), "A question is answered
with citations" (a fake completion citing identities).
"""

import pytest

from dynomark_daemon.domain.bookmark import Enrichment, Identity
from dynomark_daemon.domain.chat import DraftAnswer, Question
from dynomark_daemon.domain.diff import DiffAction, DiffKind, DiffProposal
from dynomark_daemon.domain.placement import FolderChoice
from dynomark_daemon.domain.tree import TreeOutline
from dynomark_daemon.ports.completion import CompletionError, CompletionPort
from dynomark_daemon.testing.completion import (
    ChooseFolderCall,
    EnrichCall,
    ScriptedCompletion,
    ScriptExhausted,
)
from tests._factories import make_bookmark, make_capture, make_entry, make_path

pytestmark = pytest.mark.contract

EMPTY = TreeOutline(root=make_path("Dynomark"), folders=())
RUST = FolderChoice(folder=make_path("Dynomark", "Rust"), rationale="neighbours")


def test_scripted_completion_is_a_completion_port() -> None:
    """Given a ScriptedCompletion, When used where a CompletionPort is expected,
    Then it type-checks and reports its model as local."""
    port: CompletionPort = ScriptedCompletion()

    assert port.model().local


def test_enrich_returns_scripted_answers_in_order() -> None:
    """Given two scripted enrichments, When enrich is called twice, Then they come
    back in order and each call is recorded with its inputs."""
    first = Enrichment(summary="one", tags=("a",))
    second = Enrichment(summary="two", tags=())
    fake = ScriptedCompletion(enrich=[first, second])
    bookmark, capture = make_bookmark(), make_capture("text")

    answers = [fake.enrich(bookmark, capture), fake.enrich(bookmark, capture)]

    assert answers == [first, second]
    assert fake.calls == [EnrichCall(bookmark, capture)] * 2


def test_enrich_raises_a_scripted_error_then_answers() -> None:
    """Given a script of an error then an answer, When enrich is called twice,
    Then the first call raises that error and the second answers."""
    error = CompletionError("model loading", retryable=True)
    answer = Enrichment(summary="ok", tags=())
    fake = ScriptedCompletion(enrich=[error, answer])

    with pytest.raises(CompletionError) as raised:
        fake.enrich(make_bookmark(), make_capture())

    assert raised.value is error
    assert fake.enrich(make_bookmark(), make_capture()) == answer


def test_choose_folder_with_a_repeated_script_answers_identically() -> None:
    """Given a script echoing one folder, When choose_folder is called twice with
    the same inputs, Then both answers are that folder (Goal 3's fixed answer)."""
    fake = ScriptedCompletion(choose_folder=[RUST, RUST])
    entry = make_entry()

    answers = [
        fake.choose_folder(entry, neighbours=(), outline=EMPTY, feedback=())
        for _ in range(2)
    ]

    assert answers == [RUST, RUST]
    assert fake.calls[0] == ChooseFolderCall(entry, (), EMPTY, ())


def test_answer_and_propose_diff_return_their_scripts() -> None:
    """Given scripted chat and diff answers, When asked, Then each returns its own
    script (methods do not share a queue)."""
    draft = DraftAnswer(text="see", cited=(Identity("https://a"),), urls=())
    proposal = DiffProposal(action=DiffAction.ADD, description="add", operations=())
    fake = ScriptedCompletion(answer=[draft], propose_diff=[(proposal,)])

    assert fake.propose_diff(DiffKind.AUDIT, outline=EMPTY, own_bar=EMPTY) == (
        proposal,
    )
    assert fake.answer(Question("why?"), history=(), context=()) == draft


def test_unscripted_call_raises_script_exhausted() -> None:
    """Given no script for enrich, When enrich is called, Then ScriptExhausted
    names the method (an unplanned model call fails the test loudly)."""
    fake = ScriptedCompletion()

    with pytest.raises(ScriptExhausted, match="enrich"):
        fake.enrich(make_bookmark(), make_capture())
