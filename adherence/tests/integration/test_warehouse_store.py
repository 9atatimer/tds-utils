"""The warehouse ReportStore adapter over the S3 protocol, against a local
fake that verifies every request's signature (tests/s3_fake.py): the
shared contract on a default-branch run, then what only the warehouse can
show -- the record carries no quoted code and is one NDJSON line, and a
request signed with the wrong secret is refused and said so
(ARCHITECTURE.ARCH-ADHERENCE.md, Module map: adapters/warehouse.py;
Persistence; Security mitigations).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from adherence.adapters.warehouse import (
    LedgerCredential,
    LedgerSettings,
    S3Client,
    WarehouseReportStore,
)
from adherence.container import Stage, build
from adherence.domain.report import Report
from adherence.ports.report_store import ReportStore, StoreMiss
from tests.report_store_contract import (
    IDENTITY,
    NOW,
    REPORT,
    REVISION,
    ReportStoreContract,
)
from tests.s3_fake import Credential, Grant, SigningS3

BUCKET = "adherence-ledger"
REGION = "auto"
SCAN = LedgerCredential("scan-key-id", "scan-secret")
LOOKUP = LedgerCredential("lookup-key-id", "lookup-secret")
DAY = datetime.fromtimestamp(NOW, UTC).strftime("%Y-%m-%d")
SCAN_KEY = f"adherence/v1/dt={DAY}/example/{REVISION}-{IDENTITY.digest}.json"
LOOKUP_KEY = f"adherence/v1/by-rev/example/{REVISION}/{IDENTITY.digest}.json"
# The infra module's scoping, per repository: the scan credential writes the
# scan prefix and reads the lookup prefix; the lookup credential, held only
# by default-branch runs, writes the lookup prefix.
GRANTS = {
    SCAN.access_key_id: Credential(
        SCAN.secret_access_key,
        (
            Grant("PUT", "adherence/v1/dt=*/example/*"),
            Grant("GET", "adherence/v1/by-rev/example/*"),
        ),
    ),
    LOOKUP.access_key_id: Credential(
        LOOKUP.secret_access_key, (Grant("PUT", "adherence/v1/by-rev/example/*"),)
    ),
}


def _settings(
    s3: SigningS3,
    *,
    scan: LedgerCredential = SCAN,
    lookup: LedgerCredential | None = LOOKUP,
) -> LedgerSettings:
    return LedgerSettings(
        endpoint=s3.endpoint, bucket=BUCKET, region=REGION, scan=scan, lookup=lookup
    )


def _store(s3: SigningS3, settings: LedgerSettings) -> WarehouseReportStore:
    return WarehouseReportStore(
        repository="example", ledger=settings, clock=lambda: NOW
    )


def _today() -> str:
    """The scan partition of a report the composition root keeps now: it
    binds the real clock."""
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _unquoted(report: Report) -> Report:
    """The report as the ledger promises to keep it: every finding's
    location and identity, no offending line."""
    return replace(
        report,
        findings=tuple(f.unquoted() for f in report.findings),
        removed=tuple(f.unquoted() for f in report.removed),
    )


@pytest.fixture
def s3() -> Iterator[SigningS3]:
    with SigningS3(bucket=BUCKET, region=REGION, credentials=GRANTS) as server:
        yield server


class TestWarehouseReportStore(ReportStoreContract):
    @pytest.fixture(autouse=True)
    def _serve(self, s3: SigningS3) -> None:
        self.s3 = s3

    def store_with(self, tmp_path: Path, *, now: float = NOW) -> ReportStore:
        return WarehouseReportStore(
            repository="example", ledger=_settings(self.s3), clock=lambda: now
        )

    def kept(self, report: Report) -> Report:
        return _unquoted(report)


def test_the_fake_refuses_an_unsigned_request(s3: SigningS3) -> None:
    """Given the signature-verifying fake, When a request carries no
    signature, Then it is refused and nothing is written."""
    request = urllib.request.Request(
        f"{s3.endpoint}/{BUCKET}/{SCAN_KEY}", data=b"{}\n", method="PUT"
    )

    with pytest.raises(urllib.error.HTTPError) as refused:
        urllib.request.urlopen(request, timeout=5)

    assert refused.value.code == 403
    assert s3.ledger.objects == {}


def test_a_default_branch_run_writes_both_keys_as_unquoted_ndjson(
    s3: SigningS3,
) -> None:
    """Given a default-branch run's credentials, When a report is put, Then
    the scan key and the lookup key each hold one newline-terminated JSON
    record that carries what the findings' identities read (the whole
    offending line's digest) and no offending line."""
    recorded = _store(s3, _settings(s3)).put(REPORT)

    assert recorded.kept, recorded
    assert set(s3.ledger.objects) == {SCAN_KEY, LOOKUP_KEY}
    for raw in s3.ledger.objects.values():
        assert raw.endswith(b"\n") and raw.count(b"\n") == 1
        record = json.loads(raw)
        assert [f["evidence"]["digest"] for f in record["findings"]] == [
            f.unquoted().evidence.digest for f in REPORT.findings
        ]
        assert [f["evidence"]["text"] for f in record["findings"]] == [
            "" for _ in REPORT.findings
        ]
        assert REPORT.findings[0].evidence.text.encode() not in raw


