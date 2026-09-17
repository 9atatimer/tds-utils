"""DefinitionsLoader -- $CHORES_HOME on disk as a DefinitionsPort
(CHORES.DESIGN.md Subsystem 1). YAML front-matter and config parsing happen
here, at the edge; the domain's ``Chore.from_mapping`` does the validating.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path

import yaml

from chores.domain.budget import Ceiling, InvalidBudget
from chores.domain.chore import Chore, InvalidChore
from chores.ports.backends import BackendConfig, Price
from chores.ports.definitions import Definitions, GlobalConfig, InvalidDefinition

_FRONT_MATTER_FENCE = "---"
_GIT_TIMEOUT_SEC = 5


# --- helpers -----------------------------------------------------------------


def split_front_matter(text: str) -> tuple[Mapping[str, object], str]:
    """Split ``---\\n<yaml>\\n---\\n<body>``; raise InvalidChore without a fence."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != _FRONT_MATTER_FENCE:
        raise InvalidChore("missing front-matter fence")
    for i in range(1, len(lines)):
        if lines[i].strip() == _FRONT_MATTER_FENCE:
            data = yaml.safe_load("".join(lines[1:i])) or {}
            if not isinstance(data, Mapping):
                raise InvalidChore("front-matter must be a mapping")
            return data, "".join(lines[i + 1 :]).strip()
    raise InvalidChore("unterminated front-matter")


