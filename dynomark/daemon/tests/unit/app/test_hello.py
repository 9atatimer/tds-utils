"""Transport contract, "Identity and version" (DYNOMARK.DESIGN.md): "On
mismatch, write-producing flows stop; search and chat continue only if the
extension's version is newer than the daemon's"; Goal 7 (one writer); as
contract v1 pins them (Connection lifecycle: hello, mode, the role a
connection is served with; Message table: status).
"""

import pytest

from dynomark_daemon.app.hello import Greeting, hello, owned_roots_for, status
from dynomark_daemon.domain.connection import (
    DAEMON_CONTRACT_VERSION,
    HelloMode,
    negotiate,
)
from dynomark_daemon.domain.ids import HostId, ProfileId
from dynomark_daemon.domain.job import JobState
from dynomark_daemon.domain.roles import HostRole
from dynomark_daemon.domain.tree import OwnedRoots, RootKey
from dynomark_daemon.testing.store import InMemoryCorpusStore
from dynomark_daemon.wire.base import CONTRACT_VERSION
from tests._factories import make_config, make_job, make_path

A, B = ProfileId("profile-a"), ProfileId("profile-b")
FOLLOW_UP = make_path("Follow Up")
V = DAEMON_CONTRACT_VERSION


@pytest.mark.parametrize(
    ("extension", "mode"),
    [(V, HelloMode.FULL), (V + 1, HelloMode.READ_ONLY), (V - 1, HelloMode.REFUSED)],
)
def test_negotiate_the_mode_from_the_two_versions(
    extension: int, mode: HelloMode
) -> None:
    """Given the extension's and the daemon's contract versions, When they are
    compared, Then equal is full, a newer extension read_only, an older one
    refused."""
    assert negotiate(extension, V) is mode


def _hello(
    store: InMemoryCorpusStore,
    profile: ProfileId,
    *,
    version: int = V,
    role: HostRole = HostRole.WRITER,
) -> Greeting:
    return hello(profile, version, FOLLOW_UP, make_config(role=role), store=store)


def test_hello_on_a_writer_binds_the_first_full_profile_and_serves_others_reader() -> (
    None
):
    """Given a writer daemon, When profile A completes a full hello and then B,
    Then A is served writer (and bound), B reader, and A again writer."""
    store = InMemoryCorpusStore()

    first, other, again = _hello(store, A), _hello(store, B), _hello(store, A)

    assert (first.role, other.role, again.role) == (
        HostRole.WRITER,
        HostRole.READER,
        HostRole.WRITER,
    )
    assert first.mode is HelloMode.FULL and first.host_id == HostId("mbp")


def test_hello_that_is_not_full_never_binds_the_writer_profile() -> None:
    """Given a writer daemon, When A says hello with a newer version (read_only)
    and then B with the daemon's, Then A is served reader and B is bound."""
    store = InMemoryCorpusStore()

    newer = _hello(store, A, version=V + 1)
    equal = _hello(store, B)

    assert (newer.mode, newer.role) == (HelloMode.READ_ONLY, HostRole.READER)
    assert equal.role is HostRole.WRITER


def test_hello_on_a_reader_daemon_serves_every_profile_reader() -> None:
    """Given a daemon configured reader, When any profile says hello, Then it is
    served reader (a reader host never writes)."""
    store = InMemoryCorpusStore()

    assert _hello(store, A, role=HostRole.READER).role is HostRole.READER


def test_hello_echoes_the_follow_up_folder_and_remembers_it_for_the_profile() -> None:
    """Given a Follow Up the extension resolved elsewhere, When it says hello,
    Then owned_roots.follow_up is exactly that folder, Dynomark and Graveyard
    come from Config, and the profile's roots keep it."""
    store = InMemoryCorpusStore()
    elsewhere = make_path("Inbox", "Follow Up")

    greeting = hello(A, V, elsewhere, make_config(), store=store)

    config_roots = make_config().owned_roots
    assert greeting.owned_roots == OwnedRoots(
        follow_up=elsewhere,
        dynomark=config_roots.dynomark,
        graveyard=config_roots.graveyard,
    )
    assert owned_roots_for(A, make_config(), store=store) == greeting.owned_roots
    assert owned_roots_for(B, make_config(), store=store) == config_roots
    assert greeting.owned_roots.follow_up.root is RootKey.BAR


def test_status_reports_role_host_version_models_and_queue_depth() -> None:
    """Given jobs in flight and done, When status is asked, Then it names the
    connection's role, the host, the contract version, both models from
    Config (local or not), and how many jobs are still in flight."""
    store = InMemoryCorpusStore()
    for n, state in enumerate(
        [
            JobState.QUEUED,
            JobState.ENRICHED,
            JobState.PLACED,
            JobState.FILED,
            JobState.FAILED,
        ]
    ):
        store.put_job(make_job(f"job-{n}", node_id=str(n), state=state))

    report = status(HostRole.WRITER, make_config(), store=store)

    config = make_config()
    assert (report.role, report.host_id, report.contract_version) == (
        HostRole.WRITER,
        config.host_id,
        V,
    )
    assert (report.embedding, report.completion) == (
        config.embedding_model,
        config.completion_model,
    )
    assert report.queue_depth == 3


def test_the_daemon_speaks_the_contract_version_of_its_wire_models() -> None:
    """Given the domain's contract version and the wire models', When compared,
    Then they are one number (hello and status report what the codec speaks)."""
    assert DAEMON_CONTRACT_VERSION == CONTRACT_VERSION
