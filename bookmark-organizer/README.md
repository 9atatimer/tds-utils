# orgmarks

Groom a Chrome bookmark export around task intent. `orgmarks` takes a Chrome
bookmark export, reorganizes it around task intent (work, fun, self-education,
writing) using deterministic rules first and an LLM second, and emits a cleaned
tree for re-import -- guided by a human-editable YAML taxonomy.

Design: [../docs/design/BOOKMARK-ORGANIZER.DESIGN.md](../docs/design/BOOKMARK-ORGANIZER.DESIGN.md).

## Install

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```
cd bookmark-organizer
uv sync
```

The launcher shim `bin/orgmarks` (on `$PATH` via tds-utils) bootstraps through
`uv run` automatically.

## Usage

```
orgmarks plan  --input FILE      --taxonomy taxonomy.yml
orgmarks plan  --from-profile FILE --taxonomy taxonomy.yml
orgmarks apply --input FILE      --taxonomy taxonomy.yml [--output-dir DIR]
```

- `--input` -- a Netscape HTML export (chrome://bookmarks -> Export).
- `--from-profile` -- a path to a Chrome `Bookmarks` JSON file (read-only; the
  profile is never written).
- `--taxonomy` -- your taxonomy.yml (see `taxonomy.example.yml`).
- `--restructure` -- let the LLM propose a reworked folder tree.

`plan` is read-only and prints the move/create/merge report. `apply` writes
`bookmarks-organized-<date>.html` and appends any `source: learned` rules back
into your taxonomy.yml (comments and key order are preserved).

## Import caveat

Chrome imports HTML into a new `Imported` folder rather than merging. The
manual step is: import the generated HTML, spot-check it, delete the old roots,
then drag the new tree up. Direct profile writes are out of scope for v1.

## Taxonomy

The taxonomy file seeds intents, pins, deterministic rules, the reference-index
root, and the LLM provider. It grows over time as high-confidence LLM
assignments are learned back as rules, so each run needs fewer LLM calls than
the last.

`taxonomy.example.yml` here uses placeholder URLs only. Your real taxonomy.yml
contains private URLs and interests -- keep it in a PRIVATE repo, never in
tds-utils.

Provider selection lives under `llm:` in the taxonomy. Default is `claude-cli`
(rides the local `claude` CLI). An absent `llm:` block runs rules-only and
sends residue to `_triage`; an unreachable provider degrades the same way
rather than failing the run.

## Scope (v1)

No dead-link checking, no Chrome profile writes, no browser automation, no
bookmark database. Chrome stays the system of record; orgmarks is a batch
groomer.
