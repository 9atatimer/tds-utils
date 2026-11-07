"""Fixture trees hold their declaration as `adherence.fixture.toml`, never
`adherence.toml`: a declaration file in any directory of this repository
governs that subtree for the suite judging the repository itself
(DESIGN.ARCH-ADHERENCE.md, The declaration), and a fixture -- some
deliberately flawed, one deliberately unreadable -- is an asset, never a
sub-project. A test plants a fixture tree under its real name."""

from __future__ import annotations

import shutil
from pathlib import Path

from adherence.domain.declaration import DECLARATION_PATH
from tests.git_kit import make_repository

FIXTURE_DECLARATION = "adherence.fixture.toml"


def plant(source: Path, root: Path) -> None:
    """The fixture tree copied over `root`, each fixture declaration under
    the name the suite reads."""
    shutil.copytree(source, root, dirs_exist_ok=True)
    for planted in sorted(root.rglob(FIXTURE_DECLARATION)):
        planted.replace(planted.with_name(DECLARATION_PATH))


def planted_repository(source: Path, root: Path) -> Path:
    """A git repository at `root` whose working tree holds the fixture tree,
    planted."""
    make_repository(root, base={}, staged={}, working={})
    plant(source, root)
    return root