def test_a_wrong_secret_is_refused_and_the_report_is_not_kept(
    s3: SigningS3,
) -> None:
    """Given a scan credential whose secret is wrong, When a report is put
    and a base is got, Then the fake refuses each signature, the put is not
    kept and its notice says why without the secret, and the get is a miss."""
    wrong = LedgerCredential(SCAN.access_key_id, "not-the-secret")
    store = _store(s3, _settings(s3, scan=wrong, lookup=None))

    recorded = store.put(REPORT)
    answer = store.get("example", REVISION, IDENTITY.digest, None)

    assert not recorded.kept
    assert recorded.notice is not None
    assert "SignatureDoesNotMatch" in recorded.notice.message
    assert "not-the-secret" not in recorded.notice.message
    assert isinstance(answer, StoreMiss)
    assert s3.ledger.objects == {}
    assert len(s3.ledger.refused) == 2


def test_a_pull_request_run_writes_the_scan_key_alone(s3: SigningS3) -> None:
    """Given a run holding the scan credential and no lookup credential (a
    pull request's), When a report is put and then asked for, Then only the
    scan key is written, nothing is refused, and no base is read back."""
    store = _store(s3, _settings(s3, lookup=None))

    recorded = store.put(REPORT)

    assert recorded.kept, recorded
    assert set(s3.ledger.objects) == {SCAN_KEY}
    assert s3.ledger.refused == []
    assert isinstance(store.get("example", REVISION, IDENTITY.digest, None), StoreMiss)


def test_another_repositorys_keys_are_never_read_or_written(s3: SigningS3) -> None:
    """Given a store bound to one repository, When a report of another
    repository is put and that repository's base is asked for, Then neither
    is attempted -- the fake sees no request -- the put is not kept and says
    the report lies outside this repository's prefixes, and the get is a
    miss."""
    store = _store(s3, _settings(s3))
    other = replace(REPORT, repository="neighbour")

    recorded = store.put(other)
    answer = store.get("neighbour", REVISION, IDENTITY.digest, None)

    assert not recorded.kept
    assert recorded.notice is not None
    assert "outside" in recorded.notice.message
    assert isinstance(answer, StoreMiss)
    assert "outside" in answer.reason
    assert s3.ledger.objects == {}
    assert s3.ledger.refused == []


def test_build_ci_binds_the_warehouse_when_its_configuration_is_present(
    s3: SigningS3, tmp_path: Path
) -> None:
    """Given a ci job whose environment carries the ledger's endpoint,
    bucket, scan credential and lookup credential, When a report is put and
    its base asked for, Then the warehouse holds the scan and lookup keys,
    the report is kept, and the base is read back from the warehouse."""
    environment = {
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "ADHERENCE_LEDGER_ENDPOINT": s3.endpoint,
        "ADHERENCE_LEDGER_BUCKET": BUCKET,
        "ADHERENCE_LEDGER_ACCESS_KEY_ID": SCAN.access_key_id,
        "ADHERENCE_LEDGER_SECRET_ACCESS_KEY": SCAN.secret_access_key,
        "ADHERENCE_LEDGER_LOOKUP_ACCESS_KEY_ID": LOOKUP.access_key_id,
        "ADHERENCE_LEDGER_LOOKUP_SECRET_ACCESS_KEY": LOOKUP.secret_access_key,
    }
    reports = build(
        Stage.CI, root=str(tmp_path / "example"), environment=environment
    ).reports

    recorded = reports.put(REPORT)
    answer = reports.get("example", REVISION, IDENTITY.digest, None)

    assert recorded.kept, recorded
    assert {k.split("/")[2] for k in s3.ledger.objects} == {f"dt={_today()}", "by-rev"}
    assert answer == _unquoted(REPORT)


def _invalid_endpoint(
    ledger: LedgerSettings, credential: LedgerCredential, bound: float
) -> S3Client:
    """A connector as boto3 behaves on a scheme-less endpoint."""
    raise ValueError(f"Invalid endpoint: {ledger.endpoint}")


