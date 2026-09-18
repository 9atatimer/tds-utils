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
    """Two of the three roots lie inside one another. The data root holds
    default workspaces a chore writes into, the state root is what chores
    writes, and the definitions root is the git-tracked tree it must never
    write to; any containment lets one bleed into another."""


@dataclass(frozen=True, slots=True)
class Paths:
    chores_home: str
    state_dir: str
    data_dir: str

    def __post_init__(self) -> None:
        # No two roots may contain one another: the data root holds default
        # workspaces a chore writes into, the state root is what chores
        # writes, and the definitions root is what it must never write to.
        roots = (
            ("definitions", self.chores_home),
            ("state", self.state_dir),
            ("data", self.data_dir),
        )
        for i, (name_a, a) in enumerate(roots):
            for name_b, b in roots[i + 1 :]:
                if is_under(a, b) or is_under(b, a):
                    raise OverlappingRoots(
                        f"{name_a} dir {a} overlaps the {name_b} dir {b}"
                    )

    def forbidden_for_cwd(self) -> tuple[str, str]:
        """Directories a chore's cwd may neither be inside nor contain."""
        return (self.chores_home, self.state_dir)
