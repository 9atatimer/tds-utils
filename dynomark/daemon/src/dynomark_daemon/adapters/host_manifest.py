"""The native-messaging host manifest for ``tds.dynomark``.

One JSON file per browser in its per-user ``NativeMessagingHosts``
directory, naming the installed ``dynomark-host`` by absolute path and
allowing exactly one extension (Design, Security Considerations: the shim
is bound to the extension's identity in the host manifest). Chrome and
Chromium name it by origin (``allowed_origins``, a 32-letter id); Firefox
by its gecko id (``allowed_extensions``: an address-like id or a braced
uuid). An id has the form of one family only, so it decides which
browsers a manifest is written for when none is named.
"""

import json
import re
from pathlib import Path
from typing import Final

HOST_NAME: Final = "tds.dynomark"
DESCRIPTION: Final = "Dynomark: native-messaging pipe to the dynomark daemon"
EXTENSION_ID: Final = re.compile(r"[a-p]{32}")
GECKO_ID: Final = re.compile(
    r"[A-Za-z0-9._-]*@[A-Za-z0-9._-]+"
    r"|\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}"
)
GECKO_ID_MAX: Final = 80
"""The longest gecko id addons.mozilla.org accepts."""
BROWSERS: Final = ("chrome", "chromium", "firefox")
_MAC: Final = {
    "chrome": "Library/Application Support/Google/Chrome/NativeMessagingHosts",
    "chromium": "Library/Application Support/Chromium/NativeMessagingHosts",
    "firefox": "Library/Application Support/Mozilla/NativeMessagingHosts",
}
_LINUX: Final = {
    "chrome": ".config/google-chrome/NativeMessagingHosts",
    "chromium": ".config/chromium/NativeMessagingHosts",
    "firefox": ".mozilla/native-messaging-hosts",
}


class InvalidExtensionId(ValueError):
    """Not an extension id of the browsers named (Chrome: 32 letters a-p;
    Firefox: a gecko id)."""


# --- Predicates ---


def is_firefox(browser: str) -> bool:
    return browser == "firefox"


def fits(browser: str, extension_id: str) -> bool:
    """True when ``extension_id`` has the form ``browser``'s extension ids take."""
    if is_firefox(browser):
        return (
            len(extension_id) <= GECKO_ID_MAX
            and GECKO_ID.fullmatch(extension_id) is not None
        )
    return EXTENSION_ID.fullmatch(extension_id) is not None


# --- Pure helpers ---


def manifest_dirs(platform: str, *, home: Path) -> dict[str, Path]:
    """Each supported browser's per-user manifest directory on ``platform``
    (``sys.platform``: ``darwin`` or ``linux``)."""
    table = _MAC if platform == "darwin" else _LINUX
    return {browser: home / relative for browser, relative in table.items()}


def manifest(host: Path, extension_id: str, *, browser: str) -> dict[str, object]:
    """The manifest ``browser`` reads, allowing only ``extension_id``."""
    allowed: dict[str, object] = (
        {"allowed_extensions": [extension_id]}
        if is_firefox(browser)
        else {"allowed_origins": [f"chrome-extension://{extension_id}/"]}
    )
    return {
        "name": HOST_NAME,
        "description": DESCRIPTION,
        "path": str(host.resolve()),
        "type": "stdio",
        **allowed,
    }


def _targets(extension_id: str, browsers: tuple[str, ...] | None) -> tuple[str, ...]:
    """The browsers to write for: those named, or every one the id fits."""
    named = BROWSERS if browsers is None else browsers
    misfits = [b for b in named if not fits(b, extension_id)]
    targets = tuple(b for b in named if fits(b, extension_id))
    if not targets or (browsers is not None and misfits):
        wanted = ", ".join(misfits or named)
        raise InvalidExtensionId(
            f"{extension_id!r} is not an extension id for {wanted} "
            "(Chrome, Chromium: 32 letters a-p; Firefox: a gecko id such as "
            "name@domain or a braced uuid)"
        )
    return targets


# --- Effectful ---


def install_manifests(
    host: Path,
    extension_id: str,
    *,
    platform: str,
    home: Path,
    browsers: tuple[str, ...] | None = None,
) -> list[Path]:
    """Write ``tds.dynomark.json`` for each of ``browsers`` (default: every
    browser ``extension_id`` fits); the paths written.

    Raises:
        InvalidExtensionId: ``extension_id`` is not an extension id of a
            named browser, or of any browser when none is named.
        FileNotFoundError: no host executable at ``host``.
    """
    targets = _targets(extension_id, browsers)
    if not host.is_file():
        raise FileNotFoundError(f"no dynomark-host at {host}")
    dirs = manifest_dirs(platform, home=home)
    written: list[Path] = []
    for browser in targets:
        document = manifest(host, extension_id, browser=browser)
        target = dirs[browser] / f"{HOST_NAME}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        written.append(target)
    return written
