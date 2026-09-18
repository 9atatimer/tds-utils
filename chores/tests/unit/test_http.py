"""The HTTP transport seam: a malformed URL is a transport error, and the
reachability probe answers False rather than raising.
"""

from __future__ import annotations

import pytest


def test_probe_treats_a_malformed_url_as_unreachable() -> None:
    from chores.adapters.http import probe

    assert probe("https://host:bad-port", timeout_sec=0.01) is False
    assert probe("not a url", timeout_sec=0.01) is False


@pytest.mark.parametrize("url", ["https://host:bad-port/v1", "not a url"])
def test_a_malformed_url_is_a_transport_error_not_a_crash(url: str) -> None:
    from chores.adapters.http import TransportError, UrllibTransport

    with pytest.raises(TransportError, match="malformed url"):
        UrllibTransport().post_json(url, headers={}, body={}, timeout_sec=0.01)
