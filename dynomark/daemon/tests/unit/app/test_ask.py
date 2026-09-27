"""Behaviors rows: A question is answered with citations; An out-of-corpus URL
is marked (DYNOMARK.DESIGN.md, Behaviors and Interfaces) --
``ask(question, history, *, store, embedding, completion) -> Answer``.

The daemon, "Chat": retrieve top-k entries, answer through
``CompletionPort``, keep only citations the retrieval returned, mark other
URLs ``external``.
"""

from dynomark_daemon.app.ask import ASK_CONTEXT, ask
from dynomark_daemon.domain.bookmark import Identity
from dynomark_daemon.domain.chat import Citation, DraftAnswer, Question, Turn
from dynomark_daemon.testing.completion import AnswerCall, ScriptedCompletion
from dynomark_daemon.testing.embedding import HashingEmbedding
from dynomark_daemon.testing.store import InMemoryCorpusStore
from tests._factories import make_entry, make_path, make_placement

TOKIO = "https://tokio.rs/tokio/tutorial"
RAYON = "https://docs.rs/rayon"
RUST = make_path("Dynomark", "Rust")


def _corpus() -> InMemoryCorpusStore:
    store = InMemoryCorpusStore()
    embedding = HashingEmbedding()
    for identity, title, text in (
        (TOKIO, "Tokio tutorial", "tokio cancellation select"),
        (RAYON, "Rayon", "data parallelism iterators"),
    ):
        store.put_entry(
            make_entry(
                identity,
                title=title,
                text=text,
                vector=embedding.embed(f"{title} {text}").vector,
            )
        )
    store.put_placement(make_placement(TOKIO, folder=RUST))
    return store


def test_ask_cites_the_retrieved_entries_the_completion_cites() -> None:
    """Given a corpus and a fake completion citing a retrieved identity, When a
    question is asked, Then that identity is a Citation with its title and
    filed path, and the completion saw the retrieved entries and history."""
    store = _corpus()
    completion = ScriptedCompletion(
        answer=[DraftAnswer(text="Use select!.", cited=(Identity(TOKIO),), urls=())]
    )
    history = (Turn(question="what is tokio?", answer="an async runtime"),)

    answer = ask(
        Question("how does tokio cancellation work?"),
        history,
        store=store,
        embedding=HashingEmbedding(),
        completion=completion,
    )

    assert answer.citations == (Citation(Identity(TOKIO), "Tokio tutorial", RUST),)
    (call,) = completion.calls
    assert isinstance(call, AnswerCall)
    assert call.history == history
    assert Identity(TOKIO) in {entry.identity for entry in call.context}
    assert len(call.context) <= ASK_CONTEXT


def test_ask_drops_an_identity_the_completion_invents() -> None:
    """Given a fake completion citing an identity that is in no retrieval, When
    asked, Then that one is dropped and the retrieved one is kept."""
    invented = Identity("https://made-up.example/page")
    completion = ScriptedCompletion(
        answer=[DraftAnswer(text="x", cited=(invented, Identity(RAYON)), urls=())]
    )

    answer = ask(
        Question("rayon iterators"),
        (),
        store=_corpus(),
        embedding=HashingEmbedding(),
        completion=completion,
    )

    assert [c.identity for c in answer.citations] == [Identity(RAYON)]


def test_ask_marks_a_url_outside_the_corpus_external() -> None:
    """Given the completion returns a URL not in the corpus and one that is,
    When asked, Then only the outside one is marked external."""
    outside = "https://rust-lang.github.io/async-book/"
    completion = ScriptedCompletion(
        answer=[DraftAnswer(text="x", cited=(), urls=(outside, RAYON))]
    )

    answer = ask(
        Question("tokio"),
        (),
        store=_corpus(),
        embedding=HashingEmbedding(),
        completion=completion,
    )

    assert answer.external_urls == (outside,)


def test_ask_on_an_empty_corpus_answers_without_citations() -> None:
    """Given no corpus entries, When asked, Then the completion is shown no
    context and the answer cites nothing."""
    completion = ScriptedCompletion(
        answer=[DraftAnswer(text="I have nothing on that.", cited=(), urls=())]
    )

    answer = ask(
        Question("anything?"),
        (),
        store=InMemoryCorpusStore(),
        embedding=HashingEmbedding(),
        completion=completion,
    )

    assert answer.citations == () and answer.text == "I have nothing on that."
    (call,) = completion.calls
    assert isinstance(call, AnswerCall) and call.context == ()
