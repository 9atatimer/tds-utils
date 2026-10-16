"""One chat exchange: question, grounded answer, citations."""

import re
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from typing import Final

from dynomark_daemon.domain.bookmark import Identity, is_fetchable
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


# --- Grounding (Goal 5; The daemon, "Chat") ---

MAX_ANSWER_TEXT: Final = 65_536
"""An ``Answer``'s text, in code points (contract v2 ``Answer``)."""
MAX_CITATIONS: Final = 50
MAX_EXTERNAL_URLS: Final = 50
MAX_URL: Final = 65_536
"""A ``Url``'s longest form, in code points."""


_URL_IN_TEXT: Final = re.compile(r"https?://[^\s<>\"'`]+", re.IGNORECASE)
_TRAILING: Final = ".,;:!?"
_CLOSERS: Final = {")": "(", "]": "[", "}": "{"}


def _unique[T](items: Iterable[T]) -> list[T]:
    return list(dict.fromkeys(items))


def _trimmed(url: str) -> str:
    """``url`` without what ends the sentence or the link around it: trailing
    punctuation, and a closing bracket the url never opened."""
    while url:
        last = url[-1]
        if last in _TRAILING:
            url = url[:-1]
        elif last in _CLOSERS and url.count(last) > url.count(_CLOSERS[last]):
            url = url[:-1]
        else:
            return url
    return url


def urls_in_text(text: str) -> tuple[str, ...]:
    """Every http(s) URL written in ``text``, in order, once each."""
    found = (_trimmed(m.group(0)) for m in _URL_IN_TEXT.finditer(text))
    return tuple(_unique(url for url in found if "://" in url))


def mentioned_urls(draft: DraftAnswer) -> tuple[str, ...]:
    """The URLs a draft mentions: those the model listed, then any more its
    text names (Goal 5 marks every out-of-corpus URL in the answer)."""
    return tuple(_unique([*draft.urls, *urls_in_text(draft.text)]))


def ground(
    draft: DraftAnswer,
    retrieved: Sequence[Citation],
    *,
    in_corpus: Collection[Identity],
) -> Answer:
    """The answer the extension may trust: a ``Citation`` for each retrieved
    entry the draft cites or mentions (by any url variant), invented
    identities dropped, and each mentioned http(s) URL -- listed by the model
    or written in its text -- no corpus entry has marked external.
    ``in_corpus`` holds the mentioned identities the corpus has. Capped to the
    contract's sizes."""
    by_identity = {citation.identity: citation for citation in retrieved}
    named = [Identity.from_url(i.value) for i in draft.cited]
    mentioned = [
        (url, Identity.from_url(url))
        for url in mentioned_urls(draft)
        if is_fetchable(url) and len(url) <= MAX_URL
    ]
    citations = _unique(
        by_identity[identity]
        for identity in [*named, *(identity for _, identity in mentioned)]
        if identity in by_identity
    )
    external = _unique(
        url
        for url, identity in mentioned
        if identity not in by_identity and identity not in in_corpus
    )
    return Answer(
        text=draft.text[:MAX_ANSWER_TEXT],
        citations=tuple(citations[:MAX_CITATIONS]),
        external_urls=tuple(external[:MAX_EXTERNAL_URLS]),
    )
