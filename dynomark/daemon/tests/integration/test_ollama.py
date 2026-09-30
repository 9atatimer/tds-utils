"""Ollama behind EmbeddingPort and CompletionPort (Design, Seams: "Embedding
vendor and model / Completion vendor and model -- local (Ollama)"; model id
at the edge, recorded with embeddings and placements). Against a local fake
of the Ollama HTTP API on 127.0.0.1; a real-Ollama smoke test lives in
test_ollama_live.py and skips without one.
"""

import json
import socket

import pytest

from dynomark_daemon.adapters.ollama import (
    OllamaClient,
    OllamaCompletion,
    OllamaEmbedding,
    OllamaError,
)
from dynomark_daemon.domain.batch import Expect, OpCreateFolder, OpMove
from dynomark_daemon.domain.bookmark import Identity
from dynomark_daemon.domain.chat import Question
from dynomark_daemon.domain.config import ModelInfo
from dynomark_daemon.domain.diff import DiffAction, DiffKind
from dynomark_daemon.domain.ids import NodeId
from dynomark_daemon.domain.placement import EntryRef, admit_folder
from dynomark_daemon.domain.tree import FolderPath, RootKey, TreeOutline
from dynomark_daemon.ports.completion import CompletionError, CompletionPort
from dynomark_daemon.ports.embedding import EmbeddingError, EmbeddingPort
from tests._factories import (
    make_bookmark,
    make_capture,
    make_entry,
    make_feedback,
    make_outline,
    make_outline_folder,
    make_path,
)
from tests._fake_ollama import Script, fake_ollama

pytestmark = pytest.mark.integration

EMBED = ModelInfo(model_id="ollama:nomic-embed-text", local=True)
COMPLETE = ModelInfo(model_id="ollama:llama3.1:8b", local=True)


def _embedding(base: str) -> EmbeddingPort:
    return OllamaEmbedding(
        OllamaClient(base, timeout_s=5.0), name="nomic-embed-text", model=EMBED
    )


def _completion(base: str) -> CompletionPort:
    return OllamaCompletion(
        OllamaClient(base, timeout_s=5.0), name="llama3.1:8b", model=COMPLETE
    )


def _closed_port() -> str:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return f"http://127.0.0.1:{port}"


# --- Embedding ---


def test_embed_returns_the_vector_with_the_configured_model_id() -> None:
    """Given Ollama answering a vector, When text is embedded, Then the embedding
    is that vector named by the configured model id, and the request named
    the model and carried the text."""
    script = Script(embeddings=[[0.6, 0.8]])
    with fake_ollama(script) as base:
        embedding = _embedding(base).embed("Tokio runtime")

    assert embedding.vector == (0.6, 0.8)
    assert embedding.model_id == "ollama:nomic-embed-text"
    ((path, payload),) = script.requests
    assert path == "/api/embed"
    assert (payload["model"], payload["input"]) == ("nomic-embed-text", "Tokio runtime")


def test_embed_without_a_server_is_a_retryable_error() -> None:
    """Given nothing listening, When text is embedded, Then EmbeddingError is
    retryable (the daemon retries per RetryPolicy)."""
    with pytest.raises(EmbeddingError) as raised:
        _embedding(_closed_port()).embed("x")

    assert raised.value.retryable is True


def test_embed_of_a_missing_model_is_not_retryable() -> None:
    """Given Ollama answering 404 (model not pulled), When text is embedded, Then
    EmbeddingError is not retryable."""
    with (
        fake_ollama(Script(status=404)) as base,
        pytest.raises(EmbeddingError) as raised,
    ):
        _embedding(base).embed("x")

    assert raised.value.retryable is False


# --- Completion: enrichment ---


def test_enrich_asks_for_json_and_parses_summary_and_tags() -> None:
    """Given a JSON answer, When a capture is enriched, Then the summary and the
    normalized tags (trimmed, lower-case, unique, at most 64 characters) are
    returned; the request asked for JSON, no streaming, with the page in it."""
    answer = json.dumps(
        {"summary": "An async runtime.", "tags": [" Rust ", "rust", "ASYNC", "x" * 80]}
    )
    script = Script(responses=[answer])
    with fake_ollama(script) as base:
        enrichment = _completion(base).enrich(
            make_bookmark(), make_capture("Tokio schedules tasks")
        )

    assert enrichment.summary == "An async runtime."
    assert enrichment.tags == ("rust", "async", "x" * 64)
    ((path, payload),) = script.requests
    assert path == "/api/generate"
    assert (payload["model"], payload["format"], payload["stream"]) == (
        "llama3.1:8b",
        "json",
        False,
    )
    assert "Tokio schedules tasks" in str(payload["prompt"])


