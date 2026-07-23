"""Netscape bookmark HTML: the format chrome://bookmarks imports and exports.

Primary input and the only v1 write path. Parsing uses the stdlib
``html.parser`` (no lxml/bs4). Emission writes umbrella (direct) links before
subfolders and nothing after the folders, so Chrome round-trips manual order.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

from orgmarks.domain.model import (
    ROOT_NAMES,
    Bookmark,
    BookmarkTree,
    Folder,
    FolderPath,
    RootName,
)

# Top-level Netscape folder name (lowercased) -> Chrome root.
_ROOT_BY_NAME: dict[str, RootName] = {
    "bookmarks bar": "bookmarks_bar",
    "bookmarks toolbar": "bookmarks_bar",
    "favorites bar": "bookmarks_bar",
    "other bookmarks": "other",
    "other": "other",
    "mobile bookmarks": "synced",
    "synced": "synced",
}

# Chrome root -> display name emitted back into the HTML.
_NAME_BY_ROOT: dict[RootName, str] = {
    "bookmarks_bar": "Bookmarks bar",
    "other": "Other bookmarks",
    "synced": "Mobile bookmarks",
}


@dataclass(slots=True)
class _FolderBuilder:
    """Mutable folder node used while parsing."""

    name: str = ""
    add_date: int | None = None
    subfolders: list[_FolderBuilder] = field(default_factory=list)
    bookmarks: list[Bookmark] = field(default_factory=list)


def _parse_add_date(raw: str | None) -> int | None:
    if raw is None or not raw.strip():
        return None
    try:
        return int(raw)
    except ValueError:
        return None


class _NetscapeParser(HTMLParser):
    """Build a tree of ``_FolderBuilder`` nodes from Netscape HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _FolderBuilder(name="__root__")
        self._stack: list[_FolderBuilder] = [self.root]
        self._pending: _FolderBuilder | None = None
        self._in_h3 = False
        self._h3_text: list[str] = []
        self._in_a = False
        self._a_text: list[str] = []
        self._a_href: str = ""
        self._a_add_date: int | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k: v for k, v in attrs}
        if tag == "h3":
            self._in_h3 = True
            self._h3_text = []
            folder = _FolderBuilder(add_date=_parse_add_date(attr.get("add_date")))
            self._stack[-1].subfolders.append(folder)
            self._pending = folder
        elif tag == "dl":
            if self._pending is not None:
                self._stack.append(self._pending)
                self._pending = None
            else:
                self._stack.append(self._stack[-1])
        elif tag == "a":
            self._in_a = True
            self._a_text = []
            self._a_href = attr.get("href") or ""
            self._a_add_date = _parse_add_date(attr.get("add_date"))

    def handle_endtag(self, tag: str) -> None:
        if tag == "h3" and self._in_h3:
            self._in_h3 = False
            if self._pending is not None:
                self._pending.name = "".join(self._h3_text).strip()
        elif tag == "dl":
            if len(self._stack) > 1:
                self._stack.pop()
        elif tag == "a" and self._in_a:
            self._in_a = False
            title = "".join(self._a_text).strip()
            self._stack[-1].bookmarks.append(
                Bookmark(
                    url=self._a_href,
                    title=title,
                    add_date=self._a_add_date or 0,
                    source_path=FolderPath(()),
                )
            )

    def handle_data(self, data: str) -> None:
        if self._in_h3:
            self._h3_text.append(data)
        elif self._in_a:
            self._a_text.append(data)


def _root_name_for(builder: _FolderBuilder, index: int) -> RootName:
    mapped = _ROOT_BY_NAME.get(builder.name.strip().lower())
    if mapped is not None:
        return mapped
    return ROOT_NAMES[index] if index < len(ROOT_NAMES) else "other"


def _freeze(builder: _FolderBuilder, path: FolderPath) -> Folder:
    """Convert a builder subtree to a frozen Folder, stamping source_path."""
    bookmarks = tuple(
        Bookmark(
            url=bm.url,
            title=bm.title,
            add_date=bm.add_date,
            source_path=path,
            guid=bm.guid,
        )
        for bm in builder.bookmarks
    )
    subfolders = tuple(_freeze(sub, path.child(sub.name)) for sub in builder.subfolders)
    return Folder(
        name=builder.name,
        subfolders=subfolders,
        bookmarks=bookmarks,
        add_date=builder.add_date,
    )


def parse_netscape(text: str) -> BookmarkTree:
    """Parse Netscape bookmark HTML into a BookmarkTree."""
    parser = _NetscapeParser()
    parser.feed(text)
    parser.close()
    roots: list[tuple[RootName, Folder]] = []
    for index, top in enumerate(parser.root.subfolders):
        root_name = _root_name_for(top, index)
        base = FolderPath((root_name,))
        frozen = _freeze(top, base)
        roots.append(
            (
                root_name,
                Folder(
                    name=root_name,
                    subfolders=frozen.subfolders,
                    bookmarks=frozen.bookmarks,
                    add_date=frozen.add_date,
                ),
            )
        )
    return BookmarkTree(roots=tuple(roots))


def _emit_bookmark(bm: Bookmark, indent: str) -> str:
    date = f' ADD_DATE="{bm.add_date}"' if bm.add_date else ""
    href = html.escape(bm.url, quote=True)
    title = html.escape(bm.title)
    return f'{indent}<DT><A HREF="{href}"{date}>{title}</A>\n'


def _emit_folder(folder: Folder, indent: str, *, toolbar: bool) -> str:
    date = f' ADD_DATE="{folder.add_date}"' if folder.add_date else ""
    toolbar_attr = ' PERSONAL_TOOLBAR_FOLDER="true"' if toolbar else ""
    name = html.escape(folder.name)
    out = [f"{indent}<DT><H3{date}{toolbar_attr}>{name}</H3>\n"]
    out.append(f"{indent}<DL><p>\n")
    inner = indent + "    "
    # Big-buttons-first: umbrella links, then subfolders, nothing after.
    for bm in folder.bookmarks:
        out.append(_emit_bookmark(bm, inner))
    for sub in folder.subfolders:
        out.append(_emit_folder(sub, inner, toolbar=False))
    out.append(f"{indent}</DL><p>\n")
    return "".join(out)


def emit_netscape(tree: BookmarkTree) -> str:
    """Serialize a BookmarkTree back to Netscape bookmark HTML."""
    parts = [
        "<!DOCTYPE NETSCAPE-Bookmark-file-1>\n",
        '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">\n',
        "<TITLE>Bookmarks</TITLE>\n",
        "<H1>Bookmarks</H1>\n",
        "<DL><p>\n",
    ]
    for root_name, folder in tree.roots:
        display = Folder(
            name=_NAME_BY_ROOT.get(root_name, folder.name),
            subfolders=folder.subfolders,
            bookmarks=folder.bookmarks,
            add_date=folder.add_date,
        )
        parts.append(
            _emit_folder(display, "    ", toolbar=(root_name == "bookmarks_bar"))
        )
    parts.append("</DL><p>\n")
    return "".join(parts)


class NetscapeSource:
    """BookmarkSource reading Netscape HTML from a file."""

    def load(self, path: Path) -> BookmarkTree:
        """Read and parse the file at ``path`` (read-only)."""
        return parse_netscape(path.read_text(encoding="utf-8"))


class NetscapeSink:
    """BookmarkSink writing Netscape HTML."""

    def emit(self, tree: BookmarkTree) -> str:
        """Serialize ``tree`` to Netscape HTML text."""
        return emit_netscape(tree)
