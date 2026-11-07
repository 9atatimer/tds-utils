# layer-graph -- runbook

`bin/layer-graph` reads a repository's `adherence.toml` declarations and the
import statements of the files they declare, and prints the repository's
layer/domain graph as JSON: which (layer, context) nodes exist, which nodes
import which, and the findings that graph shows (outward edges, cycles,
undeclared files). It is procedural: no model, no network, no judgement.

- Launcher: `bin/layer-graph` (bash, runs on macOS and Linux) execs the uv
  project `layer-graph/`.
- Code: `layer-graph/src/layer_graph/` -- `domain/` (globs, declarations,
  contexts, import scanning, resolution, the graph, the JSON contract),
  `application/extract.py` (the use case), `adapters/disk.py` (file walk,
  reads, git), `cli.py` (flags and the composition root).
- Tests: `layer-graph/tests/unit/`, against tiny fixture repositories in
  `layer-graph/tests/fixtures/`. A fixture's declaration is stored as
  `adherence.toml.in` and a dot directory as `dot.<name>`; the test copies
  the tree to a temporary root and restores the real names, so the
  adherence engine never discovers a fixture declaration as this
  repository's own.
- The declaration format is the adherence suite's:
  `docs/design/DESIGN.ARCH-ADHERENCE.md`, "The declaration". This tool
  reads it; it does not judge anything and does not share code with the
  engine in `adherence/`.

---

## Install

Nothing beyond `uv` on `PATH` (`brew install uv`). The runtime is pure
stdlib; the first run syncs a virtual environment under `layer-graph/.venv`.

To run the suite and the linters:

```
uv --directory layer-graph run pytest
uv --directory layer-graph run ruff check .
uv --directory layer-graph run ruff format --check .
uv --directory layer-graph run mypy
```

## Use

```
layer-graph [--root DIR] [--format json|summary] [--include-tests]
            [--no-barrels] [--out FILE]
```

- `--root DIR` -- the repository root. Default: the working directory.
- `--format json` -- the JSON document below, on stdout. This is the default.
- `--format summary` -- a short human table of nodes, edges and findings.
- `--include-tests` -- add the files of the `test` layer as nodes. By
  default the test layer is left out of the graph.
- `--no-barrels` -- do not see through barrels (below): an import that
  lands on a re-export-only file stays an edge to that file's node.
- `--out FILE` -- write the output to FILE instead of stdout.

Exit codes:

- `0` -- the graph was printed, findings or not. Findings never change the
  exit code.
- `1` -- an `adherence.toml` cannot be read (not TOML, an unknown layer name,
  a pattern that leaves its directory, a section of the wrong shape). The
  message on stderr names the file.
- `2` -- the repository holds no `adherence.toml`. Nothing is printed on
  stdout.

Examples:

```
bin/layer-graph --root ~/workplace/misvtt --format summary
bin/layer-graph --root ~/workplace/misvtt --out /tmp/misvtt-graph.json
```

## Disable

There is nothing to disable: the tool runs only when someone calls it. It
installs no hook, no schedule and no CI job. To remove it, delete
`bin/layer-graph` and `layer-graph/`.

## What it reads

- Declarations: every file named `adherence.toml` under the root. A
  declaration governs its own directory's subtree, and its patterns are
  relative to that directory. A path's governing declarations are read as
  one, root first: `[layers]` and `[runtimes]` are the union of what they
  say, and an `[override.layers]` or `[override.runtimes]` replaces the
  section for its own subtree. An `adherence.toml` that a declaration above
  it assigns to the `test` layer is test data, not a declaration.
