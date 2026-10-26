"""adapters/python_names.py -- what a name in a Python source stands for.

A file's imports bind local names to the modules and attributes they
import (`from time import sleep as nap` binds `nap` to `time.sleep`); a
dotted name written in the file is read through those bindings to the
name it stands for. The bindings are read from the ast alone: nothing is
imported or run.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping

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
