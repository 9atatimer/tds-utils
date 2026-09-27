"""Grounding a chat answer (DYNOMARK.DESIGN.md, Goal 5: "an Answer cites
CorpusEntry identities that the retrieval step returned; an identity the
completion invents is dropped; a URL outside the corpus is marked
external"). Contract v1 ``Answer``: at most 50 citations and 50 external
urls, text at most 65,536 code points.
"""

from hypothesis import given
from hypothesis import strategies as st

from dynomark_daemon.domain.bookmark import Identity
from dynomark_daemon.domain.chat import (
    MAX_ANSWER_TEXT,
    MAX_CITATIONS,
    MAX_EXTERNAL_URLS,
    Citation,
    DraftAnswer,
    ground,
)
from tests._factories import make_path

TOKIO = Citation(Identity("https://tokio.rs/"), "Tokio", make_path("Dynomark", "Rust"))
ASYNC_BOOK = Citation(
    Identity("https://rust-lang.github.io/async-book/"),
    "Async book",
    make_path("Dynomark", "Rust"),
)


def _draft(
    *, cited: tuple[str, ...] = (), urls: tuple[str, ...] = (), text: str = "t"
) -> DraftAnswer:
    return DraftAnswer(text=text, cited=tuple(Identity(c) for c in cited), urls=urls)


def test_ground_keeps_each_retrieved_identity_the_draft_cites() -> None:
    """Given a draft citing both retrieved entries, When grounded, Then each is a
    Citation with its title and path, in the draft's order."""
    draft = _draft(cited=(ASYNC_BOOK.identity.value, TOKIO.identity.value))

    answer = ground(draft, (TOKIO, ASYNC_BOOK), in_corpus=frozenset())

    assert answer.citations == (ASYNC_BOOK, TOKIO)
    assert answer.text == "t"


def test_ground_drops_a_cited_identity_the_retrieval_did_not_return() -> None:
    """Given a draft citing a retrieved entry and an invented identity, When
    grounded, Then only the retrieved one is a Citation and the invented one
    is not reported anywhere."""
    draft = _draft(cited=(TOKIO.identity.value, "https://invented.example/"))

    answer = ground(draft, (TOKIO,), in_corpus=frozenset())

    assert answer.citations == (TOKIO,)
    assert answer.external_urls == ()


def test_ground_marks_a_url_outside_the_corpus_external() -> None:
    """Given a draft mentioning a URL no corpus entry has, When grounded, Then
    the answer lists it in external_urls."""
    draft = _draft(urls=("https://doc.rust-lang.org/book/",))

    answer = ground(draft, (TOKIO,), in_corpus=frozenset())

    assert answer.external_urls == ("https://doc.rust-lang.org/book/",)


def test_ground_neither_cites_nor_marks_a_corpus_url_that_was_not_retrieved() -> None:
    """Given a draft mentioning a corpus URL the retrieval did not return, When
    grounded, Then it is neither a Citation nor external."""
    other = "https://docs.rs/tokio"
    draft = _draft(urls=(other,))

    answer = ground(draft, (TOKIO,), in_corpus=frozenset({Identity(other)}))

    assert answer.citations == () and answer.external_urls == ()


def test_ground_cites_a_retrieved_page_the_draft_mentions_by_a_url_variant() -> None:
    """Given a draft naming a retrieved entry by a raw url variant, When
    grounded, Then that entry is a Citation (the daemon normalizes), once."""
    draft = _draft(cited=("HTTPS://Tokio.RS:443/",), urls=("https://tokio.rs",))

    answer = ground(draft, (TOKIO,), in_corpus=frozenset())

    assert answer.citations == (TOKIO,) and answer.external_urls == ()


def test_ground_never_marks_a_non_http_url_external() -> None:
    """Given a draft mentioning javascript: and file: URLs, When grounded, Then
    neither is offered to the extension to open."""
    draft = _draft(urls=("javascript:alert(1)", "file:///etc/passwd"))

    answer = ground(draft, (), in_corpus=frozenset())

    assert answer.external_urls == ()


@given(
    cited=st.lists(st.integers(0, 80), max_size=120),
    urls=st.lists(st.integers(0, 80), max_size=120),
    extra=st.integers(0, 70_000),
)
def test_ground_always_fits_the_contract_caps(
    cited: list[int], urls: list[int], extra: int
) -> None:
    """Given any draft, When grounded, Then the answer has at most 50 unique
    citations, at most 50 unique external urls, and text within the cap."""
    retrieved = tuple(
        Citation(Identity(f"https://e.example/{i}"), f"t{i}", make_path("Dynomark"))
        for i in range(80)
    )
    draft = _draft(
        cited=tuple(f"https://e.example/{i}" for i in cited),
        urls=tuple(f"https://x.example/{i}" for i in urls),
        text="x" * extra,
    )

    answer = ground(draft, retrieved, in_corpus=frozenset())

    assert len(answer.citations) <= MAX_CITATIONS
    assert len(set(answer.citations)) == len(answer.citations)
    assert len(answer.external_urls) <= MAX_EXTERNAL_URLS
    assert len(set(answer.external_urls)) == len(answer.external_urls)
    assert len(answer.text) <= MAX_ANSWER_TEXT
