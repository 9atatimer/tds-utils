"""Where things live on this machine, resolved once at the composition root.

The three roots arrive already canonical (the wiring realpaths them, as the
loader realpaths every chore ``cwd``) so the containment checks here and in
``check_bindings`` compare like with like; a symlinked ``XDG_STATE_HOME``
cannot be reached through its target.
"""

from __future__ import annotations

from dataclasses import dataclass

from chores.domain.chore import is_under


class OverlappingRoots(ValueError):
    """The data root (default workspaces) lies inside, or contains, the state
    or definitions root: a command chore's default cwd could then write into
    ``runs/``, the ledger or the sentries."""


@dataclass(frozen=True, slots=True)
class Paths:
    chores_home: str
    state_dir: str
    data_dir: str

    def __post_init__(self) -> None:
        for name, root in (
            ("state", self.state_dir),
            ("definitions", self.chores_home),
        ):
            if is_under(self.data_dir, root) or is_under(root, self.data_dir):
                raise OverlappingRoots(
                    f"data dir {self.data_dir} overlaps the {name} dir {root}"
                )

    def forbidden_for_cwd(self) -> tuple[str, str]:
        """Directories a chore's cwd may neither be inside nor contain."""
        return (self.chores_home, self.state_dir)
