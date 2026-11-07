"""The errors layer-graph reports to its caller."""


class LayerGraphError(Exception):
    """Base for every error layer-graph raises on purpose."""


class DeclarationUnreadable(LayerGraphError):
    """An adherence.toml that cannot be read; the message names the file."""


class NoDeclaration(LayerGraphError):
    """A repository with no adherence.toml in it."""
