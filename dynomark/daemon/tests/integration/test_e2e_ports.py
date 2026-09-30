"""The integration e2e's composed ports (dynomark/e2e): the production store
and fetch with only the models faked. It opens a real SQLite file under a
temp directory, so it is integration-tier (pyproject: "a temp sqlite file").
"""

from pathlib import Path

import pytest

from dynomark_daemon.adapters.fetch import FetchContentSource
from dynomark_daemon.adapters.sqlite_store import SqliteCorpusStore
from dynomark_daemon.settings import parse_settings
from dynomark_daemon.testing.completion import ScriptedCompletion
from dynomark_daemon.testing.e2e import e2e_ports, load_script
from dynomark_daemon.testing.embedding import HashingEmbedding

pytestmark = pytest.mark.integration


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
