"""The native-messaging host manifest (contract/v1/README.md, Endpoint: host
name ``tds.dynomark``; Design, Security Considerations: "the
native-messaging shim is bound to the extension's identity in the host
manifest"). Written into a temporary home directory.
"""

import json
from pathlib import Path

import pytest

from dynomark_daemon.adapters.host_manifest import (
    HOST_NAME,
    InvalidExtensionId,
    install_manifests,
    manifest_dirs,
)

pytestmark = pytest.mark.integration

EXTENSION = "abcdefghijklmnopabcdefghijklmnop"
MAC_SUPPORT = "Library/Application Support"


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        (
            "darwin",
            {
                "chrome": f"{MAC_SUPPORT}/Google/Chrome/NativeMessagingHosts",
                "chromium": f"{MAC_SUPPORT}/Chromium/NativeMessagingHosts",
            },
        ),
        (
            "linux",
            {
                "chrome": ".config/google-chrome/NativeMessagingHosts",
                "chromium": ".config/chromium/NativeMessagingHosts",
            },
        ),
    ],
)
def test_manifest_dirs_are_the_per_user_directories_of_each_browser(
    platform: str, expected: dict[str, str], tmp_path: Path
) -> None:
    """Given macOS or Linux, When the directories are asked for, Then each is the
    browser's per-user NativeMessagingHosts directory under home."""
    dirs = manifest_dirs(platform, home=tmp_path)

    assert {b: str(p.relative_to(tmp_path)) for b, p in dirs.items()} == expected


def test_install_writes_one_manifest_per_browser_bound_to_the_extension(
    tmp_path: Path,
) -> None:
    """Given a host executable and an extension id, When installed for both
    browsers, Then each directory holds tds.dynomark.json naming the host by
    absolute path, stdio, and only that extension's origin."""
    host = tmp_path / "bin" / "dynomark-host"
    host.parent.mkdir()
    host.write_text("#!/bin/sh\n")

    written = install_manifests(
        host, EXTENSION, platform="linux", home=tmp_path / "home"
    )

    assert len(written) == 2
    for path in written:
        assert path.name == f"{HOST_NAME}.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        assert document == {
            "name": "tds.dynomark",
            "description": "Dynomark: native-messaging pipe to the dynomark daemon",
            "path": str(host.resolve()),
            "type": "stdio",
            "allowed_origins": [f"chrome-extension://{EXTENSION}/"],
        }


@pytest.mark.parametrize(
    "extension_id", ["", "ABCDEFGHIJKLMNOPABCDEFGHIJKLMNOP", "abc", "q" * 32]
)
def test_install_refuses_a_malformed_extension_id(
    extension_id: str, tmp_path: Path
) -> None:
    """Given an id that is not 32 letters a-p, When installing, Then it raises
    and writes nothing (the manifest must name exactly one extension)."""
    with pytest.raises(InvalidExtensionId):
        install_manifests(
            tmp_path / "dynomark-host", extension_id, platform="linux", home=tmp_path
        )

    assert not any(tmp_path.rglob("*.json"))


def test_install_refuses_a_host_path_that_does_not_exist(tmp_path: Path) -> None:
    """Given no executable at the host path, When installing, Then it raises
    FileNotFoundError and writes nothing."""
    with pytest.raises(FileNotFoundError):
        install_manifests(
            tmp_path / "missing", EXTENSION, platform="darwin", home=tmp_path
        )

    assert not any(tmp_path.rglob("*.json"))
