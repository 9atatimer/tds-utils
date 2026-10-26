"""adapters/python_names.py -- what a name in a Python source stands for.

A file's imports bind local names to the modules and attributes they
import (`from time import sleep as nap` binds `nap` to `time.sleep`); a
dotted name written in the file is read through those bindings, and the
file's own definitions, to the name it stands for and, when the
repository defines it, to that definition's file and symbol. Everything
is read from the ast alone: nothing is imported or run.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from dataclasses import dataclass

from adherence.adapters.python_imports import beside
from adherence.domain.model import Target

# --- Constants ---------------------------------------------------------------

SELF = "self"
# How many re-exports, or bases, one resolution follows at most.
HOPS = 8
# unittest's test types, by the dotted names they are imported as; a method
# they carry resolves to TEST_CASE's.
TEST_CASE = "unittest.TestCase"
TEST_CASE_TYPES = frozenset(
    {
        "unittest.TestCase",
        "unittest.case.TestCase",
        "unittest.IsolatedAsyncioTestCase",
        "unittest.async_case.IsolatedAsyncioTestCase",
    }
)

# --- Pure helpers ------------------------------------------------------------


def chain(node: ast.expr) -> list[str] | None:
    """The names of a dotted chain (`os.environ.get`), outermost first; None
    when the expression is not one."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return parts[::-1]


def relative_base(module: str | None, is_package: bool, level: int) -> str | None:
    """The package a relative import of that level starts from, in a file of
    that module (a package's `__init__` when is_package); None when the
    file's module is unknown or the import climbs past its top."""
    if module is None:
        return None
    parts = module.split(".") if module else []
    if not is_package:
        parts = parts[:-1]
    climb = level - 1
    if climb >= len(parts):
        return None
    return ".".join(parts[: len(parts) - climb])


def _from_base(
    node: ast.ImportFrom, module: str | None, is_package: bool
) -> str | None:
    """The module a `from ... import` reads from, resolved when relative."""
    if node.level == 0:
        return node.module
    base = relative_base(module, is_package, node.level)
    if base is None:
        return None
    return f"{base}.{node.module}" if node.module else base


def imported_names(
    tree: ast.Module, module: str | None = None, is_package: bool = False
) -> dict[str, str]:
    """Each name the file's imports bind, anywhere in it, to the dotted name
    it stands for; module-level imports first, a later binding winning. A
    relative import resolves only when the file's module is known."""
    bound: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    bound[alias.asname] = alias.name
                else:
                    top = alias.name.split(".")[0]
                    bound[top] = top
        elif isinstance(node, ast.ImportFrom):
            base = _from_base(node, module, is_package)
            if base is None:
                continue
            for alias in node.names:
                if alias.name != "*":
                    bound[alias.asname or alias.name] = f"{base}.{alias.name}"
    return bound


def expanded(parts: list[str], imported: Mapping[str, str]) -> str:
    """A dotted chain read through the imports: its first name replaced by
    what an import binds it to, when one does."""
    head = imported.get(parts[0])
    if head is None:
        return ".".join(parts)
    return ".".join([head, *parts[1:]])


def qualified(module: str | None, symbol: str) -> str:
    """A definition's dotted name: its symbol under its module, when known."""
    return f"{module}.{symbol}" if module else symbol


# --- Values ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FileNames:
    """What one source binds: its module (None outside a package), each name
    its imports bind to the dotted name it stands for, the symbols it
    defines, and each of its types' bases as dotted chains."""

    module: str | None
    imported: Mapping[str, str]
    defined: frozenset[str]
    bases: Mapping[str, tuple[tuple[str, ...], ...]]


# --- Resolver ----------------------------------------------------------------


