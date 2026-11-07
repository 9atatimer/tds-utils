"""Resolving an import specifier to a file in the repository.

TypeScript/JavaScript: relative specifiers with extension and index probing,
tsconfig `paths` mappings, and workspace packages by name (exports, main, or
src/index). Python: absolute imports against the top-level package roots
(src layout included) and the importing file's own directory, and relative
imports against the importing package. A specifier that reaches no file in
the repository resolves to None: external, or not understood.
"""

import json
import posixpath
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from layer_graph.domain.imports import PythonImport

# --- Constants ---------------------------------------------------------------

TS_EXTENSIONS = (".ts", ".tsx", ".js", ".mjs", ".vue")
# A .js specifier naming a .ts source (TypeScript's ESM convention).
JS_TO_TS = {".js": (".ts", ".tsx"), ".mjs": (".mts", ".ts"), ".jsx": (".tsx",)}
EXPORT_CONDITIONS = ("import", "module", "default", "types", "require", "node")
FALLBACK_ENTRIES = ("src/index", "index")
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")


# --- Values ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Package:
    """A workspace package: its name, directory, exports by subpath, main."""

    name: str
    directory: str
    exports: tuple[tuple[str, str], ...]
    main: str | None


@dataclass(frozen=True, slots=True)
class PathScope:
    """The tsconfig `paths` that apply to files under a directory, targets
    already resolved to repository paths."""

    directory: str
    mappings: tuple[tuple[str, tuple[str, ...]], ...]


@dataclass(frozen=True, slots=True)
class TsConfig:
    """What one tsconfig file says that resolution needs."""

    extends: tuple[str, ...]
    references: tuple[str, ...]
    mappings: tuple[tuple[str, tuple[str, ...]], ...]


@dataclass(frozen=True, slots=True)
class Workspace:
    """Everything resolution reads: the repository's files, its packages,
    its tsconfig path scopes and its Python roots."""

    files: frozenset[str]
    packages: tuple[Package, ...] = ()
    scopes: tuple[PathScope, ...] = ()
    python_roots: tuple[str, ...] = ()


# --- Predicates --------------------------------------------------------------


def is_relative(specifier: str) -> bool:
    """Whether a specifier is relative to the importing file."""
    return specifier.startswith(("./", "../")) or specifier in {".", ".."}


def _escapes(path: str) -> bool:
    return path == ".." or path.startswith("../") or path.startswith("/")


# --- Pure helpers: manifests ---------------------------------------------------


def strip_jsonc(text: str) -> str:
    """JSON-with-comments as plain JSON: comments outside strings removed,
    trailing commas dropped."""
    out: list[str] = []
    i = 0
    in_string = False
    while i < len(text):
        char = text[i]
        if in_string:
            out.append(char)
            if char == "\\" and i + 1 < len(text):
                out.append(text[i + 1])
                i += 2
                continue
            in_string = char != '"'
            i += 1
            continue
        if char == '"':
            in_string = True
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = len(text) if end < 0 else end
            continue
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = len(text) if end < 0 else end + 2
            continue
        out.append(char)
        i += 1
    return _TRAILING_COMMA.sub(r"\1", "".join(out))


def load_json(text: str, *, comments: bool = False) -> object:
    """Parsed JSON (JSONC when `comments`), or None when it does not parse."""
    try:
        parsed: object = json.loads(strip_jsonc(text) if comments else text)
    except ValueError:
        return None
    return parsed


def _mapping(value: object) -> Mapping[str, object]:
    return {str(k): v for k, v in value.items()} if isinstance(value, dict) else {}


