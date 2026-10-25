"""The TypeScript code model's fixture tree, read as the use case would hand
it over: every TypeScript and JavaScript file's bytes by repository path,
and its declaration."""

from __future__ import annotations

from pathlib import Path

from adherence.domain.declaration import (
    DECLARATION_PATH,
    Declaration,
    parse_declaration,
)
from adherence.domain.model import Layer
from adherence.domain.parameters import Vocabulary

ROOT = Path(__file__).resolve().parent / "fixtures" / "typescript"
SUFFIXES = {".ts", ".mts", ".cts", ".tsx", ".js", ".mjs", ".cjs", ".jsx"}
VOCABULARY = Vocabulary(
    regions={"predicates": Layer.DOMAIN, "action functions": Layer.ADAPTERS},
)


def sources() -> dict[str, bytes]:
    return {
        path.relative_to(ROOT).as_posix(): path.read_bytes()
        for path in sorted(ROOT.rglob("*"))
        if path.suffix in SUFFIXES
    }


def declaration() -> Declaration:
    parsed = parse_declaration((ROOT / DECLARATION_PATH).read_bytes())
    assert isinstance(parsed, Declaration)
    return parsed
