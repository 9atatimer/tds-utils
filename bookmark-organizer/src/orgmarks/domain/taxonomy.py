"""The ``Taxonomy`` value object: the parsed, frozen view of taxonomy.yml.

Parsing and validation happen in ``adapters/taxonomy_yaml.py`` (Pydantic at
the boundary); the domain only ever sees this immutable value. No YAML, no
Pydantic, and no vendor detail leaks in here.
"""

from __future__ import annotations

from dataclasses import dataclass

from orgmarks.domain.model import FolderPath, Rule


@dataclass(frozen=True, slots=True)
class Intent:
    """A top-level folder seed. ``hint`` is passed verbatim to the LLM."""

    name: str
    hint: str | None = None


@dataclass(frozen=True, slots=True)
class LlmConfig:
    """LLM provider selection and the triage threshold."""

    provider: str
    confidence_threshold: float = 0.7
    model: str | None = None
    endpoint: str | None = None


@dataclass(frozen=True, slots=True)
class Taxonomy:
    """Human hints plus learned rules, as a frozen value.

    ``rules`` are stored human-before-learned so first-match evaluation
    always prefers a human rule over a machine-appended one.
    """

    version: int
    intents: tuple[Intent, ...]
    pins: tuple[FolderPath, ...]
    rules: tuple[Rule, ...]
    reference_root: FolderPath
    reference_seeds: tuple[str, ...] = ()
    llm: LlmConfig | None = None
    max_umbrella_links: int = 3
    triage_folder: str = "_triage"

    def intent_names(self) -> tuple[str, ...]:
        """The declared intent names, in display order."""
        return tuple(intent.name for intent in self.intents)

    def is_intent_path(self, path: FolderPath) -> bool:
        """True if ``path`` roots at a declared intent."""
        return path.depth >= 1 and path.parts[0] in self.intent_names()
