"""The one seam: the repository being read (the disk, or a fake in a test)."""

from typing import Protocol


class RepoSource(Protocol):
    """A repository's files and identity, as the use case reads them."""

    @property
    def root(self) -> str:
        """The repository root as an absolute path."""
        ...

    def files(self) -> list[str]:
        """Every file under the root, as repository paths, sorted, with build
        and dependency directories left out."""
        ...

    def read_text(self, path: str) -> str | None:
        """A file's text by repository path; None when it cannot be read or
        lies outside the root."""
        ...

    def identity(self) -> tuple[str | None, str | None]:
        """The repository's owner/name from its git remote and its HEAD
        commit; None for each that is unknown."""
        ...