def _condition(value: object) -> str | None:
    """The first usable target of an exports value: a string, a list's first
    usable item, or a conditions object's preferred condition."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        for item in value:
            found = _condition(item)
            if found:
                return found
        return None
    conditions = _mapping(value)
    for key in (*EXPORT_CONDITIONS, *conditions):
        if key in conditions:
            found = _condition(conditions[key])
            if found:
                return found
    return None


def export_targets(exports: object) -> tuple[tuple[str, str], ...]:
    """A package.json `exports` field as (subpath, target) pairs."""
    table = _mapping(exports)
    if not table or not all(k.startswith(".") for k in table):
        target = _condition(exports)
        return ((".", target),) if target else ()
    pairs: list[tuple[str, str]] = []
    for subpath, value in table.items():
        target = _condition(value)
        if target:
            pairs.append((subpath, target))
    return tuple(pairs)


def package_from_manifest(directory: str, manifest: object) -> Package | None:
    """A workspace package from its package.json, or None without a name."""
    data = _mapping(manifest)
    name = data.get("name")
    if not isinstance(name, str) or not name:
        return None
    main = data.get("main")
    return Package(
        name=name,
        directory=directory,
        exports=export_targets(data.get("exports")),
        main=main if isinstance(main, str) else None,
    )


def _under(directory: str, relative: str) -> str:
    return (
        posixpath.normpath(posixpath.join(directory, relative))
        if relative
        else (directory)
    )


def tsconfig_from(path: str, config: object) -> TsConfig:
    """What a tsconfig file at `path` says: relative extends, references, and
    its `paths` with targets resolved against baseUrl or its own directory."""
    data = _mapping(config)
    directory = posixpath.dirname(path)
    extends_value = data.get("extends")
    extends_list = extends_value if isinstance(extends_value, list) else [extends_value]
    extends = tuple(
        _config_file(_under(directory, e))
        for e in extends_list
        if isinstance(e, str) and is_relative(e)
    )
    references_value = data.get("references")
    references = tuple(
        _config_file(_under(directory, str(r["path"])))
        for r in (references_value if isinstance(references_value, list) else [])
        if isinstance(r, dict) and isinstance(r.get("path"), str)
    )
    options = _mapping(data.get("compilerOptions"))
    base_url = options.get("baseUrl")
    base = _under(directory, base_url) if isinstance(base_url, str) else directory
    mappings: list[tuple[str, tuple[str, ...]]] = []
    for pattern, targets in _mapping(options.get("paths")).items():
        if isinstance(targets, list):
            resolved = tuple(_under(base, t) for t in targets if isinstance(t, str))
            mappings.append((pattern, resolved))
    return TsConfig(extends, references, tuple(mappings))


def _config_file(path: str) -> str:
    return path if path.endswith(".json") else posixpath.join(path, "tsconfig.json")


def python_roots(files: Iterable[str]) -> tuple[str, ...]:
    """The directories that hold a top-level Python package: the parent of
    every package directory whose own parent is not a package."""
    packages = {posixpath.dirname(f) for f in files if f.endswith("/__init__.py")}
    packages |= {"" for f in files if f == "__init__.py"}
    roots = {
        posixpath.dirname(p)
        for p in packages
        if p and posixpath.dirname(p) not in packages
    }
    return tuple(sorted(roots))


# --- Pure helpers: probing -------------------------------------------------------


def _candidates(path: str) -> list[str]:
    stem, extension = posixpath.splitext(path)
    found = [path]
    found += [stem + ts for ts in JS_TO_TS.get(extension, ())]
    found += [path + ext for ext in TS_EXTENSIONS]
    found += [posixpath.join(path, "index" + ext) for ext in TS_EXTENSIONS]
    return found


def probe(path: str, files: frozenset[str]) -> str | None:
    """The file a module path names: itself, with an extension, or as a
    directory's index; None when nothing in the repository matches."""
    if _escapes(path):
        return None
    for candidate in _candidates(posixpath.normpath(path)):
        if candidate in files:
            return candidate
    return None


# --- Pure helpers: TypeScript resolution ------------------------------------------


def _scope_for(importer: str, scopes: Iterable[PathScope]) -> PathScope | None:
    best: PathScope | None = None
    for scope in scopes:
        directory = scope.directory
        if directory == "" or importer.startswith(directory + "/"):
            if best is None or len(directory) > len(best.directory):
                best = scope
    return best


def _star_match(pattern: str, specifier: str) -> str | None:
    """What a single-star pattern's star captures, or None on no match."""
    if "*" not in pattern:
        return "" if pattern == specifier else None
    head, _, tail = pattern.partition("*")
    if (
        specifier.startswith(head)
        and specifier.endswith(tail)
        and len(specifier) >= len(head) + len(tail)
    ):
        return specifier[len(head) : len(specifier) - len(tail)]
    return None


