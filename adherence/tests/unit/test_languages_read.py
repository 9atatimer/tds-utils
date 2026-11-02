"""Which checks read which language (task-070; DESIGN.ARCH-ADHERENCE.md,
G11): shell's model holds regions, bodies and commands, so only the checks
over those read it, and every check reads the fully modelled languages."""

from __future__ import annotations

import pytest

from adherence.domain.checks.run import reads
from adherence.domain.qualities import catalog_check


@pytest.mark.parametrize("name", ["Anatomy", "Stub", "Dependency", "Complexity"])
def test_a_check_over_regions_bodies_or_commands_reads_shell(name: str) -> None:
    """Given a check that reads only regions, bodies or commands, When asked
    whether it reads a script, Then it does, in any shell dialect."""
    for path in ("bin/run.sh", "lib/x.bash", "macos/y.zsh"):
        assert reads(catalog_check(name), path), path


@pytest.mark.parametrize("name", ["Grep", "Arrow", "Swap", "Change", "Wiring"])
def test_a_check_over_facts_shell_lacks_does_not_read_it(name: str) -> None:
    """Given a check that needs imports, references or types, When asked
    whether it reads a script, Then it does not."""
    assert not reads(catalog_check(name), "bin/run.sh")


@pytest.mark.parametrize("path", ["src/a.py", "lib/b.ts", "lib/c.mjs", "README"])
def test_every_check_reads_a_fully_modelled_language(path: str) -> None:
    """Given a Python, TypeScript or JavaScript file, or one in no language,
    When any check is asked whether it reads it, Then it does."""
    assert reads(catalog_check("Grep"), path)
    assert reads(catalog_check("Anatomy"), path)