def git_revision(home: Path) -> str:
    """``<sha>``, ``<sha>-dirty`` or ``untracked`` (design: definition_rev)."""
    try:
        head = subprocess.run(
            ["git", "-C", str(home), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SEC,
            check=False,
        )
        if head.returncode != 0:
            return "untracked"
        status = subprocess.run(
            ["git", "-C", str(home), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SEC,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "untracked"
    sha = head.stdout.strip()
    return f"{sha}-dirty" if status.stdout.strip() else sha


def _ceiling(raw: object, *, where: str) -> Ceiling:
    if raw is None:
        return Ceiling()
    if not isinstance(raw, Mapping):
        raise ValueError(f"{where}: ceiling must be a map")
    try:
        return Ceiling(
            tokens=None if raw.get("tokens") is None else int(str(raw["tokens"])),
            usd=None if raw.get("usd") is None else float(str(raw["usd"])),
            turns=None if raw.get("turns") is None else int(str(raw["turns"])),
        )
    except (InvalidBudget, ValueError) as e:
        raise ValueError(f"{where}: {e}") from e


def _backend(name: str, raw: object) -> BackendConfig:
    if not isinstance(raw, Mapping) or not isinstance(raw.get("type"), str):
        raise ValueError(f"backends.yaml: {name} needs a string type")
    prices: dict[str, Price] = {}
    raw_prices = raw.get("prices")
    if raw_prices is None:
        raw_prices = {}
    if not isinstance(raw_prices, Mapping):
        raise ValueError(
            f"backends.yaml: {name} prices must be a map of model -> price"
        )
    for model, p in raw_prices.items():
        if not isinstance(p, Mapping):
            raise ValueError(f"backends.yaml: {name} price for {model} must be a map")
        try:
            prices[str(model)] = Price(
                in_per_1m=float(str(p["in_per_1m"])),
                out_per_1m=float(str(p["out_per_1m"])),
            )
        except (KeyError, ValueError) as e:
            raise ValueError(f"backends.yaml: {name} price for {model}: {e}") from e
    known = {
        "type",
        "model",
        "base_url",
        "auth_header",
        "credential_ref",
        "prices",
        "ceiling",
        "requires_network",
    }
    requires_network = raw.get("requires_network")
    return BackendConfig(
        name=name,
        type=str(raw["type"]),
        model=None if raw.get("model") is None else str(raw["model"]),
        base_url=None if raw.get("base_url") is None else str(raw["base_url"]),
        auth_header=None if raw.get("auth_header") is None else str(raw["auth_header"]),
        credential_ref=(
            None if raw.get("credential_ref") is None else str(raw["credential_ref"])
        ),
        prices=prices,
        ceiling=_ceiling(raw.get("ceiling"), where=f"backends.yaml: {name}"),
        requires_network=requires_network
        if isinstance(requires_network, bool)
        else None,
        extra={k: v for k, v in raw.items() if k not in known},
    )


def _config(raw: object) -> GlobalConfig:
    if raw is None:
        return GlobalConfig()
    if not isinstance(raw, Mapping):
        raise ValueError("config.yaml: must be a map")
    defaults = GlobalConfig()
    ints = {
        "tick_interval_sec",
        "missed_grace_sec",
        "failure_threshold",
        "retention_days",
        "secret_timeout_sec",
        "kill_grace_sec",
        "max_run_dir_bytes",
    }
    values: dict[str, object] = {}
    for key in ints:
        if key in raw:
            value = raw[key]
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"config.yaml: {key} must be a positive integer")
            values[key] = value
    if "count_subscription_usd" in raw:
        if not isinstance(raw["count_subscription_usd"], bool):
            raise ValueError(
                "config.yaml: count_subscription_usd must be true or false"
            )
        values["count_subscription_usd"] = raw["count_subscription_usd"]
    unknown = set(raw) - ints - {"count_subscription_usd", "ceiling"}
    if unknown:
        raise ValueError(f"config.yaml: unknown keys {sorted(unknown)}")
    return GlobalConfig(
        ceiling=_ceiling(raw.get("ceiling"), where="config.yaml"),
        tick_interval_sec=int(
            str(values.get("tick_interval_sec", defaults.tick_interval_sec))
        ),
        missed_grace_sec=int(
            str(values.get("missed_grace_sec", defaults.missed_grace_sec))
        ),
        failure_threshold=int(
            str(values.get("failure_threshold", defaults.failure_threshold))
        ),
        retention_days=int(str(values.get("retention_days", defaults.retention_days))),
        count_subscription_usd=bool(
            values.get("count_subscription_usd", defaults.count_subscription_usd)
        ),
        secret_timeout_sec=int(
            str(values.get("secret_timeout_sec", defaults.secret_timeout_sec))
        ),
        kill_grace_sec=int(str(values.get("kill_grace_sec", defaults.kill_grace_sec))),
        max_run_dir_bytes=int(
            str(values.get("max_run_dir_bytes", defaults.max_run_dir_bytes))
        ),
    )


def _normalise_cwd(raw: str) -> str:
    """Expand ~ and resolve symlinks and .. so the cwd rule sees a real path."""
    return os.path.realpath(os.path.expanduser(raw))


def _load_yaml(path: Path) -> object:
    if not path.exists():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# --- the adapter -------------------------------------------------------------


class DefinitionsLoader:
    def __init__(
        self, home: Path, *, revision_reader: Callable[[Path], str] = git_revision
    ) -> None:
        self.home = home
        self._revision_reader = revision_reader

    def load(self) -> Definitions:
        chores: list[Chore] = []
        invalid: list[InvalidDefinition] = []
        errors: list[str] = []
        for path in sorted((self.home / "chores").glob("*.md")):
            try:
                data, body = split_front_matter(path.read_text(encoding="utf-8"))
                if isinstance(data.get("cwd"), str):
                    data = {**data, "cwd": _normalise_cwd(str(data["cwd"]))}
                chore = Chore.from_mapping(data, body=body)
                if chore.name != path.stem:
                    raise InvalidChore(f"name {chore.name!r} must equal the file stem")
                chores.append(chore)
            except (InvalidChore, yaml.YAMLError, OSError) as e:
                invalid.append(InvalidDefinition(name=path.stem, error=str(e)))
        backends: dict[str, BackendConfig] = {}
        try:
            raw_backends = _load_yaml(self.home / "backends.yaml")
            if raw_backends is not None:
                if not isinstance(raw_backends, Mapping) or not isinstance(
                    raw_backends.get("backends"), Mapping
                ):
                    raise ValueError(
                        "backends.yaml: expected a top-level 'backends' map"
                    )
                for name, raw in raw_backends["backends"].items():
                    backends[str(name)] = _backend(str(name), raw)
        except (ValueError, yaml.YAMLError, KeyError) as e:
            errors.append(f"backends.yaml: {e}")
        config = GlobalConfig()
        try:
            config = _config(_load_yaml(self.home / "config.yaml"))
        except (ValueError, yaml.YAMLError) as e:
            errors.append(str(e))
        return Definitions(
            chores=chores,
            invalid=invalid,
            backends=backends,
            config=config,
            revision=self._revision_reader(self.home),
            errors=tuple(errors),
        )

    def source(self, name: str) -> str | None:
        path = self.home / "chores" / f"{name}.md"
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")