@pytest.mark.parametrize(
    "answer",
    [
        "not json at all",
        json.dumps(["a list"]),
        json.dumps({"tags": ["no summary"]}),
        json.dumps({"summary": "", "tags": []}),
        json.dumps({"summary": "ok", "tags": "not-a-list"}),
        json.dumps({"summary": "ok", "tags": [1, 2]}),
    ],
    ids=["prose", "array", "no-summary", "empty-summary", "tags-string", "tags-ints"],
)
def test_an_unparseable_enrichment_is_a_retryable_completion_error(
    answer: str,
) -> None:
    """Given a model answer that is not the JSON asked for, When enriching, Then
    CompletionError is retryable (strict parsing; the next attempt may do)."""
    with fake_ollama(Script(responses=[answer])) as base:
        with pytest.raises(CompletionError) as raised:
            _completion(base).enrich(make_bookmark(), make_capture("text"))

    assert raised.value.retryable is True


# --- Completion: placement ---


def test_choose_folder_shows_outline_neighbours_feedback_and_parses_a_path() -> None:
    """Given an outline with a locked folder, neighbours and feedback, When a
    folder is chosen, Then the prompt lists them (the lock marked) and the
    answer's names become a FolderPath under the outline's root."""
    outline = make_outline(
        make_outline_folder("Dynomark", "Rust"),
        make_outline_folder("Dynomark", "Private", locked=True),
    )
    neighbour = EntryRef(
        Identity("https://docs.rs/tokio"), "tokio docs", make_path("Dynomark", "Rust")
    )
    answer = json.dumps({"folder": ["Dynomark", "Rust", "Async"], "rationale": "tokio"})
    script = Script(responses=[answer])
    with fake_ollama(script) as base:
        choice = _completion(base).choose_folder(
            make_entry(summary="An async runtime."),
            neighbours=(neighbour,),
            outline=outline,
            feedback=(make_feedback("fb-1"),),
        )

    assert choice.folder == make_path("Dynomark", "Rust", "Async")
    assert choice.rationale == "tokio"
    prompt = str(script.requests[0][1]["prompt"])
    assert "Dynomark/Rust" in prompt and "tokio docs" in prompt
    assert "Dynomark/Private (locked)" in prompt


@pytest.mark.parametrize(
    "answer",
    [
        json.dumps({"folder": "Dynomark/Rust", "rationale": "x"}),
        json.dumps({"folder": [], "rationale": "x"}),
        json.dumps({"folder": ["Dynomark", ""], "rationale": "x"}),
        json.dumps({"rationale": "x"}),
    ],
)
def test_an_unparseable_folder_choice_is_a_retryable_completion_error(
    answer: str,
) -> None:
    """Given an answer without a list of folder names, When choosing, Then
    CompletionError is retryable."""
    with fake_ollama(Script(responses=[answer])) as base:
        with pytest.raises(CompletionError) as raised:
            _completion(base).choose_folder(
                make_entry(), neighbours=(), outline=make_outline(), feedback=()
            )

    assert raised.value.retryable is True


def test_a_folder_choice_without_the_root_is_placed_under_it() -> None:
    """Given an answer naming only the leaf path below the root, When choosing,
    Then the path is taken as relative to the Dynomark root."""
    answer = json.dumps({"folder": ["Rust"], "rationale": "x"})
    with fake_ollama(Script(responses=[answer])) as base:
        choice = _completion(base).choose_folder(
            make_entry(), neighbours=(), outline=make_outline(), feedback=()
        )

    assert choice.folder == make_path("Dynomark", "Rust")


def test_a_folder_choice_copied_from_a_prompt_line_names_that_folder() -> None:
    """Given the prompt shows folders as slash-joined lines and the model
    answers one such line as a single name, When choosing, Then the answer
    names the existing folder, not a new one titled with slashes."""
    outline = make_outline(make_outline_folder("Dynomark", "Rust"))
    answer = json.dumps({"folder": ["Dynomark/Rust"], "rationale": "x"})
    with fake_ollama(Script(responses=[answer])) as base:
        choice = _completion(base).choose_folder(
            make_entry(), neighbours=(), outline=outline, feedback=()
        )

    assert choice.folder == make_path("Dynomark", "Rust")


