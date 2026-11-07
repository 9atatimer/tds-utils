# Test fixtures

Each directory here is a repository tree the engine's tests measure. A
fixture's declaration is named `adherence.fixture.toml`, never
`adherence.toml`: the engine reads every `adherence.toml` in a repository
as a sub-project's declaration (DESIGN.ARCH-ADHERENCE, The declaration),
and these trees sit outside every layer the root declaration names, so a
fixture under the real name would be read as part of this repository's
own declaration, and the deliberately unreadable one would stop every
run. `tests/fixture_tree.py` plants a fixture into a temporary tree under
the real name when a test needs the engine to read it.