class Resolver:
    """Reads a callee to what it stands for across the sources: through its
    file's imports and definitions, a module's re-exports, and, for
    `self.<method>`, its type's bases -- a test type's own method, or
    unittest's TestCase's. Bounded: at most HOPS re-exports or bases deep,
    and linear in breadth -- a base listed twice is walked once, a type
    already walked with as many hops left is not walked again, and each
    type's member is resolved once (Self-review re-review H1, task-061)."""

    def __init__(
        self,
        *,
        files: Mapping[str, FileNames],
        modules: Mapping[str, str],
    ) -> None:
        self._files = files
        self._modules = modules
        self._members: dict[tuple[str, str, str], Target | None] = {}

    def imported(self, path: str) -> Mapping[str, str]:
        """Each name a file's imports bind, to the dotted name it stands for."""
        names = self._files.get(path)
        return {} if names is None else names.imported

    def target(self, path: str, within: str | None, parts: list[str]) -> Target | None:
        """What a dotted chain written in a definition of a file stands for;
        None when neither the file nor its imports bind its first name."""
        names = self._files.get(path)
        if names is None:
            return None
        head = parts[0]
        if head == SELF and len(parts) == 2 and within is not None:
            owner = within.rpartition(".")[0]
            if owner in names.bases:
                return self._own_member(path, owner, parts[1])
        if head in names.defined:
            symbol = ".".join(parts)
            return Target(
                name=qualified(names.module, symbol), path=path, symbol=symbol
            )
        if head in names.imported:
            return self._located(expanded(parts, names.imported), path, HOPS)
        return None

    def _module_path(self, module: str, near: str) -> str | None:
        """The source of a module an import in the file `near` names: beside
        a file outside any package first, as Python searches, then among
        the packages."""
        names = self._files.get(near)
        if names is not None and names.module is None:
            found = beside(near, module, self._files.keys())
            if found is not None:
                return found
        return self._modules.get(module)

    def _located(self, dotted: str, near: str, hops: int) -> Target:
        """The repository definition a dotted name names -- its longest
        prefix that is a module, the rest a symbol there, a re-export
        followed -- or the name alone when it is outside the repository."""
        parts = dotted.split(".")
        for cut in range(len(parts), 0, -1):
            path = self._module_path(".".join(parts[:cut]), near)
            if path is None:
                continue
            rest = parts[cut:]
            names = self._files.get(path)
            if rest and names is not None and hops > 0:
                if rest[0] not in names.defined and rest[0] in names.imported:
                    again = expanded(rest, names.imported)
                    return self._located(again, path, hops - 1)
            symbol = ".".join(rest) or None
            return Target(name=dotted, path=path, symbol=symbol)
        return Target(name=dotted)

    def _own_member(self, path: str, owner: str, name: str) -> Target | None:
        """A method of a type, resolved once per type and name."""
        key = (path, owner, name)
        if key not in self._members:
            self._members[key] = self._member(path, owner, name, HOPS, {})
        return self._members[key]

    def _member(
        self,
        path: str,
        owner: str,
        name: str,
        hops: int,
        walked: dict[tuple[str, str], int],
    ) -> Target | None:
        """A method of a type, defined on it or inherited from its bases;
        walked holds each type this lookup has walked the bases of, with the
        most hops it had left, so no type is walked twice with no more."""
        names = self._files[path]
        symbol = f"{owner}.{name}"
        if symbol in names.defined:
            return Target(
                name=qualified(names.module, symbol), path=path, symbol=symbol
            )
        if hops <= 0 or walked.get((path, owner), -1) >= hops:
            return None
        walked[(path, owner)] = hops
        for base in dict.fromkeys(names.bases.get(owner, ())):
            found = self._inherited(path, list(base), name, hops - 1, walked)
            if found is not None:
                return found
        return None

    def _inherited(
        self,
        path: str,
        base: list[str],
        name: str,
        hops: int,
        walked: dict[tuple[str, str], int],
    ) -> Target | None:
        """A method a type gets from one base: unittest's TestCase's, or the
        base type's own when the repository defines it."""
        resolved = self.target(path, None, base)
        if resolved is None:
            return None
        if resolved.path is None:
            if resolved.name in TEST_CASE_TYPES:
                return Target(name=f"{TEST_CASE}.{name}")
            return None
        owner = self._files.get(resolved.path)
        if resolved.symbol is None or owner is None:
            return None
        if resolved.symbol not in owner.bases:
            return None
        return self._member(resolved.path, resolved.symbol, name, hops, walked)
