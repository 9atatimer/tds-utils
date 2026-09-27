"""Identity normalization (DYNOMARK.DESIGN.md, Ubiquitous language: "Identity
-- the normalized URL. Normalized on the daemon only"; contract/v1 README,
Identity: "an absolute URL the browser can navigate to that reaches the same
resource as the raw URLs it stands for; normalization only removes
equivalent variants").

Behaviors row: A save is ingested -- its idempotency key is (NodeId,
Identity), so two spellings of one resource must yield one Identity and two
resources must never collapse into one.
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from dynomark_daemon.domain.bookmark import Identity
from dynomark_daemon.testing.strategies import http_urls


def _swap_scheme_and_host_case(url: str) -> str:
    scheme, rest = url.split("://", 1)
    cut = min((i for i in (rest.find(c) for c in "/?#") if i >= 0), default=len(rest))
    return f"{scheme.swapcase()}://{rest[:cut].swapcase()}{rest[cut:]}"


@given(http_urls())
def test_normalize_twice_equals_normalize_once(url: str) -> None:
    """Given any http(s) URL, When normalized twice, Then it equals normalizing
    once (an Identity is a fixed point: the daemon may re-normalize safely)."""
    once = Identity.from_url(url)
    assert Identity.from_url(once.value) == once


@given(http_urls())
def test_normalize_ignores_scheme_and_host_case(url: str) -> None:
    """Given a URL, When its scheme and host are spelled in another case, Then
    both spellings are one Identity (a repeat save is one job)."""
    assert Identity.from_url(_swap_scheme_and_host_case(url)) == Identity.from_url(url)


@given(http_urls())
def test_normalize_keeps_an_absolute_url_of_the_same_scheme(url: str) -> None:
    """Given a URL, When normalized, Then the identity is still an absolute URL
    of that scheme (the extension navigates to it)."""
    scheme = url.split("://", 1)[0].lower()
    assert Identity.from_url(url).value.startswith(f"{scheme}://")


@pytest.mark.parametrize(
    ("raw", "identity"),
    [
        ("HTTPS://Tokio.RS/tokio/tutorial", "https://tokio.rs/tokio/tutorial"),
        ("https://tokio.rs:443/tokio/tutorial", "https://tokio.rs/tokio/tutorial"),
        ("http://example.org:80/", "http://example.org/"),
        ("http://example.org:/a", "http://example.org/a"),
        ("https://example.org", "https://example.org/"),
        ("https://example.org/a/./b/../c", "https://example.org/a/c"),
        ("https://example.org/%7euser/%2fx", "https://example.org/~user/%2Fx"),
        ("https://example.org/a?q=%61%3d", "https://example.org/a?q=a%3D"),
    ],
)
def test_normalize_removes_equivalent_variants(raw: str, identity: str) -> None:
    """Given a raw URL spelled with a default port, case, dot segments or
    percent-encoding variants, When normalized, Then the variant is removed."""
    assert Identity.from_url(raw) == Identity(identity)


@pytest.mark.parametrize(
    "raw",
    [
        "https://example.org/Path/Is/Case-Sensitive",
        "https://example.org/a?x=1&y=2",
        "https://example.org/a?y=2&x=1",
        "https://example.org/app#/route",
        "https://example.org:8443/a",
        "https://user@example.org/a",
        "https://example.org/a%2Fb",
    ],
)
def test_normalize_keeps_what_can_name_another_resource(raw: str) -> None:
    """Given a URL whose path case, query order, fragment, port, userinfo or an
    encoded reserved character may name a different resource, When
    normalized, Then it is kept exactly (two resources never collapse)."""
    assert Identity.from_url(raw) == Identity(raw)


@given(st.sampled_from(["javascript:void(0)", "file:///etc/hosts", "about:blank"]))
def test_normalize_leaves_non_http_urls_alone_but_the_scheme_case(raw: str) -> None:
    """Given a non-http(s) URL, When normalized in another scheme case, Then only
    the scheme is lower-cased (no equivalence rules are known for it)."""
    scheme, rest = raw.split(":", 1)
    assert Identity.from_url(f"{scheme.upper()}:{rest}") == Identity(raw)
