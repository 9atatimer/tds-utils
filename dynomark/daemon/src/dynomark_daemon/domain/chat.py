"""One chat exchange: question, grounded answer, citations."""

from dataclasses import dataclass

from dynomark_daemon.domain.bookmark import Identity
from dynomark_daemon.domain.tree import FolderPath


@dataclass(frozen=True, slots=True)
class Question:
    text: str


@dataclass(frozen=True, slots=True)
class Turn:
    """An earlier exchange: the user's text and the reply it got."""

    question: str
    answer: str


@dataclass(frozen=True, slots=True)
class Citation:
    """A reference to a ``CorpusEntry`` identity the retrieval returned."""

    identity: Identity
    title: str
    path: FolderPath


@dataclass(frozen=True, slots=True)
class Answer:
    """The grounded reply; URLs outside the corpus are ``external_urls``."""

    text: str
    citations: tuple[Citation, ...]
    external_urls: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DraftAnswer:
    """What the completion model returns before grounding is enforced."""

    text: str
    cited: tuple[Identity, ...]
    urls: tuple[str, ...]
