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


@pytest.mark.parametrize(("private", "allowed"), [(False, False), (True, True)])
def test_the_composed_vetter_honours_the_private_addresses_opt_out(
    tmp_path: Path, private: bool, allowed: bool
) -> None:
    """Given ``[capture] private_addresses`` off (the default) or on, When the
    composed ports vet a loopback URL (a literal address, so no DNS), Then it
    is refused by default and allowed when opted out: the background tab is
    held to the fetch fallback's own policy (issue #410)."""
    settings = parse_settings(
        {"role": "writer", "capture": {"private_addresses": private}},
        {"XDG_STATE_HOME": str(tmp_path / "state")},
        home=tmp_path,
        hostname="mbp",
    )
    Path(settings.config.store_path).parent.mkdir(parents=True)
    ports = e2e_ports(settings, load_script({}))
    try:
        verdict = ports.vetter.vet("http://127.0.0.1:8080/admin")
    finally:
        if isinstance(ports.store, SqliteCorpusStore):
            ports.store.close()

    assert verdict.allowed is allowed
