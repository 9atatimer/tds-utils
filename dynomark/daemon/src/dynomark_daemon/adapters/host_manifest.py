"""The native-messaging host manifest for ``tds.dynomark``.

One JSON file per browser in its per-user ``NativeMessagingHosts``
directory, naming the installed ``dynomark-host`` by absolute path and
allowing exactly one extension origin (Design, Security Considerations:
the shim is bound to the extension's identity in the host manifest).
"""

import json
import re
from pathlib import Path
from typing import Final

HOST_NAME: Final = "tds.dynomark"
DESCRIPTION: Final = "Dynomark: native-messaging pipe to the dynomark daemon"
EXTENSION_ID: Final = re.compile(r"[a-p]{32}")
BROWSERS: Final = ("chrome", "chromium")
_MAC: Final = {
    "chrome": "Library/Application Support/Google/Chrome/NativeMessagingHosts",
    "chromium": "Library/Application Support/Chromium/NativeMessagingHosts",
}
_LINUX: Final = {
    "chrome": ".config/google-chrome/NativeMessagingHosts",
    "chromium": ".config/chromium/NativeMessagingHosts",
}


class InvalidExtensionId(ValueError):
    """Not a Chrome extension id (32 letters a-p)."""


def manifest_dirs(platform: str, *, home: Path) -> dict[str, Path]:
    """Each supported browser's per-user manifest directory on ``platform``
    (``sys.platform``: ``darwin`` or ``linux``)."""
    table = _MAC if platform == "darwin" else _LINUX
    return {browser: home / relative for browser, relative in table.items()}


def manifest(host: Path, extension_id: str) -> dict[str, object]:
    return {
        "name": HOST_NAME,
        "description": DESCRIPTION,
        "path": str(host.resolve()),
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{extension_id}/"],
    }


def install_manifests(
    host: Path,
    extension_id: str,
    *,
    platform: str,
    home: Path,
    browsers: tuple[str, ...] = BROWSERS,
) -> list[Path]:
    """Write ``tds.dynomark.json`` for each of ``browsers``; the paths written.

    Raises:
        InvalidExtensionId: ``extension_id`` is not an extension id.
        FileNotFoundError: no host executable at ``host``.
    """
    if EXTENSION_ID.fullmatch(extension_id) is None:
        raise InvalidExtensionId(f"{extension_id!r} is not 32 letters a-p")
    if not host.is_file():
        raise FileNotFoundError(f"no dynomark-host at {host}")
    document = json.dumps(manifest(host, extension_id), indent=2) + "\n"
    dirs = manifest_dirs(platform, home=home)
    written: list[Path] = []
    for browser in browsers:
        target = dirs[browser] / f"{HOST_NAME}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(document, encoding="utf-8")
        written.append(target)
    return written
