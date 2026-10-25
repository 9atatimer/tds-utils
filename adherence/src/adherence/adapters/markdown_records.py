"""adapters/markdown_records.py -- RecordsPort over markdown-it-py.

Reads the design and architecture records the declaration names, through
RepositoryPort at the target, and parses them as markdown shaped like
DESIGN.ARCH-ADHERENCE.md: the Behaviors table and the Domain Language of
the design; the use-case surface, with the signatures it gives, and the
seam list of the architecture record (ARCHITECTURE.ARCH-ADHERENCE.md,
Module map). A record is data: it is parsed, never rendered or followed.
The adapter compares the Deadline to its own clock and answers TimedOut
rather than overrun it.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Sequence

from markdown_it import MarkdownIt
from markdown_it.token import Token

from adherence.domain.deadline import Deadline, TimedOut
from adherence.domain.declaration import Declaration
from adherence.domain.model import Parameter, Signature
from adherence.domain.records import (
    Behavior,
    DesignRecords,
    RecordsUnavailable,
    Seam,
    SeamKind,
    SurfaceRow,
    Term,
    UseCase,
)
from adherence.domain.target import Base, Head
from adherence.ports.repository import Absent, Refused, RepositoryPort

# --- Constants ---------------------------------------------------------------

BEHAVIORS = "Behaviors"
DOMAIN_LANGUAGE = "Domain Language"
SURFACE = "Use-case surface"
SEAMS = "Seams"
SECTIONS = (BEHAVIORS, DOMAIN_LANGUAGE, SURFACE, SEAMS)
# A heading names a section when its first words, markup dropped and case
# folded, are the section's: `### **Behaviors** (v2)` is the Behaviors.
HEADING_WORD = re.compile(r"[\w-]+")
IDENTIFIER = re.compile(r"[A-Za-z_]\w*")
SIGNATURE = re.compile(
    r"(?P<name>[A-Za-z_]\w*)\((?P<parameters>.*)\)\s*(?:->\s*(?P<returns>.+))?",
    re.DOTALL,
)
# A Kind cell names a seam's kind first; any other cell is no seam.
SEAM_KINDS = (
    ("port", SeamKind.PORT),
    ("policy", SeamKind.POLICY),
    ("parameter", SeamKind.PARAMETER),
)
OPENERS = "([{"
CLOSERS = ")]}"
KEYWORD_ONLY_MARKER = "*"
POSITIONAL_ONLY_MARKER = "/"
NAMES_NONE = "the declaration names no design record"

# --- Pure helpers ------------------------------------------------------------


def _passed(deadline: Deadline | None, now: float) -> bool:
    return deadline is not None and deadline.epoch_seconds <= now


def _line(token: Token) -> int:
    """The 1-based line a block token starts on."""
    return token.map[0] + 1 if token.map else 0


def _section_named(heading: str) -> str | None:
    """The section a heading's plain text names, or None."""
    words = HEADING_WORD.findall(heading.casefold())
    return next(
        (
            section
            for section in SECTIONS
            if (wanted := HEADING_WORD.findall(section.casefold()))
            == words[: len(wanted)]
        ),
        None,
    )


def _level(heading_open: Token) -> int:
    return int(heading_open.tag[1:])


def _sections(tokens: Sequence[Token]) -> dict[str, list[Token]]:
    """Each section's tokens, by the section its heading names at any level:
    a section runs to the next heading as high as its own, and holds the
    deeper headings inside it."""
    sections: dict[str, list[Token]] = {}
    current: list[Token] | None = None
    level = 0
    for index, token in enumerate(tokens):
        if token.type == "heading_open":
            named = _section_named(_plain(tokens[index + 1]))
            if named is not None:
                current, level = sections.setdefault(named, []), _level(token)
                continue
            if _level(token) <= level:
                current, level = None, 0
        if current is not None:
            current.append(token)
    return sections


def _plain(inline: Token) -> str:
    """An inline token's text as read: code spans by their content, breaks
    as spaces, markup dropped, whitespace collapsed."""
    parts = [
        child.content if child.type in {"text", "code_inline"} else " "
        for child in inline.children or []
        if child.type in {"text", "code_inline", "softbreak", "hardbreak"}
    ]
    return " ".join("".join(parts).split())


def _code_spans(inline: Token) -> list[str]:
    return [c.content for c in inline.children or [] if c.type == "code_inline"]


def _rows(tokens: Sequence[Token]) -> list[tuple[int, list[Token]]]:
    """Every body row of every table among the tokens: its line and its
    cells' inline tokens."""
    rows: list[tuple[int, list[Token]]] = []
    in_body = False
    for token in tokens:
        if token.type in {"tbody_open", "tbody_close"}:
            in_body = token.type == "tbody_open"
        elif in_body and token.type == "tr_open":
            rows.append((_line(token), []))
        elif in_body and token.type == "inline" and rows:
            rows[-1][1].append(token)
    return rows


def _split_top_level(text: str) -> list[str]:
    """The text split at every comma outside brackets."""
    parts: list[str] = []
    depth = 0
    start = 0
    for index, char in enumerate(text):
        if char in OPENERS:
            depth += 1
        elif char in CLOSERS:
            depth = max(depth - 1, 0)
        elif char == "," and depth == 0:
            parts.append(text[start:index])
            start = index + 1
    parts.append(text[start:])
    return [p.strip() for p in parts if p.strip()]


def _parameter(text: str, keyword_only: bool) -> Parameter:
    """One parameter as a signature writes it: `name: annotation = default`."""
    head, equals, _default = text.partition("=")
    name, colon, annotation = head.partition(":")
    return Parameter(
        name.strip(),
        annotation.strip() if colon else None,
        keyword_only,
        bool(equals),
    )


