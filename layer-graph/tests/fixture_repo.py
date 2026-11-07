"""Copy a fixture repository from tests/fixtures/ into a temporary root.

Fixture trees store what git or the adherence engine would otherwise act on
under inert names, and the copy restores the real ones:

- a file ending `.in` loses the suffix (`adherence.toml.in` ->
  `adherence.toml`), so the engine never discovers a fixture declaration as
  this repository's own;
- a path segment starting `dot.` becomes a dot directory (`dot.nuxt` ->
  `.nuxt`), the repository's own dotfile convention.
"""

import shutil
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def _restored(name: str) -> str:
    name = "." + name.removeprefix("dot.") if name.startswith("dot.") else name
    return name.removesuffix(".in")


def copy_fixture(name: str, destination: Path) -> Path:
    """The fixture `name` copied under `destination`, real names restored."""
    source = FIXTURES / name
    root = destination / name
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        target = root.joinpath(*(_restored(part) for part in relative.parts))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    return root
