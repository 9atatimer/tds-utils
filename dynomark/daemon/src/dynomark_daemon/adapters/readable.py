"""Readable text from HTML, with the standard library's ``html.parser``.

The fetch adapter's extraction (Design, Key Decisions: "Extraction --
inside the ContentSourcePort adapters"): text inside ``script``, ``style``,
``nav``, ``header``, ``footer`` and other invisible elements is dropped;
the text of the ``article`` elements is preferred, then ``main``, then the
whole document. Block elements break lines; whitespace runs collapse.
"""

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Final

MAX_TEXT: Final = 1_048_576
"""``Capture.text``'s cap in code points (contract v1, Size limits)."""

SKIPPED: Final = frozenset(
    {
        "script",
        "style",
        "nav",
        "header",
        "footer",
        "noscript",
        "template",
        "svg",
        "iframe",
        "head",
    }
)
BLOCKS: Final = frozenset(
    {
        "p",
        "div",
        "br",
        "li",
        "ul",
        "ol",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "section",
        "article",
        "main",
        "tr",
        "td",
        "th",
        "pre",
        "blockquote",
        "dt",
        "dd",
        "figcaption",
        "hr",
        "table",
    }
)
HEAD_CONTENT: Final = frozenset(
    {
        "html",
        "head",
        "base",
        "basefont",
        "bgsound",
        "link",
        "meta",
        "title",
        "noscript",
        "noframes",
        "style",
        "script",
        "template",
    }
)
"""Start tags the HTML5 tree builder keeps in an open ``head`` ("in head"
insertion mode); any other start tag ends the head, and so does text."""
HEAD_ENDING_END_TAGS: Final = frozenset({"head", "body", "html", "br"})
HEAD_TEXT_HOLDERS: Final = frozenset(
    {"noscript", "noframes", "style", "script", "template"}
)
"""Head content whose text is its own: text inside one does not end the head
(the void ``meta``, ``link`` and ``base`` hold none)."""
SPACES: Final = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class Readable:
    title: str | None
    text: str


@dataclass
class _Text:
    """Text runs per region; a region's text is joined at the end."""

    all: list[str] = field(default_factory=list)
    main: list[str] = field(default_factory=list)
    article: list[str] = field(default_factory=list)


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.open: dict[str, int] = {}
        self.text = _Text()
        self.title: list[str] = []

    def _depth(self, tag: str) -> int:
        return self.open.get(tag, 0)

    def _skipping(self) -> bool:
        return any(self._depth(tag) for tag in SKIPPED)

    def _break(self) -> None:
        self._add("\n")

    def _add(self, run: str) -> None:
        self.text.all.append(run)
        if self._depth("main"):
            self.text.main.append(run)
        if self._depth("article"):
            self.text.article.append(run)

    def _end_head(self) -> None:
        """End an open ``head`` whose end tag was omitted, as the HTML5 tree
        builder does: everything still open was opened inside it (an
        unclosed ``noscript`` too), so only ``html`` stays open."""
        self.open = {"html": self._depth("html")}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._depth("head") and tag not in HEAD_CONTENT:
            self._end_head()
        if tag in BLOCKS:
            self._break()
        if tag != "br" and tag != "hr":
            self.open[tag] = self._depth(tag) + 1

    def handle_endtag(self, tag: str) -> None:
        if tag in HEAD_ENDING_END_TAGS and self._depth("head"):
            self._end_head()
        elif self._depth(tag):
            self.open[tag] -= 1
        if tag in BLOCKS:
            self._break()

    def handle_data(self, data: str) -> None:
        if self._depth("title"):
            self.title.append(data)
            return
        if self._depth("head") and data.strip() and not self._in_head_content():
            self._end_head()
        if not self._skipping():
            self._add(SPACES.sub(" ", data))

    def _in_head_content(self) -> bool:
        """Inside an element of the head whose text is its own (a script)."""
        return any(self._depth(tag) for tag in HEAD_TEXT_HOLDERS)


def _lines(runs: list[str]) -> str:
    text = "".join(runs)
    lines = (SPACES.sub(" ", line).strip() for line in text.split("\n"))
    return "\n".join(line for line in lines if line)


def readable(html: str) -> Readable:
    """The page's title and its readable text (at most ``MAX_TEXT``)."""
    extractor = _Extractor()
    extractor.feed(html)
    extractor.close()
    regions = (extractor.text.article, extractor.text.main, extractor.text.all)
    text = next((t for t in map(_lines, regions) if t), "")
    title = SPACES.sub(" ", "".join(extractor.title)).strip()
    return Readable(title=title or None, text=text[:MAX_TEXT])