@pytest.mark.parametrize(
    "folder",
    [
        pytest.param(["Dynomark/Rust (locked)"], id="prompt-line"),
        pytest.param(["Dynomark", "Rust (locked)"], id="names"),
        pytest.param(["Rust  (locked)"], id="leaf-only"),
    ],
)
def test_a_locked_folder_copied_with_its_annotation_names_the_locked_folder(
    folder: list[str],
) -> None:
    """Given the prompt marks a folder "(locked)" and the model, disobeying,
    answers that folder with the mark copied, When choosing and admitting,
    Then the choice names the locked folder itself (not a new folder titled
    "Rust (locked)"), and placement's lock rule falls back to the
    neighbours' folder as designed (Placement respects a lock)."""
    outline = make_outline(
        make_outline_folder("Dynomark", "Rust", locked=True),
        make_outline_folder("Dynomark", "Python"),
    )
    answer = json.dumps({"folder": folder, "rationale": "rust"})
    script = Script(responses=[answer])
    with fake_ollama(script) as base:
        choice = _completion(base).choose_folder(
            make_entry(), neighbours=(), outline=outline, feedback=()
        )

    assert "Dynomark/Rust (locked)" in str(script.requests[0][1]["prompt"])
    assert choice.folder == make_path("Dynomark", "Rust")
    python = make_path("Dynomark", "Python")
    assert admit_folder(choice.folder, outline, [python]) == python


# --- Completion: diffs ---

BAR = FolderPath(root=RootKey.BAR, names=())
DIFF_OUTLINE = make_outline(
    make_outline_folder("Dynomark", "Rust", node_id="14"),
    make_outline_folder("Dynomark", "Rust", "Async", node_id="16", pinned=True),
    make_outline_folder("Dynomark", "Private", node_id="18", locked=True),
)
OWN_BAR = TreeOutline(
    root=BAR,
    folders=(
        make_outline_folder(node_id="1"),
        make_outline_folder("Reading", node_id="30"),
    ),
)


def test_propose_diff_shows_both_outlines_and_builds_operations() -> None:
    """Given the Dynomark outline (pinned and locked marked) and the user's own
    bar, When an audit is proposed, Then the prompt lists both, and a move
    and an add in the answer become operations built from the outlines."""
    answer = json.dumps(
        {
            "items": [
                {
                    "action": "move",
                    "folder": ["Dynomark", "Rust"],
                    "to": ["Reading", "Languages"],
                    "description": "Rust belongs with your reading",
                },
                {
                    "action": "add",
                    "folder": ["Reading", "Async"],
                    "description": "An Async folder in your bar",
                },
            ]
        }
    )
    script = Script(responses=[answer])
    with fake_ollama(script) as base:
        proposals = _completion(base).propose_diff(
            DiffKind.AUDIT, outline=DIFF_OUTLINE, own_bar=OWN_BAR
        )

    prompt = str(script.requests[0][1]["prompt"])
    assert "Dynomark/Rust/Async (pinned)" in prompt
    assert "Dynomark/Private (locked)" in prompt and "Reading" in prompt
    move, add = proposals
    assert (move.action, move.description) == (
        DiffAction.MOVE,
        "Rust belongs with your reading",
    )
    assert move.operations == (
        OpCreateFolder(index=0, parent=make_path("Reading"), title="Languages"),
        OpMove(
            index=1,
            node_id=NodeId("14"),
            to=make_path("Reading", "Languages"),
            expect=Expect(
                parent_id=NodeId("n-Dynomark"), parent_path=make_path("Dynomark")
            ),
        ),
    )
    assert add.operations == (
        OpCreateFolder(index=0, parent=make_path("Reading"), title="Async"),
    )


def test_propose_diff_reads_slash_joined_names_as_the_prompt_writes_them() -> None:
    """Given folders written as the prompt writes them (names separated by /),
    When a move names them that way, Then it is built as if the names were
    listed one by one."""
    answer = json.dumps(
        {
            "items": [
                {
                    "action": "move",
                    "folder": ["Dynomark/Rust"],
                    "to": ["Reading/Languages"],
                    "description": "x",
                }
            ]
        }
    )
    with fake_ollama(Script(responses=[answer])) as base:
        (move,) = _completion(base).propose_diff(
            DiffKind.AUDIT, outline=DIFF_OUTLINE, own_bar=OWN_BAR
        )

    assert move.operations[-1] == OpMove(
        index=1,
        node_id=NodeId("14"),
        to=make_path("Reading", "Languages"),
        expect=Expect(
            parent_id=NodeId("n-Dynomark"), parent_path=make_path("Dynomark")
        ),
    )