def signature_of(code: str) -> tuple[str, Signature] | None:
    """The use case's name and signature a code span states, or None when it
    states none."""
    match = SIGNATURE.fullmatch(code.strip())
    if match is None:
        return None
    parameters: list[Parameter] = []
    keyword_only = False
    for part in _split_top_level(match.group("parameters")):
        if part == KEYWORD_ONLY_MARKER:
            keyword_only = True
        elif part != POSITIONAL_ONLY_MARKER:
            parameters.append(_parameter(part, keyword_only))
    returns = match.group("returns")
    return match.group("name"), Signature(
        tuple(parameters), returns.strip() if returns else None
    )


def _named(code: str) -> str | None:
    """The use case a code span names, by its bare name or its signature."""
    if IDENTIFIER.fullmatch(code.strip()):
        return code.strip()
    stated = signature_of(code)
    return stated[0] if stated is not None else None


def _behaviors(path: str, tokens: Sequence[Token]) -> tuple[Behavior, ...]:
    return tuple(
        Behavior(_plain(cells[0]), _plain(cells[1]), path, line)
        for line, cells in _rows(tokens)
        if len(cells) >= 2
    )


def _term(inline: Token) -> str | None:
    """The term a Domain Language item defines: its leading strong text."""
    children = [c for c in inline.children or [] if c.type != "text" or c.content]
    if len(children) < 3 or children[0].type != "strong_open":
        return None
    name = children[1].content.strip().rstrip(".").strip()
    return name or None


def _terms(path: str, tokens: Sequence[Token]) -> tuple[Term, ...]:
    return tuple(
        Term(name, path, _line(token))
        for token in tokens
        if token.type == "inline" and (name := _term(token)) is not None
    )


def _surface(path: str, tokens: Sequence[Token]) -> tuple[SurfaceRow, ...]:
    return tuple(
        SurfaceRow(
            _plain(cells[0]),
            next(
                (n for code in _code_spans(cells[1]) if (n := _named(code))),
                None,
            ),
            path,
            line,
        )
        for line, cells in _rows(tokens)
        if len(cells) >= 2
    )


def _use_cases(path: str, tokens: Sequence[Token]) -> tuple[UseCase, ...]:
    """Every signature the surface states, in its table or its prose; the
    first stated for a name is that use case's."""
    found: dict[str, UseCase] = {}
    for token in tokens:
        if token.type != "inline":
            continue
        for code in _code_spans(token):
            stated = signature_of(code)
            if stated is not None and stated[0] not in found:
                name, signature = stated
                found[name] = UseCase(name, signature, path, _line(token))
    return tuple(found.values())


def _seam_kind(cell: Token) -> SeamKind | None:
    kind = _plain(cell).lower()
    return next((k for word, k in SEAM_KINDS if kind.startswith(word)), None)


def _seams(path: str, tokens: Sequence[Token]) -> tuple[Seam, ...]:
    seams: list[Seam] = []
    for line, cells in _rows(tokens):
        if len(cells) < 3:
            continue
        names = _code_spans(cells[1])
        kind = _seam_kind(cells[2])
        if names and kind is not None:
            seams.append(Seam(names[0].strip(), kind, path, line))
    return tuple(seams)


def parse_records(
    *, design_path: str, design: str, architecture_path: str, architecture: str
) -> DesignRecords:
    """The DesignRecords two records' markdown states."""
    parser = MarkdownIt("commonmark").enable("table")
    stated = _sections(parser.parse(design))
    surfaced = _sections(parser.parse(architecture))
    return DesignRecords(
        seams=_seams(architecture_path, surfaced.get(SEAMS, [])),
        behaviors=_behaviors(design_path, stated.get(BEHAVIORS, [])),
        terms=_terms(design_path, stated.get(DOMAIN_LANGUAGE, [])),
        use_cases=_use_cases(architecture_path, surfaced.get(SURFACE, [])),
        surface=_surface(architecture_path, surfaced.get(SURFACE, [])),
    )


# --- Adapter -----------------------------------------------------------------


class MarkdownRecords:
    """RecordsPort over markdown records read through a RepositoryPort."""

    def __init__(
        self, repository: RepositoryPort, *, clock: Callable[[], float] = time.time
    ) -> None:
        self._repository = repository
        self._clock = clock

    def _text(
        self, path: str, at: Base | Head, deadline: Deadline | None
    ) -> str | RecordsUnavailable | TimedOut:
        data = self._repository.read(path, at, deadline)
        if isinstance(data, Absent):
            return RecordsUnavailable(f"{path}: no such record at this target")
        if isinstance(data, Refused):
            return RecordsUnavailable(f"{path}: refused: {data.reason}")
        if isinstance(data, TimedOut):
            return data
        return data.decode("utf-8", "replace")

    def records(
        self, at: Base | Head, declaration: Declaration, deadline: Deadline | None
    ) -> DesignRecords | RecordsUnavailable | TimedOut:
        if _passed(deadline, self._clock()):
            return TimedOut("read the design records")
        paths = declaration.records
        if paths is None:
            return RecordsUnavailable(NAMES_NONE)
        design = self._text(paths.design, at, deadline)
        if not isinstance(design, str):
            return design
        architecture = self._text(paths.architecture, at, deadline)
        if not isinstance(architecture, str):
            return architecture
        return parse_records(
            design_path=paths.design,
            design=design,
            architecture_path=paths.architecture,
            architecture=architecture,
        )
