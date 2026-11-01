"""adapters/warehouse.py -- ReportStore over the adherence-ledger bucket.

ci's ledger (ARCHITECTURE.ARCH-ADHERENCE.md, Module map and Persistence),
written over the S3 protocol with boto3 under the fleet data warehouse's
invariants: one newline-terminated JSON record per key, append-only,
private, no quoted code -- each finding keeps its location and identity
and drops its offending line (`Finding.unquoted`). Every put writes the
scan key `adherence/v1/dt=YYYY-MM-DD/<repo>/<rev>-<identity>.json` under
the scan credential; only a run holding the lookup credential -- a
default-branch run, whose environment alone carries it -- also writes the
lookup key `adherence/v1/by-rev/<repo>/<rev>/<identity>.json` that `get`
reads with the scan credential. The adapter is bound to one repository
and touches no key outside that repository's prefixes. A write failure
rides on Recorded and never changes a verdict; the notice names the
failure and never a secret. A get compares the Deadline to its own clock
and bounds its request by what is left.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Protocol, cast

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from adherence.adapters.file_store import (
    MalformedReport,
    is_key_part,
    report_data,
    report_from_data,
)
from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.finding import Notice
from adherence.domain.report import Recorded, Report
from adherence.domain.target import is_object_id
from adherence.ports.report_store import StoreMiss

# --- Constants ---------------------------------------------------------------

PREFIX = "adherence/v1"
# Seconds a ledger request may take, connect and read, when no Deadline
# bounds it sooner. A put runs after the verdict, so this is its bound.
REQUEST_BOUND = 10.0
MISSING = frozenset({"NoSuchKey", "404"})

# --- Values ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LedgerCredential:
    """One S3 credential pair; the secret never prints."""

    access_key_id: str
    secret_access_key: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class LedgerSettings:
    """Where the ledger is and the credentials a run holds: `scan` always,
    `lookup` only on a default-branch run."""

    endpoint: str
    bucket: str
    region: str
    scan: LedgerCredential
    lookup: LedgerCredential | None = None


class S3Client(Protocol):
    """The two calls this adapter makes of a boto3 S3 client."""

    def put_object(
        self, *, Bucket: str, Key: str, Body: bytes, ContentType: str
    ) -> Mapping[str, object]: ...

    def get_object(self, *, Bucket: str, Key: str) -> Mapping[str, object]: ...


class _Body(Protocol):
    def read(self) -> bytes: ...


Connect = Callable[[LedgerSettings, LedgerCredential, float], S3Client]

# --- Pure helpers ------------------------------------------------------------


def scan_key(repository: str, revision: str, identity: str, kept_at: float) -> str:
    day = datetime.fromtimestamp(kept_at, UTC).strftime("%Y-%m-%d")
    return f"{PREFIX}/dt={day}/{repository}/{revision}-{identity}.json"


def lookup_key(repository: str, revision: str, identity: str) -> str:
    return f"{PREFIX}/by-rev/{repository}/{revision}/{identity}.json"


def ledger_record(report: Report, kept_at: float) -> bytes:
    """The report as the ledger keeps it: one JSON line, every finding
    unquoted, stamped with the time it was kept."""
    unquoted = replace(
        report,
        findings=tuple(f.unquoted() for f in report.findings),
        removed=tuple(f.unquoted() for f in report.removed),
    )
    document = {**report_data(unquoted), "kept_at": kept_at}
    return (json.dumps(document, separators=(",", ":")) + "\n").encode("utf-8")


def _failure(error: BotoCoreError | ClientError) -> str:
    """What went wrong, from the protocol's own error code and message."""
    if isinstance(error, ClientError):
        detail = error.response.get("Error", {})
        return f"{detail.get('Code', 'error')}: {detail.get('Message', '')}".strip()
    return str(error)


def _missing(error: BotoCoreError | ClientError) -> bool:
    if not isinstance(error, ClientError):
        return False
    return str(error.response.get("Error", {}).get("Code")) in MISSING


# --- Mechanism ---------------------------------------------------------------