def test_propose_diff_reads_folders_copied_with_their_flags() -> None:
    """Given the diff prompt marks folders "(pinned)" and "(locked)", When an
    item names a folder with its marks copied, Then it is built on that
    folder (the rules then judge the pinned or locked folder), not skipped
    as naming no known folder."""
    answer = json.dumps(
        {
            "items": [
                {
                    "action": "move",
                    "folder": ["Dynomark/Rust/Async (pinned)"],
                    "to": ["Reading"],
                    "description": "x",
                },
                {
                    "action": "move",
                    "folder": ["Dynomark", "Private (pinned) (locked)"],
                    "to": ["Reading"],
                    "description": "y",
                },
            ]
        }
    )
    with fake_ollama(Script(responses=[answer])) as base:
        pinned, locked = _completion(base).propose_diff(
            DiffKind.AUDIT, outline=DIFF_OUTLINE, own_bar=OWN_BAR
        )

    moved = [
        op.node_id
        for proposal in (pinned, locked)
        for op in proposal.operations
        if isinstance(op, OpMove)
    ]
    assert moved == [NodeId("16"), NodeId("18")]


def test_propose_diff_skips_items_it_cannot_build() -> None:
    """Given items naming no known folder, a merge (rules undefined, Open
    Question 1) and a malformed one, When proposed, Then each is skipped."""
    answer = json.dumps(
        {
            "items": [
                {
                    "action": "move",
                    "folder": ["Nope"],
                    "to": ["Reading"],
                    "description": "x",
                },
                {"action": "merge", "folder": ["Dynomark", "Rust"], "description": "x"},
                {"action": "add", "folder": "Reading/New", "description": "x"},
                "not an object",
            ]
        }
    )
    with fake_ollama(Script(responses=[answer])) as base:
        proposals = _completion(base).propose_diff(
            DiffKind.REBUILD, outline=DIFF_OUTLINE, own_bar=OWN_BAR
        )

    assert proposals == ()


def test_propose_diff_without_an_item_list_is_retryable() -> None:
    """Given an answer that has no items list, When proposed, Then
    CompletionError is retryable."""
    with fake_ollama(Script(responses=[json.dumps({"items": "none"})])) as base:
        with pytest.raises(CompletionError) as raised:
            _completion(base).propose_diff(
                DiffKind.REBUILD, outline=DIFF_OUTLINE, own_bar=OWN_BAR
            )

    assert raised.value.retryable is True


# --- Completion: chat draft, model, availability ---


def test_answer_parses_text_cited_identities_and_urls() -> None:
    """Given a JSON answer, When a question is answered, Then the draft carries
    the text, the cited identities and the URLs as the model gave them (the
    ask use case enforces grounding)."""
    answer = json.dumps(
        {
            "text": "See tokio.",
            "cited": ["https://tokio.rs/"],
            "urls": ["https://x.org/"],
        }
    )
    with fake_ollama(Script(responses=[answer])) as base:
        draft = _completion(base).answer(
            Question("what is tokio?"), history=(), context=(make_entry(),)
        )

    assert draft.text == "See tokio."
    assert draft.cited == (Identity("https://tokio.rs/"),)
    assert draft.urls == ("https://x.org/",)


def test_the_ports_report_the_configured_models() -> None:
    """Given configured model ids, When the ports are asked, Then each names its
    model id and whether it is local."""
    assert _embedding("http://127.0.0.1:1").model() == EMBED
    assert _completion("http://127.0.0.1:1").model() == COMPLETE


def test_the_client_lists_installed_models() -> None:
    """Given Ollama with two models pulled, When the client lists them, Then
    both names come back (dynomark-daemon check)."""
    script = Script(models=["nomic-embed-text:latest", "llama3.1:8b"])
    with fake_ollama(script) as base:
        names = OllamaClient(base, timeout_s=5.0).installed_models()

    assert names == ["nomic-embed-text:latest", "llama3.1:8b"]


def test_the_client_without_a_server_raises_ollama_error() -> None:
    """Given nothing listening, When models are listed, Then OllamaError."""
    with pytest.raises(OllamaError):
        OllamaClient(_closed_port(), timeout_s=1.0).installed_models()
