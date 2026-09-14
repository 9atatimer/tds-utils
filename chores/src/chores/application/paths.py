"""Where things live on this machine, resolved once at the composition root."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Paths:
    chores_home: str
    state_dir: str
    data_dir: str

    def forbidden_for_cwd(self) -> tuple[str, str]:
        """Directories a chore's cwd may neither be inside nor contain."""
        return (self.chores_home, self.state_dir)
