"""Readable-text extraction inside the fetch adapter (Design, Key Decisions:
"Extraction -- inside the ContentSourcePort adapters"). Standard-library
``html.parser`` only: scripts, styles, navigation, headers and footers are
dropped; an ``article`` is preferred, then ``main``, then the whole body.
"""

import pytest

from dynomark_daemon.adapters.readable import MAX_TEXT, readable

ARTICLE = """<html><head><title>T &amp; U</title><script>var s = "secret";</script>
<style>.x{}</style></head><body><header>Header menu</header><nav>Nav link</nav>
<main><p>Main preamble.</p><article><h1>Heading</h1><p>First <em>line</em>.<br>
Second line.</p><script>inline()</script></article></main>
<footer>Footer text</footer></body></html>"""


def test_readable_prefers_the_article_and_drops_page_chrome() -> None:
    """Given a page with header, nav, main, article, scripts and a footer, When
    extracted, Then the text is the article's, block by block, and the title is
    the page title with entities decoded."""
    page = readable(ARTICLE)

    assert page.title == "T & U"
    assert page.text == "Heading\nFirst line.\nSecond line."


def test_readable_falls_back_to_main_then_body() -> None:
    """Given a page with main and no article, and one with neither, When
    extracted, Then the main's text, and then the body's text without its
    footer, are returned; whitespace runs collapse."""
    main = readable(
        "<body><nav>n</nav><div>outside</div><main><p>a   b\n c</p></main></body>"
    )
    body = readable("<body><div>one</div><div>two</div><footer>f</footer></body>")

    assert main.text == "a b c"
    assert body.text == "one\ntwo"
    assert main.title is None


def test_readable_never_leaks_script_or_style_text() -> None:
    """Given scripts, styles, noscript and template content anywhere, When
    extracted, Then none of their text appears."""
    page = readable(
        "<body><p>kept</p><script>a</script><style>b</style>"
        "<noscript>c</noscript><template>d</template></body>"
    )

    assert page.text == "kept"


def test_readable_survives_unbalanced_markup() -> None:
    """Given stray end tags and an unclosed element, When extracted, Then the
    visible text is still returned."""
    page = readable("<body></nav></article><p>still here<div>and here</body>")

    assert page.text == "still here\nand here"


def test_readable_caps_the_text_at_the_capture_limit() -> None:
    """Given a page whose text exceeds Capture.text's cap, When extracted, Then
    the text is cut to MAX_TEXT code points (contract v1, Size limits)."""
    page = readable("<p>" + "é" * (MAX_TEXT + 10) + "</p>")

    assert len(page.text) == MAX_TEXT == 1_048_576


@pytest.mark.parametrize(
    ("html", "text"),
    [
        pytest.param(
            "<!doctype html><html><head><meta charset=utf-8><title>Tokio</title>"
            "<body><p>Tokio is an async runtime.</p></body></html>",
            "Tokio is an async runtime.",
            id="closed-by-body",
        ),
        pytest.param(
            "<html><head><title>Tokio</title><link rel=icon href=/i.png>"
            "<p>Tokio is an async runtime.</p>",
            "Tokio is an async runtime.",
            id="closed-by-first-body-content-tag",
        ),
        pytest.param(
            "<head><title>Tokio</title><meta charset=utf-8>Tokio is an async runtime.",
            "Tokio is an async runtime.",
            id="closed-by-text",
        ),
        pytest.param(
            "<head><title>Tokio</title><noscript><link rel=stylesheet href=/x.css>"
            "<body><p>Tokio is an async runtime.</p>",
            "Tokio is an async runtime.",
            id="closes-an-open-noscript-with-it",
        ),
    ],
)
def test_readable_closes_an_unclosed_head_where_html5_does(
    html: str, text: str
) -> None:
    """Given a page that opens <head> but never ends it (HTML5 makes </head>
    optional; minified pages drop it), When extracted, Then the head ends at
    <body>, at the first body-content start tag or at the first text outside
    head content, as the HTML5 tree builder ends it, and the body's text is
    returned with the head's title."""
    page = readable(html)

    assert (page.title, page.text) == ("Tokio", text)


def test_readable_keeps_head_content_out_of_the_text() -> None:
    """Given an unclosed head holding meta, link, style, script and noscript,
    When extracted, Then none of it counts as body content or leaks text."""
    page = readable(
        "<head><title>T</title><meta name=a content=b><link rel=x href=y>"
        "<style>.s{}</style><script>var s;</script><noscript>no</noscript>"
        "<body><p>kept</p>"
    )

    assert page.text == "kept"
