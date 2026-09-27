"""The integration e2e's daemon entry point (dynomark/e2e): the production
composition -- SQLite store, fetch, socket, job loop -- with only the models
replaced by the ``testing`` fakes, answering from a script the e2e writes.

It is test support, not a production option: ``dynomark-daemon`` and its
config file cannot select a fake model. These tests pin what the e2e relies
on: the script is read into the scripted completion in order, a bad script
is refused by name, and the composed ports are the real store and fetch
with the fake models.
"""

from pathlib import Path

import pytest

from dynomark_daemon.adapters.fetch import FetchContentSource
from dynomark_daemon.adapters.sqlite_store import SqliteCorpusStore
from dynomark_daemon.domain.batch import OpCreateFolder
from dynomark_daemon.domain.bookmark import Identity
from dynomark_daemon.domain.chat import Question
from dynomark_daemon.domain.diff import DiffAction, DiffKind
from dynomark_daemon.settings import SCHEMA, parse_settings
from dynomark_daemon.testing.completion import ScriptedCompletion, ScriptExhausted
from dynomark_daemon.testing.e2e import ScriptError, e2e_ports, load_script
from dynomark_daemon.testing.embedding import HashingEmbedding
from tests._factories import make_bookmark, make_capture, make_outline, make_path

URL = "http://127.0.0.1:4321/tokio"
SCRIPT: dict[str, object] = {
    "enrich": [{"summary": "An async runtime.", "tags": ["rust"]}],
    "choose_folder": [
        {
            "folder": {"root": "bar", "names": ["Dynomark", "Rust"]},
            "rationale": "rust pages live here",
        }
    ],
    "answer": [{"text": "Read the tutorial.", "cited": [URL], "urls": []}],
    "propose_diff": [
        [
            {
                "action": "add",
                "description": "Add a Reading folder",
                "operations": [
                    {
                        "op": "create_folder",
                        "index": 0,
                        "parent": {"root": "bar", "names": ["Dynomark"]},
                        "title": "Reading",
                    }
                ],
            }
        ]
    ],
}


def test_load_script_answers_each_method_in_the_scripted_order() -> None:
    """Given a script with one answer per method, When it is loaded, Then the
    completion answers each call with the scripted domain value, then fails
    loudly when a script runs out."""
    completion = load_script(SCRIPT)
    bookmark = make_bookmark(url=URL)

    assert isinstance(completion, ScriptedCompletion)
    enrichment = completion.enrich(bookmark, make_capture())
    assert (enrichment.summary, enrichment.tags) == ("An async runtime.", ("rust",))
    with pytest.raises(ScriptExhausted):
        completion.enrich(bookmark, make_capture())
    answer = completion.answer(Question("how?"), history=(), context=())
    assert answer.cited == (Identity(URL),)
    (proposal,) = completion.propose_diff(
        DiffKind.REBUILD, outline=make_outline(), own_bar=make_outline()
    )
    assert proposal.action is DiffAction.ADD
    assert proposal.operations == (
        OpCreateFolder(index=0, parent=make_path("Dynomark"), title="Reading"),
    )


def test_load_script_refuses_an_unknown_method_by_name() -> None:
    """Given a script naming a method no completion has, When it is loaded,
    Then it is refused with an error that names the key."""
    with pytest.raises(ScriptError, match="summarize"):
        load_script({"summarize": []})


def test_e2e_ports_are_the_production_store_and_fetch_with_fake_models(
    tmp_path: Path,
) -> None:
    """Given settings, When the e2e ports are composed, Then the store is the
    SQLite store at the configured path, the fetch is the real one, and only
    the models are the testing fakes."""
    settings = parse_settings(
        {"role": "writer", "host_id": "mbp"},
        {"XDG_STATE_HOME": str(tmp_path / "state")},
        home=tmp_path,
        hostname="mbp",
    )
    Path(settings.config.store_path).parent.mkdir(parents=True)
    ports = e2e_ports(settings, load_script({}))
    store = ports.store
    try:
        assert isinstance(store, SqliteCorpusStore)
        assert isinstance(ports.content, FetchContentSource)
        assert isinstance(ports.embedding, HashingEmbedding)
        assert isinstance(ports.completion, ScriptedCompletion)
        assert Path(settings.config.store_path).exists()
    finally:
        if isinstance(store, SqliteCorpusStore):
            store.close()


def test_no_config_key_selects_a_fake_model() -> None:
    """Given the daemon's config schema, When its keys are read, Then none
    selects a model vendor or a fake: fakes are reachable only through the
    test-support entry point."""
    assert SCHEMA["models"] == frozenset({"embedding", "completion", "timeout_s"})
