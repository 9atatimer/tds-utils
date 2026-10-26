"""The file ReportStore adapter: the shared contract over a real directory,
then what only the file cache can show -- its default is a per-user cache
directory outside the checkout, a cache inside the repository is refused,
and a document it cannot read is a miss (ARCHITECTURE.ARCH-ADHERENCE.md,
Module map: adapters/file_store.py)."""

from __future__ import annotations

import os
from pathlib import Path

from adherence.adapters.file_store import FileReportStore, default_store_dir
from adherence.ports.report_store import ReportStore, StoreMiss
from tests.report_store_contract import (
    IDENTITY,
    NOW,
    REPORT,
    REVISION,
    ReportStoreContract,
)

CHECKOUT = Path(__file__).resolve().parents[3]


class TestFileReportStore(ReportStoreContract):
    def store_with(self, tmp_path: Path, *, now: float = NOW) -> ReportStore:
        return FileReportStore(
            tmp_path / "cache", root=tmp_path / "repo", clock=lambda: now
        )


def test_the_default_cache_is_a_per_user_directory_outside_the_checkout() -> None:
    """Given this machine's environment, When the default cache directory is
    resolved, Then it lies outside the checkout, under the per-user cache."""
    default = default_store_dir(os.environ, Path.home()).resolve()

    assert not default.is_relative_to(CHECKOUT), default
    assert default.name == "adherence"


def test_the_default_follows_xdg_cache_home_only_when_absolute(tmp_path: Path) -> None:
    """Given XDG_CACHE_HOME set to an absolute path, and then to a relative
    one, When the default is resolved, Then the first is used and the second
    falls back to ~/.cache."""
    home = tmp_path / "home"

    assert default_store_dir({"XDG_CACHE_HOME": str(tmp_path)}, home) == (
        tmp_path / "adherence"
    )
    assert default_store_dir({"XDG_CACHE_HOME": "rel"}, home) == (
        home / ".cache" / "adherence"
    )


def test_a_cache_inside_the_repository_keeps_nothing(tmp_path: Path) -> None:
    """Given a cache directory inside the repository it measures, When a
    report is put and got, Then nothing is kept or read, and the notice
    says why."""
    store = FileReportStore(tmp_path / "repo" / ".cache", root=tmp_path / "repo")

    recorded = store.put(REPORT)

    assert not recorded.kept
    assert recorded.notice is not None and "inside" in recorded.notice.message
    assert isinstance(store.get("example", REVISION, IDENTITY.digest, None), StoreMiss)
    assert not (tmp_path / "repo").exists()


def test_a_kept_document_that_is_not_a_report_is_a_miss(tmp_path: Path) -> None:
    """Given a lookup key whose document is not a report, When it is got,
    Then the answer is a miss naming the document."""
    store = FileReportStore(tmp_path / "cache", root=tmp_path / "repo")
    store.put(REPORT)
    kept = next((tmp_path / "cache" / "by-rev").rglob("*.json"))
    kept.write_text('{"format": 1, "ran": ["Not a check"]}')

    answer = store.get("example", REVISION, IDENTITY.digest, None)

    assert isinstance(answer, StoreMiss) and str(kept) in answer.reason
