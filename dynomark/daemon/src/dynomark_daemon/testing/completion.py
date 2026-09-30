"""A scripted ``CompletionPort``: each method answers from its own script.

A script is a sequence of answers or ``CompletionError``s consumed in
order; an error is raised when its turn comes. Every call is recorded in
``calls`` with its inputs. Calling a method whose script is used up raises
``ScriptExhausted``, so an unplanned model call fails the test loudly.
"""

from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from dynomark_daemon.domain.bookmark import Bookmark, Capture, CorpusEntry, Enrichment
from dynomark_daemon.domain.chat import DraftAnswer, Question, Turn
from dynomark_daemon.domain.config import ModelInfo
from dynomark_daemon.domain.diff import DiffKind, DiffProposal
from dynomark_daemon.domain.placement import EntryRef, FolderChoice, MoveFeedback
from dynomark_daemon.domain.tree import TreeOutline
from dynomark_daemon.ports.completion import CompletionError


class ScriptExhausted(AssertionError):
    """A method was called more times than its script has answers."""


@dataclass(frozen=True, slots=True)
class EnrichCall:
    bookmark: Bookmark
    capture: Capture


@dataclass(frozen=True, slots=True)
class ChooseFolderCall:
    entry: CorpusEntry
    neighbours: tuple[EntryRef, ...]
    outline: TreeOutline
    feedback: tuple[MoveFeedback, ...]


@dataclass(frozen=True, slots=True)
class AnswerCall:
    question: Question
    history: tuple[Turn, ...]
    context: tuple[CorpusEntry, ...]


@dataclass(frozen=True, slots=True)
class ProposeDiffCall:
    kind: DiffKind
    outline: TreeOutline
    own_bar: TreeOutline


CompletionCall = EnrichCall | ChooseFolderCall | AnswerCall | ProposeDiffCall


class _Script[T]:
    def __init__(self, method: str, steps: Iterable[T | CompletionError]) -> None:
        self._method = method
        self._steps: deque[T | CompletionError] = deque(steps)

    def next(self) -> T:
        if not self._steps:
            raise ScriptExhausted(f"no scripted answer left for {self._method}")
        step = self._steps.popleft()
        if isinstance(step, CompletionError):
            raise step
        return step


class ScriptedCompletion:
    def __init__(
        self,
        *,
        enrich: Sequence[Enrichment | CompletionError] = (),
        choose_folder: Sequence[FolderChoice | CompletionError] = (),
        answer: Sequence[DraftAnswer | CompletionError] = (),
        propose_diff: Sequence[tuple[DiffProposal, ...] | CompletionError] = (),
        model_id: str = "fake:scripted",
    ) -> None:
        self._model = ModelInfo(model_id=model_id, local=True)
        self._enrich = _Script("enrich", enrich)
        self._choose_folder = _Script("choose_folder", choose_folder)
        self._answer = _Script("answer", answer)
        self._propose_diff = _Script("propose_diff", propose_diff)
        self.calls: list[CompletionCall] = []

    def model(self) -> ModelInfo:
        return self._model

    def enrich(self, bookmark: Bookmark, capture: Capture) -> Enrichment:
        self.calls.append(EnrichCall(bookmark, capture))
        return self._enrich.next()

    def choose_folder(
        self,
        entry: CorpusEntry,
        *,
        neighbours: Sequence[EntryRef],
        outline: TreeOutline,
        feedback: Sequence[MoveFeedback],
    ) -> FolderChoice:
        self.calls.append(
            ChooseFolderCall(entry, tuple(neighbours), outline, tuple(feedback))
        )
        return self._choose_folder.next()

    def answer(
        self,
        question: Question,
        *,
        history: Sequence[Turn],
        context: Sequence[CorpusEntry],
    ) -> DraftAnswer:
        self.calls.append(AnswerCall(question, tuple(history), tuple(context)))
        return self._answer.next()

    def propose_diff(
        self, kind: DiffKind, *, outline: TreeOutline, own_bar: TreeOutline
    ) -> tuple[DiffProposal, ...]:
        self.calls.append(ProposeDiffCall(kind, outline, own_bar))
        return self._propose_diff.next()