def _through_paths(
    specifier: str, scope: PathScope, files: frozenset[str]
) -> str | None:
    hits = [
        (len(pattern.partition("*")[0]), pattern, targets, captured)
        for pattern, targets in scope.mappings
        if (captured := _star_match(pattern, specifier)) is not None
    ]
    for _, _, targets, captured in sorted(hits, key=lambda h: -h[0]):
        for target in targets:
            found = probe(target.replace("*", captured), files)
            if found:
                return found
    return None


def _package_for(specifier: str, packages: Iterable[Package]) -> Package | None:
    best: Package | None = None
    for package in packages:
        if specifier == package.name or specifier.startswith(package.name + "/"):
            if best is None or len(package.name) > len(best.name):
                best = package
    return best


def _through_exports(package: Package, subpath: str) -> str | None:
    for key, target in package.exports:
        if key == subpath:
            return target
    for key, target in package.exports:
        captured = _star_match(key, subpath)
        if "*" in key and captured is not None:
            return target.replace("*", captured)
    return None


def _through_package(
    specifier: str, package: Package, files: frozenset[str]
) -> str | None:
    rest = specifier[len(package.name) :].lstrip("/")
    subpath = "./" + rest if rest else "."
    exported = _through_exports(package, subpath)
    if exported:
        return probe(_under(package.directory, exported), files)
    if rest:
        return probe(_under(package.directory, rest), files) or probe(
            _under(package.directory, "src/" + rest), files
        )
    entries = ([package.main] if package.main else []) + list(FALLBACK_ENTRIES)
    for entry in entries:
        found = probe(_under(package.directory, entry), files)
        if found:
            return found
    return None


def resolve_ts(importer: str, specifier: str, workspace: Workspace) -> str | None:
    """The repository file a TypeScript/JavaScript specifier names, or None."""
    specifier = specifier.split("?", 1)[0]
    if not specifier:
        return None
    files = workspace.files
    if is_relative(specifier):
        return probe(_under(posixpath.dirname(importer), specifier), files)
    scope = _scope_for(importer, workspace.scopes)
    if scope is not None:
        found = _through_paths(specifier, scope, files)
        if found:
            return found
    package = _package_for(specifier, workspace.packages)
    if package is not None:
        return _through_package(specifier, package, files)
    return None


# --- Pure helpers: Python resolution ---------------------------------------------


def _python_module(base: str, dotted: str, files: frozenset[str]) -> str | None:
    path = _under(base, dotted.replace(".", "/")) if dotted else base
    if _escapes(path):
        return None
    for candidate in (path + ".py", posixpath.join(path, "__init__.py")):
        candidate = posixpath.normpath(candidate)
        if candidate in files:
            return candidate
    return None


def _python_bases(
    importer: str, imported: PythonImport, roots: tuple[str, ...]
) -> list[str]:
    directory = posixpath.dirname(importer)
    if imported.level:
        base = directory
        for _ in range(imported.level - 1):
            base = posixpath.dirname(base) if base else ".."
        return [base]
    ancestors = sorted(
        (r for r in roots if r == "" or importer.startswith(r + "/")),
        key=len,
        reverse=True,
    )
    others = [r for r in roots if r not in ancestors]
    ordered = [*ancestors, *others, directory, ""]
    return list(dict.fromkeys(ordered))


def resolve_python(
    importer: str, imported: PythonImport, workspace: Workspace
) -> tuple[str, ...]:
    """The repository files a Python import reaches: each imported name that
    is a submodule, else the module itself; empty when none is in the
    repository."""
    files = workspace.files
    for base in _python_bases(importer, imported, workspace.python_roots):
        module = _python_module(base, imported.module, files)
        submodules = [
            found
            for name in imported.names
            if name != "*"
            and (found := _python_module(base, _joined(imported.module, name), files))
        ]
        if submodules:
            return tuple(dict.fromkeys(submodules))
        if module:
            return (module,)
    return ()


def _joined(module: str, name: str) -> str:
    return f"{module}.{name}" if module else name