def connect(
    ledger: LedgerSettings, credential: LedgerCredential, bound: float
) -> S3Client:
    """A boto3 S3 client for one credential, built when a call needs it,
    path-style, one attempt, every wait bounded, and checksums only where
    the protocol requires them (R2 refuses the newer default trailers)."""
    client = boto3.client(
        "s3",
        endpoint_url=ledger.endpoint,
        region_name=ledger.region,
        aws_access_key_id=credential.access_key_id,
        aws_secret_access_key=credential.secret_access_key,
        config=Config(
            connect_timeout=bound,
            read_timeout=bound,
            retries={"total_max_attempts": 1},
            s3={"addressing_style": "path"},
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )
    return cast(S3Client, client)


# --- Adapter -----------------------------------------------------------------


class WarehouseReportStore:
    """ReportStore over the ledger bucket, for `repository` alone."""

    def __init__(
        self,
        *,
        repository: str,
        ledger: LedgerSettings,
        clock: Callable[[], float] = time.time,
        connector: Connect = connect,
    ) -> None:
        self._repository = repository
        self._ledger = ledger
        self._clock = clock
        self._connect = connector

    def get(
        self, repository: str, revision: str, identity: str, deadline: Deadline | None
    ) -> Report | StoreMiss | TimedOut:
        now = self._clock()
        if deadline is not None and deadline.epoch_seconds <= now:
            return TimedOut("read a kept report")
        if repository != self._repository:
            return StoreMiss(self._outside(repository))
        if not (
            is_key_part(repository) and is_object_id(revision) and is_key_part(identity)
        ):
            return StoreMiss(f"no report is kept for {repository} at {revision}")
        key = lookup_key(repository, revision, identity)
        bound = REQUEST_BOUND
        if deadline is not None:
            bound = min(bound, deadline.epoch_seconds - now)
        client = self._connect(self._ledger, self._ledger.scan, bound)
        try:
            answer = client.get_object(Bucket=self._ledger.bucket, Key=key)
            raw = cast(_Body, answer["Body"]).read()
        except (BotoCoreError, ClientError) as error:
            if _missing(error):
                return StoreMiss(f"no report kept at {key}")
            if deadline is not None and deadline.epoch_seconds <= self._clock():
                return TimedOut("read a kept report")
            return StoreMiss(f"{key} cannot be read: {_failure(error)}")
        try:
            document = json.loads(raw)
            if not isinstance(document, dict):
                raise MalformedReport("the record is not a table")
            return report_from_data(document)
        except (ValueError, MalformedReport) as error:
            return StoreMiss(f"{key} cannot be read: {error}")

    def _outside(self, repository: str | None) -> str:
        return (
            f"{repository} lies outside this repository's ledger prefixes "
            f"({self._repository})"
        )

    def _write(self, credential: LedgerCredential, key: str, record: bytes) -> None:
        client = self._connect(self._ledger, credential, REQUEST_BOUND)
        client.put_object(
            Bucket=self._ledger.bucket,
            Key=key,
            Body=record,
            ContentType="application/json",
        )

    def put(self, report: Report) -> Recorded:
        if report.repository != self._repository:
            return Recorded(
                False,
                Notice(
                    "report not written to the warehouse: "
                    + self._outside(report.repository)
                ),
            )
        if (
            report.identity is None
            or not is_key_part(self._repository)
            or not is_key_part(report.revision)
        ):
            return Recorded(
                False,
                Notice(
                    "report not written to the warehouse: it names no repository, "
                    "revision or identity to key"
                ),
            )
        repository, revision = self._repository, str(report.revision)
        identity = report.identity.digest
        kept_at = self._clock()
        record = ledger_record(report, kept_at)
        try:
            self._write(
                self._ledger.scan,
                scan_key(repository, revision, identity, kept_at),
                record,
            )
            lookup = self._ledger.lookup
            if lookup is not None and is_object_id(revision):
                self._write(lookup, lookup_key(repository, revision, identity), record)
        except (BotoCoreError, ClientError) as error:
            return Recorded(
                False,
                Notice(f"report not written to the warehouse: {_failure(error)}"),
            )
        return Recorded(True)