- Layer of a file: the pattern that claims it. A literal path beats a
  glob, and a longer pattern beats a shorter one (the engine's rule). `**`
  crosses directories; `*`, `?` and `[...]` stay in one segment.
- Units: every file with extension `.ts`, `.tsx`, `.js`, `.mjs`, `.vue` or
  `.py` that a non-test layer claims (and the `test` layer with
  `--include-tests`).
- Skipped directories: `node_modules`, `.nuxt`, `.output`, `dist`, `build`,
  `__pycache__`, `.git`, `.venv`. Files in them are never units and never
  unassigned. A tsconfig in a skipped directory is still read when another
  tsconfig references it (Nuxt's `.nuxt/tsconfig.*.json`).

## Nodes and contexts

A node is (layer, context). Its id is `<layer>/<context>`, for example
`domain/timeline`.

- The static prefix of a pattern is its segments before the first segment
  with a wildcard. `packages/core/src/domain/**` has the prefix
  `packages/core/src/domain`.
- A file in a subdirectory of the prefix takes the first segment after the
  prefix as its context: `packages/core/src/domain/timeline/fold.ts` is in
  `domain/timeline`.
- A file directly in the prefix takes a label from the prefix: its last
  segment, skipping the generic names `src`, `lib` and `source`.
  `packages/adapters-memory/src/index.ts` is in `adapters/adapters-memory`.
- A single-file pattern takes the file stem: `packages/core/src/index.ts`
  gives the context `index`.
- When two patterns with different prefixes give one context name in one
  layer, each name gets a qualifier and a colon. The qualifier is the
  package directory name (the nearest directory above the prefix with a
  `package.json` or `pyproject.toml`). If the package names do not tell
  them apart, it is the first path segment where the prefixes differ. For
  example, `composition root/core:index` and
  `composition root/assistant:index`, or `composition root/server:composition`
  and `composition root/app:composition`.

## Imports and resolution

- TypeScript and JavaScript: `import ... from '...'`, `import '...'`,
  `export ... from '...'`, `import('...')` and `require('...')`, with type
  imports included. Comments and the contents of string and template
  literals are masked first, so import-like text in them does not count.
  For `.vue` files only the `<script>` blocks are read.
- Relative specifiers resolve against the importing file. The tool tries
  the path itself, a `.ts` or `.tsx` file for a `.js` specifier, the path
  with `.ts`, `.tsx`, `.js`, `.mjs` or `.vue`, and the directory's
  `index.*`.
- tsconfig `paths`: each `tsconfig.json` outside the skipped directories
  is a scope for the files under its directory. Its mappings come from the
  file, from the files it `extends` (relative only) and from its
  `references`. The nearest scope that has mappings applies. Comments
  and trailing commas in tsconfig files are allowed.
- Workspace packages: every `package.json` with a `name` outside the
  skipped directories. A bare name resolves through `exports["."]`, then
  `main`, then `src/index.*` or `index.*`. A subpath resolves through an
  exact `exports` key, then a `*` pattern key, then a directory join. A
  conditional export uses the first of `import`, `module`, `default`,
  `types`, `require`, `node`.
- Python: `import a.b`, `from a.b import c` and `from .x import y`, read
  with the `ast` module (imports inside functions included). Absolute
  imports resolve against the parent directory of every top-level package
  (a directory with `__init__.py` whose parent has none; this covers the
  `src` layout), then the importing file's directory, then the root. For
  `from m import n`, a name that is a submodule is the target; otherwise
  the module `m` is.
- A specifier that reaches no file in the repository is unresolved: an
  external package, the standard library, or a form the tool does not
  understand. It counts in `stats.unresolved` and makes no edge.
- An import that reaches a file in the repository that is not a unit (an
  unassigned file, a test file without `--include-tests`) makes no edge
  and is not counted as unresolved.

## Barrels

A barrel is a `.ts`, `.tsx`, `.js` or `.mjs` file whose statements are only
re-exports: `export * from`, `export * as ns from`, `export { ... } from`,
`export type { ... } from` and `export type * from`. A package's
`src/index.ts` that lists its contexts is the usual case. By default the
tool sees through barrels; `--no-barrels` turns this off.

- A named import that lands on a barrel is resolved by symbol. This
  covers `import { a, type B, c as d }`, a default import, and
  `export { a } from` in a unit file. Each imported name is followed
  through the barrel to the file that declares it:
  - `export { x as y } from` maps `y` to `x` in its target, and
    `export { default as Y } from` maps `Y` to that file's default.
  - `export * as ns from` binds `ns` to the whole target file. Behind a
    nested barrel that is every file it re-exports.
  - `export * from` targets are searched in order for the name. `export *`
    never carries `default`.
  - Nested barrels are followed; a cycle between barrels ends the search.
  - A non-barrel file declares a name when it exports it locally (`export
    function`, `const`, `let`, `var`, `class`, `interface`, `type`,
    `enum`, `const enum`, `namespace`, `module`, `export default`, or an
    `export { x }` list) or re-exports it.
- Fallback: a whole-module import (`import * as`, a side-effect import,
  `require`, `import()`, `export *` in a unit file), or a name the search
  cannot find (for example a default import that the barrel does not
  re-export by name), reaches every file behind the barrel, through
  nested barrels. `stats.barrelFallback` counts these statements.
- A redirected statement adds one to the edge for each distinct node it
  reaches, however many of its names land in that node.
- A barrel is never a unit. Its own re-exports are not counted in
  `stats.imports`, and it is in no node's `files`. A node whose only file
  was a barrel does not appear. A barrel that no layer claims is still
  listed as unassigned.
- `stats.viaBarrel` counts the import statements that landed on a
  barrel, resolved by symbol or by fallback.
- Why: a declaration that puts a package's barrel in the composition root
  would otherwise turn every `import ... from '@scope/core'` in an adapter
  into an outward edge, although the adapter depends on the files behind
  the barrel, not on the wiring.

## Edges and findings

- An edge aggregates the import statements from the files of one node to
  the files of another. Imports inside one node make no edge. A Python
  statement that reaches two submodules in one target node counts once for
  that edge.
- Direction comes from the layer order, outermost to innermost:
  composition root, adapters, application, ports, domain. The `test` layer
  is outside all of them.
  - `inward` -- the target layer is deeper.
  - `lateral` -- the same layer, a different context.
  - `outward` -- the target layer is shallower. This is a violation of the
    dependency rule.
- Findings:
  - `outward` -- every outward edge.
  - `cycles` -- every strongly connected component of more than one node
    (sorted node lists), then every pair of nodes that import each other
    and are not already listed as a component of their own.
  - `unassigned` -- every source file under a declaration that no layer
    claims.

## The JSON document (schema `layer-graph/1`)

Top-level keys, always in this order:

- `schema` -- the string `"layer-graph/1"`. Removing or changing a field
  below gets a new version; adding a field does not (`stats.viaBarrel` and
  `stats.barrelFallback` were added under `layer-graph/1`).
- `root` -- the absolute path of the repository root.
- `repo` -- `owner/name` from the `origin` remote, or `null`. It is `null`
  when the root is not itself the top of a git work tree.
- `commit` -- the `HEAD` commit sha, or `null` (same rule as `repo`).
- `declarations` -- the declaration paths read, relative to the root, root
  first, then by depth and name.
- `layers` -- the layer order, outermost first:
  `["composition root", "adapters", "application", "ports", "domain"]`.
- `runtimes` -- for each runtime any declaration names, the ids of the
  nodes with at least one file under that runtime's patterns.
- `nodes` -- a list, in layer order then context. Each node has:
  - `id` -- `<layer>/<context>`.
  - `layer` -- the layer name.
  - `context` -- the context name, qualified with `<qualifier>:` on a
    collision.
  - `files` -- the node's files, relative to the root, sorted.
  - `fileCount` -- the number of files.
  - `runtimes` -- the runtimes of the node's files, sorted.
- `edges` -- a list, sorted by `from` then `to`. Each edge has:
  - `from`, `to` -- node ids.
  - `imports` -- the number of import statements behind the edge.
  - `direction` -- `inward`, `lateral` or `outward`.
- `findings`:
  - `outward` -- a list of `{"from", "to", "imports"}`.
  - `cycles` -- a list of node-id lists.
  - `unassigned` -- a list of file paths.
- `stats`:
  - `files` -- the number of unit files.
  - `imports` -- the number of import statements in unit files.
  - `unresolved` -- how many of them reached no file in the repository.
  - `viaBarrel` -- how many of them were redirected through a barrel; `0`
    with `--no-barrels`.
  - `barrelFallback` -- how many of the redirected statements fell back to
    every file behind the barrel; `0` with `--no-barrels`.

## Known limits

- Symbol resolution reads export statements, not types: a name exported
  by `export =`, by a destructuring `export const { a } = ...`, or by a
  second declarator (`export const a = 1, b = 2` finds only `a`) is not
  found, and that import falls back to every file behind the barrel.
  Fallback edges are upper bounds; `stats.barrelFallback` says how many
  there are.
- Files, not regions: `[layers] regions` (line ranges) and section markers
  are ignored, so a one-file tool declared by region is one unit with no
  layer of its own. All other declaration sections are ignored too.
- Conflicts are not checked: two declarations that place one path in two
  layers are a conflict for the engine. Here the most specific pattern of
  the union wins.
- Escaped glob characters (`[*]`) are read as character classes, not
  literals.
- The TypeScript scan is a lexer, not a parser. A regular-expression
  literal that contains a quote can hide or invent an import. Imports
  inside a template literal's `${...}` are not seen.
- Not resolved: Nuxt and Vue auto-imports (components and composables used
  with no import statement), `#imports` and other virtual modules, Node
  subpath `imports` (`#name`), `baseUrl` lookups with no `paths` entry,
  non-relative `extends` in a tsconfig, and package exports conditions
  other than the six listed above.
- Python: namespace packages (no `__init__.py`) are found only through the
  importing file's directory or the root; `importlib` and `__import__`
  calls are not imports.
- The unassigned list covers every governed source file outside the
  layers, so a declaration that names only part of a large repository
  gives a long list.
- `layer-graph/tests` is not yet a `dist-ci.yml` job: the suite runs on the
  laptop only until a job is added to `gate`.
