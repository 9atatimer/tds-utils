"""DefinitionsLoader reads $CHORES_HOME into Definitions (Subsystem 1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from chores.adapters.definitions import DefinitionsLoader
from chores.domain.budget import Ceiling
from chores.domain.kinds import Kind
from chores.ports.backends import Price

from ._harness import COMMAND, FullHarness


def write_home(home: Path) -> None:
    (home / "chores").mkdir(parents=True)
    (home / "chores" / "brand.md").write_text(
        "---\nname: brand\nschedule: '0 3 * * *'\nkind: prompt\nbackend: gw\n"
        "budget: {usd: 0.10, tokens: 4000}\n---\nSummarize the logs.\n"
    )
    (home / "chores" / "tidy.md").write_text(
        "---\nname: tidy\nschedule: '*/5 * * * *'\nkind: command\n"
        "command: [ls, -la]\n---\n"
    )
    (home / "chores" / "broken.md").write_text(
        "---\nname: broken\nkind: prompt\n---\nx\n"
    )
    (home / "chores" / "notes.txt").write_text("ignored")
    (home / "backends.yaml").write_text(
        "backends:\n"
        "  gw:\n    type: openai-compat\n    base_url: https://example.invalid/v1\n"
        "    auth_header: cf-aig-authorization\n    credential_ref: op://v/i/password\n"
        "    model: openai/gpt-4o-mini\n"
        "    prices: {openai/gpt-4o-mini: {in_per_1m: 0.15, out_per_1m: 0.60}}\n"
        "    ceiling: {usd: 2.0}\n"
        "  local:\n    type: ollama\n    model: llama3.2\n"
    )
    (home / "config.yaml").write_text(
        "ceiling: {usd: 5.0}\ntick_interval_sec: 30\nfailure_threshold: 2\n"
    )


def test_loader_parses_chores_backends_config_and_reports_invalid(
    tmp_path: Path,
) -> None:
    """Given a populated home, Then chores, backends, config and invalid load."""
    write_home(tmp_path)
    defs = DefinitionsLoader(tmp_path, revision_reader=lambda _: "deadbeef").load()

    names = {c.name: c for c in defs.chores}
    assert set(names) == {"brand", "tidy"}
    assert (
        names["brand"].kind is Kind.PROMPT
        and names["brand"].body == "Summarize the logs.\n"
    )
    assert names["tidy"].command == ("ls", "-la")
    assert [i.name for i in defs.invalid] == ["broken"]
    assert "schedule" in defs.invalid[0].error
    assert defs.backends["gw"].type == "openai-compat"
    assert defs.backends["gw"].prices["openai/gpt-4o-mini"] == Price(0.15, 0.60)
    assert defs.backends["gw"].ceiling == Ceiling(usd=2.0)
    assert defs.backends["local"].base_url is None
    assert defs.config.ceiling == Ceiling(usd=5.0)
    assert defs.config.tick_interval_sec == 30 and defs.config.failure_threshold == 2
    assert defs.config.retention_days == 90
    assert defs.revision == "deadbeef"


def test_loader_tolerates_an_empty_home(tmp_path: Path) -> None:
    """Given no files at all, Then no chores, no backends, default config, untracked."""
    defs = DefinitionsLoader(tmp_path, revision_reader=lambda _: "untracked").load()
    assert defs.chores == [] and defs.backends == {} and defs.invalid == []
    assert defs.config.tick_interval_sec == 60
    assert defs.revision == "untracked"


def test_loader_reports_malformed_yaml_as_errors_not_exceptions(tmp_path: Path) -> None:
    """Given a backends.yaml that is not a mapping, Then an error line, not a crash."""
    (tmp_path / "backends.yaml").write_text("- just\n- a list\n")
    (tmp_path / "chores").mkdir()
    (tmp_path / "chores" / "x.md").write_text("no front matter here\n")
    defs = DefinitionsLoader(tmp_path, revision_reader=lambda _: "r").load()
    assert any("backends.yaml" in e for e in defs.errors)
    assert [i.name for i in defs.invalid] == ["x"]


def test_source_returns_raw_file(tmp_path: Path) -> None:
    write_home(tmp_path)
    loader = DefinitionsLoader(tmp_path, revision_reader=lambda _: "r")
    assert (loader.source("tidy") or "").startswith("---\nname: tidy")
    assert loader.source("nope") is None


def test_malformed_prices_is_a_reported_error_not_a_crash(tmp_path: Path) -> None:
    from chores.adapters.definitions import DefinitionsLoader

    (tmp_path / "chores").mkdir()
    (tmp_path / "backends.yaml").write_text(
        "backends:\n  gw:\n    type: ollama\n    prices: []\n"
    )
    defs = DefinitionsLoader(tmp_path, revision_reader=lambda _: "r").load()
    assert any("prices" in e for e in defs.errors) and defs.backends == {}


def test_prices_must_be_finite_and_non_negative(tmp_path: Path) -> None:
    from chores.ports.backends import Price

    for bad in (float("nan"), float("inf"), -0.01):
        with pytest.raises(ValueError):
            Price(in_per_1m=bad, out_per_1m=1.0)
    h = FullHarness(tmp_path, chores={"tidy": COMMAND})
    (tmp_path / "home" / "backends.yaml").write_text(
        "backends:\n  gw:\n    type: openai-compat\n    model: m\n"
        "    base_url: https://gw\n"
        "    prices: {m: {in_per_1m: .nan, out_per_1m: -1}}\n"
    )
    defs = h.definitions.load()
    assert any("price for m" in e for e in defs.errors)


def test_loader_rejects_unknown_ceiling_keys_and_non_bool_requires_network(
    tmp_path: Path,
) -> None:
    h = FullHarness(tmp_path, chores={"tidy": COMMAND})
    (tmp_path / "home" / "backends.yaml").write_text(
        "backends:\n  a:\n    type: ollama\n    model: m\n"
        "    ceiling: {usd: 1, usdd: 2}\n"
        "  b:\n    type: ollama\n    model: m\n    requires_network: 'false'\n"
    )
    errors = h.definitions.load().errors
    assert any("unknown dimensions ['usdd']" in e for e in errors)
    assert any("requires_network must be true or false" in e for e in errors)


def test_prompt_body_is_verbatim_and_bad_utf8_is_reported(tmp_path: Path) -> None:
    from chores.adapters.definitions import DefinitionsLoader, split_front_matter

    _data, body = split_front_matter("---\nname: p\n---\n\n  keep me  \n\n")
    assert body == "\n  keep me  \n\n"
    home = tmp_path / "home"
    (home / "chores").mkdir(parents=True)
    (home / "chores" / "bad.md").write_bytes(b"---\nname: bad\n---\n\xff\xfe")
    (home / "backends.yaml").write_bytes(b"\xff")
    (home / "config.yaml").write_bytes(b"\xff")
    defs = DefinitionsLoader(home, revision_reader=lambda _: "r").load()
    assert [i.name for i in defs.invalid] == ["bad"]
    assert any("backends.yaml" in e for e in defs.errors)
    assert defs.config_error is not None


def test_unreadable_yaml_is_a_reported_error(tmp_path: Path) -> None:
    """backends.yaml or config.yaml that exists but cannot be read (here: a
    directory) is a configuration error in the report, not a traceback."""
    import shutil

    h = FullHarness(tmp_path, chores={"tidy": COMMAND})
    home = Path(h.paths.chores_home)
    for name in ("backends.yaml", "config.yaml"):
        target = home / name
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink(missing_ok=True)
        target.mkdir()
    defs = h.definitions.load()
    assert any("backends.yaml" in e for e in defs.errors)
    assert defs.config_error is not None and "config.yaml" in defs.config_error
