"""The shell code model's fixture tree, read as the use case would hand it
over: every shell file's bytes by repository path, and its declaration."""

from __future__ import annotations

import re
from pathlib import Path

from adherence.domain.declaration import (
    DECLARATION_PATH,
    Declaration,
    parse_declaration,
)
from adherence.domain.model import Layer
from adherence.domain.parameters import Vocabulary

ROOT = Path(__file__).resolve().parent / "fixtures" / "shell"
SUFFIXES = {".sh", ".bash", ".zsh"}
# A bash, zsh or sh shebang, directly or through env.
SHEBANG = re.compile(rb"^#!\s*\S*/(?:env\s+)?(?:ba|z)?sh\b")
VOCABULARY = Vocabulary(
    regions={
        "action functions": Layer.ADAPTERS,
        "flow functions": Layer.APPLICATION,
        "main": Layer.COMPOSITION_ROOT,
    },
    sleeps=frozenset({"sleep"}),
    stubs=frozenset({":"}),
)


def is_shell(path: Path) -> bool:
    """Whether a file is shell: by its extension, or by its shebang."""
    if path.suffix in SUFFIXES:
        return True
    with path.open("rb") as handle:
        return SHEBANG.match(handle.readline()) is not None


def sources_under(root: Path) -> dict[str, bytes]:
    """Every shell file under root, by its path relative to root."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink() and is_shell(path)
    }


def sources() -> dict[str, bytes]:
    return sources_under(ROOT)


def declaration() -> Declaration:
    parsed = parse_declaration((ROOT / DECLARATION_PATH).read_bytes())
    assert isinstance(parsed, Declaration)
    return parsed
