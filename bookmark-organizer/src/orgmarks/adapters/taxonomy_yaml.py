"""Parse and write ``taxonomy.yml``.

Pydantic validates at this boundary; the domain only ever sees the frozen
``Taxonomy`` value object. Learned rules are appended with a ruamel.yaml
round-trip so human comments and key order survive.
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from ruamel.yaml import YAML

from orgmarks.domain.model import FolderPath, Rule, RuleMatch
from orgmarks.domain.taxonomy import Intent, LlmConfig, Taxonomy


class _Match(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: str | None = None
    url_prefix: str | None = None
    title_regex: str | None = None


class _Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    match: _Match
    folder: str
    ref: str | None = None
    source: Literal["human", "learned"] = "human"


class _Intent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    hint: str | None = None


class _Pin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str


class _Reference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root: str
    seeds: list[str] = Field(default_factory=list)


class _Llm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    confidence_threshold: float = 0.7
    model: str | None = None
    endpoint: str | None = None


class _Shape(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_umbrella_links: int = 3


class _TaxonomyModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    intents: list[_Intent]
    reference: _Reference
    pins: list[_Pin] = Field(default_factory=list)
    rules: list[_Rule] = Field(default_factory=list)
    llm: _Llm | None = None
    shape: _Shape = Field(default_factory=_Shape)
    triage_folder: str = "_triage"


def _to_rule(model: _Rule) -> Rule:
    return Rule(
        match=RuleMatch(
            domain=model.match.domain,
            url_prefix=model.match.url_prefix,
            title_regex=model.match.title_regex,
        ),
        folder=FolderPath.from_string(model.folder),
        ref=FolderPath.from_string(model.ref) if model.ref else None,
        source=model.source,
    )


def _to_taxonomy(model: _TaxonomyModel) -> Taxonomy:
    # Human rules sort before learned rules; order is otherwise stable.
    ordered = sorted(model.rules, key=lambda r: 0 if r.source == "human" else 1)
    llm = (
        LlmConfig(
            provider=model.llm.provider,
            confidence_threshold=model.llm.confidence_threshold,
            model=model.llm.model,
            endpoint=model.llm.endpoint,
        )
        if model.llm is not None
        else None
    )
    return Taxonomy(
        version=model.version,
        intents=tuple(Intent(name=i.name, hint=i.hint) for i in model.intents),
        pins=tuple(FolderPath.from_string(p.path) for p in model.pins),
        rules=tuple(_to_rule(r) for r in ordered),
        reference_root=FolderPath.from_string(model.reference.root),
        reference_seeds=tuple(model.reference.seeds),
        llm=llm,
        max_umbrella_links=model.shape.max_umbrella_links,
        triage_folder=model.triage_folder,
    )


def _safe_yaml() -> YAML:
    yaml = YAML(typ="safe")
    return yaml


def load_taxonomy_text(text: str) -> Taxonomy:
    """Parse taxonomy YAML text into a frozen Taxonomy (validated)."""
    data = _safe_yaml().load(text)
    model = _TaxonomyModel.model_validate(data)
    return _to_taxonomy(model)


def load_taxonomy(path: Path) -> Taxonomy:
    """Load and validate a taxonomy.yml file into a frozen Taxonomy."""
    return load_taxonomy_text(path.read_text(encoding="utf-8"))


def _rule_to_yaml(rule: Rule) -> dict[str, object]:
    match: dict[str, object] = {}
    if rule.match.domain is not None:
        match["domain"] = rule.match.domain
    if rule.match.url_prefix is not None:
        match["url_prefix"] = rule.match.url_prefix
    if rule.match.title_regex is not None:
        match["title_regex"] = rule.match.title_regex
    entry: dict[str, object] = {"match": match, "folder": str(rule.folder)}
    if rule.ref is not None:
        entry["ref"] = str(rule.ref)
    entry["source"] = rule.source
    return entry


def _match_items(match: object) -> dict[str, object]:
    if isinstance(match, dict):
        return {str(k): v for k, v in match.items()}
    return {}


def _same_rule(existing: object, candidate: dict[str, object]) -> bool:
    if not isinstance(existing, dict):
        return False
    return (
        _match_items(existing.get("match")) == _match_items(candidate.get("match"))
        and existing.get("folder") == candidate.get("folder")
        and existing.get("ref") == candidate.get("ref")
        and existing.get("source") == candidate.get("source")
    )


def write_learned_rules(path: Path, rules: Sequence[Rule]) -> None:
    """Append learned rules to taxonomy.yml, preserving comments and order.

    Idempotent: a rule already present (same match/folder/ref/source) is not
    appended again.
    """
    if not rules:
        return
    yaml = YAML()  # round-trip mode by default
    yaml.preserve_quotes = True
    with path.open(encoding="utf-8") as handle:
        data = yaml.load(handle)
    existing = data.get("rules")
    if existing is None:
        existing = []
        data["rules"] = existing
    for rule in rules:
        entry = _rule_to_yaml(rule)
        if not any(_same_rule(cur, entry) for cur in existing):
            existing.append(entry)
    buffer = io.StringIO()
    yaml.dump(data, buffer)
    path.write_text(buffer.getvalue(), encoding="utf-8")
