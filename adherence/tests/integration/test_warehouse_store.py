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
    WarehouseReportStore,
)
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
    record that carries the findings' identities and no offending line."""
    recorded = _store(s3, _settings(s3)).put(REPORT)

    assert recorded.kept, recorded
    assert set(s3.ledger.objects) == {SCAN_KEY, LOOKUP_KEY}
    for raw in s3.ledger.objects.values():
        assert raw.endswith(b"\n") and raw.count(b"\n") == 1
        record = json.loads(raw)
        assert [f["identity"] for f in record["findings"]] == [
            f.identity for f in REPORT.findings
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
