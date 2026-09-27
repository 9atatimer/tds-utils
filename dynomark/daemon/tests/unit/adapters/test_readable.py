"""Readable-text extraction inside the fetch adapter (Design, Key Decisions:
"Extraction -- inside the ContentSourcePort adapters"). Standard-library
``html.parser`` only: scripts, styles, navigation, headers and footers are
dropped; an ``article`` is preferred, then ``main``, then the whole body.
"""

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
