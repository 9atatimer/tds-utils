"""The command line: flags, output formats and exit codes."""

import json
from pathlib import Path

import pytest

from layer_graph.cli import main
from tests.fixture_repo import copy_fixture

TOP_LEVEL = [
    "schema",
    "root",
    "repo",
    "commit",
    "declarations",
    "layers",
    "runtimes",
    "nodes",
    "edges",
    "findings",
    "stats",
]


def test_main_prints_versioned_json_with_the_contract_shape(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Given a declared repository, When run with --root, Then stdout is one
    JSON document in the layer-graph/1 shape and the exit is 0."""
    root = copy_fixture("ts_mono", tmp_path)
    assert main(["--root", str(root), "--no-barrels"]) == 0
    document = json.loads(capsys.readouterr().out)
    assert list(document) == TOP_LEVEL
    assert document["schema"] == "layer-graph/1"
    assert document["root"] == str(root.resolve())
    assert document["repo"] is None and document["commit"] is None
    assert document["layers"] == [
        "composition root",
        "adapters",
        "application",
        "ports",
        "domain",
    ]
    node = next(n for n in document["nodes"] if n["id"] == "domain/timeline")
    assert node == {
        "id": "domain/timeline",
        "layer": "domain",
        "context": "timeline",
        "files": ["packages/core/src/domain/timeline/fold.ts"],
        "fileCount": 1,
        "runtimes": ["app worker"],
    }
    assert {
        "from": "domain/table",
        "to": "application/table",
        "imports": 1,
        "direction": "outward",
    } in document["edges"]
    assert {"from": "domain/table", "to": "application/table", "imports": 1} in (
        document["findings"]["outward"]
    )
    assert document["findings"]["cycles"] == [["domain/table", "domain/timeline"]]
    assert document["findings"]["unassigned"] == ["scripts/tool.ts"]
    assert document["stats"] == {
        "files": 14,
        "imports": 20,
        "unresolved": 1,
        "viaBarrel": 0,
    }


def test_main_summary_names_nodes_edges_and_findings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Given --format summary, When run, Then the human table lists nodes,
    edges and findings."""
    root = copy_fixture("ts_mono", tmp_path)
    assert main(["--root", str(root), "--format", "summary", "--no-barrels"]) == 0
    out = capsys.readouterr().out
    assert "domain/timeline" in out
    assert "domain/table -> application/table" in out
    assert "outward" in out
    assert "cycle: domain/table <-> domain/timeline" in out
    assert "scripts/tool.ts" in out


def test_main_out_writes_the_file_not_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Given --out FILE, When run, Then the JSON lands in the file and stdout
    stays empty."""
    root = copy_fixture("py_repo", tmp_path)
    out = tmp_path / "graph.json"
    assert main(["--root", str(root), "--out", str(out)]) == 0
    assert capsys.readouterr().out == ""
    assert json.loads(out.read_text())["schema"] == "layer-graph/1"


def test_main_include_tests_adds_the_test_node(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Given --include-tests, When run, Then the test layer's nodes appear."""
    root = copy_fixture("py_repo", tmp_path)
    assert main(["--root", str(root), "--include-tests"]) == 0
    ids = {n["id"] for n in json.loads(capsys.readouterr().out)["nodes"]}
    assert "test/tests" in ids


def test_main_no_declaration_exits_2_saying_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Given a repository with no adherence.toml, When run, Then it exits 2
    and says there is no declaration."""
    root = copy_fixture("no_decl", tmp_path)
    assert main(["--root", str(root)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no adherence.toml" in captured.err


def test_main_unreadable_declaration_exits_1_naming_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Given an unreadable adherence.toml, When run, Then it exits 1 and the
    message names the file."""
    root = copy_fixture("bad_decl", tmp_path)
    assert main(["--root", str(root)]) == 1
    assert "adherence.toml" in capsys.readouterr().err


def test_main_defaults_root_to_working_directory(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Given no --root, When run from a declared repository, Then that
    directory is read."""
    root = copy_fixture("py_repo", tmp_path)
    monkeypatch.chdir(root)
    assert main([]) == 0
    assert json.loads(capsys.readouterr().out)["root"] == str(root.resolve())


def test_main_sees_through_barrels_by_default(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Given no --no-barrels, When run, Then imports through re-export-only
    files are redirected and counted in stats.viaBarrel."""
    root = copy_fixture("ts_mono", tmp_path)
    assert main(["--root", str(root)]) == 0
    document = json.loads(capsys.readouterr().out)
    assert document["stats"]["viaBarrel"] == 6
    assert document["findings"]["outward"] == [
        {"from": "domain/table", "to": "application/table", "imports": 1}
    ]