def test_an_endpoint_boto3_refuses_is_a_miss_and_an_unkept_report() -> None:
    """Given a ledger whose endpoint boto3 refuses with a ValueError while
    building the client, When a base is got and a report is put, Then the
    get is a miss and the put is not kept, with a notice naming the
    failure and never the secret: a write failure rides on Recorded and
    never ends the run."""
    settings = LedgerSettings(
        endpoint="r2.example.com",
        bucket=BUCKET,
        region=REGION,
        scan=SCAN,
        lookup=LOOKUP,
    )
    store = WarehouseReportStore(
        repository="example",
        ledger=settings,
        clock=lambda: NOW,
        connector=_invalid_endpoint,
    )

    answer = store.get("example", REVISION, IDENTITY.digest, None)
    recorded = store.put(REPORT)

    assert isinstance(answer, StoreMiss)
    assert "Invalid endpoint" in answer.reason
    assert not recorded.kept
    assert recorded.notice is not None
    assert "Invalid endpoint" in recorded.notice.message
    assert SCAN.secret_access_key not in recorded.notice.message


OWNED = "someone/example"
OWNED_GRANTS = {
    SCAN.access_key_id: Credential(
        SCAN.secret_access_key,
        (
            Grant("PUT", f"adherence/v1/dt=*/{OWNED}/*"),
            Grant("GET", f"adherence/v1/by-rev/{OWNED}/*"),
        ),
    ),
    LOOKUP.access_key_id: Credential(
        LOOKUP.secret_access_key, (Grant("PUT", f"adherence/v1/by-rev/{OWNED}/*"),)
    ),
}


def test_an_owner_and_name_key_two_segments_of_their_own() -> None:
    """Given a store bound to `someone/example`, When its report is put and
    got back, Then the scan and lookup keys hold the owner and the name as
    two segments, under grants scoped to that owner's repository alone."""
    with SigningS3(bucket=BUCKET, region=REGION, credentials=OWNED_GRANTS) as s3:
        store = WarehouseReportStore(
            repository=OWNED, ledger=_settings(s3), clock=lambda: NOW
        )
        owned = replace(REPORT, repository=OWNED)

        recorded = store.put(owned)
        answer = store.get(OWNED, REVISION, IDENTITY.digest, None)

        assert recorded.kept, recorded
        assert set(s3.ledger.objects) == {
            f"adherence/v1/dt={DAY}/{OWNED}/{REVISION}-{IDENTITY.digest}.json",
            f"adherence/v1/by-rev/{OWNED}/{REVISION}/{IDENTITY.digest}.json",
        }
        assert answer == _unquoted(owned)


@pytest.mark.parametrize("name", ["a/b/c", "someone/..", "/example", "someone/"])
def test_a_name_that_is_not_one_or_two_key_parts_is_never_keyed(
    s3: SigningS3, name: str
) -> None:
    """Given a store bound to a name that is not `repo` or `owner/repo` of
    plain key parts, When its report is put and its base got, Then nothing
    is requested: the put is not kept and the get is a miss."""
    store = WarehouseReportStore(
        repository=name, ledger=_settings(s3), clock=lambda: NOW
    )

    recorded = store.put(replace(REPORT, repository=name))
    answer = store.get(name, REVISION, IDENTITY.digest, None)

    assert not recorded.kept
    assert isinstance(answer, StoreMiss)
    assert s3.ledger.objects == {}
    assert s3.ledger.refused == []


def test_build_ci_keys_the_warehouse_by_the_jobs_owner_and_name(
    tmp_path: Path,
) -> None:
    """Given a ci job whose environment carries the ledger and
    GITHUB_REPOSITORY, When the bound store puts a report of that
    repository, Then the warehouse keys it under `<owner>/<repo>`."""
    with SigningS3(bucket=BUCKET, region=REGION, credentials=OWNED_GRANTS) as s3:
        environment = {
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
            "GITHUB_REPOSITORY": OWNED,
            "ADHERENCE_LEDGER_ENDPOINT": s3.endpoint,
            "ADHERENCE_LEDGER_BUCKET": BUCKET,
            "ADHERENCE_LEDGER_ACCESS_KEY_ID": SCAN.access_key_id,
            "ADHERENCE_LEDGER_SECRET_ACCESS_KEY": SCAN.secret_access_key,
        }
        container = build(
            Stage.CI, root=str(tmp_path / "example"), environment=environment
        )

        recorded = container.reports.put(replace(REPORT, repository=container.name))

        assert recorded.kept, recorded
        (key,) = s3.ledger.objects
        assert key.startswith(f"adherence/v1/dt={_today()}/{OWNED}/")
