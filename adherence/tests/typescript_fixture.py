"""The TypeScript code model's fixture tree, read as the use case would hand
it over: every TypeScript and JavaScript file's bytes by repository path,
and its declaration."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from adherence.domain.declaration import (
    DECLARATION_PATH,
    Declaration,
    parse_declaration,
)
from adherence.domain.model import Layer
from adherence.domain.parameters import Vocabulary

ROOT = Path(__file__).resolve().parent / "fixtures" / "typescript"
CRUISER = (
    Path(__file__).resolve().parents[1] / "node" / "node_modules" / "dependency-cruiser"
)
# A claim about what dependency-cruiser resolves runs the real tool, and is
# skipped, never faked, where it is not installed (the testing skill; the
# adherence CI job installs no node tools yet, Issue#593).
needs_cruiser = pytest.mark.skipif(
    not (CRUISER.is_dir() and shutil.which("node")),
    reason="dependency-cruiser is not installed: "
    "npm ci --ignore-scripts in adherence/node",
)
SUFFIXES = {".ts", ".mts", ".cts", ".tsx", ".js", ".mjs", ".cjs", ".jsx"}
VOCABULARY = Vocabulary(
    regions={"predicates": Layer.DOMAIN, "action functions": Layer.ADAPTERS},
    environment_reads=frozenset({"process.env"}),
    sleeps=frozenset({"sleep", "setTimeout"}),
    stubs=frozenset({"{}", "NotImplementedError"}),
    options_objects=frozenset({"deps"}),
    tests=frozenset({"test", "it"}),
    assertions=frozenset({"assert", "expect"}),
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
