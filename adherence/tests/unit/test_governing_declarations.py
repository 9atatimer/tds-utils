"""domain/declaration: nested declarations read as one -- each file's
paths under its own directory, the governing declarations of a path
merged, and every conflict refused (DESIGN.ARCH-ADHERENCE.md, The
declaration; Behaviors, A sub-project's declaration governs its subtree
through An override of nothing is refused)."""

from __future__ import annotations

from collections.abc import Collection

import pytest

from adherence.domain.declaration import (
    Declaration,
    DeclarationFile,
    DeclarationUnreadable,
    governing_declarations,
    layer_of,
    parse_declaration,
    parse_file,
)
from adherence.domain.model import Layer, Region

ROOT_RADAR = b'[radar]\npath = "lmde/TECH_RADAR.md"\n'
PKG = b"""
[layers]
domain = ["src/domain/**"]
adapters = ["src/adapters/**"]

[records]
design = "docs/DESIGN.md"
architecture = "docs/ARCHITECTURE.md"
"""


def _file(path: str, text: bytes) -> DeclarationFile:
    parsed = parse_file(path, text)
    assert isinstance(parsed, DeclarationFile), parsed
    return parsed


def _merged(
    files: dict[str, bytes], tree: Collection[str] = ()
) -> Declaration | DeclarationUnreadable:
    return governing_declarations([_file(p, t) for p, t in files.items()], tree)


def _declared(files: dict[str, bytes], tree: Collection[str] = ()) -> Declaration:
    merged = _merged(files, tree)
    assert isinstance(merged, Declaration), merged
    return merged


def test_a_sub_project_declaration_assigns_only_its_subtree() -> None:
    """Given a declaration in pkg-a whose layer globs are relative to it,
    When a path's layer is asked, Then every path under pkg-a is assigned by
    it and a path elsewhere with the same relative shape is not."""
    declaration = _declared({"pkg-a/adherence.toml": PKG})

    assert layer_of("pkg-a/src/domain/rules.py", None, declaration) is Layer.DOMAIN
    assert layer_of("src/domain/rules.py", None, declaration) is None
    assert layer_of("pkg-b/src/domain/rules.py", None, declaration) is None
    assert declaration.governs("pkg-a/src/x.py")
    assert not declaration.governs("pkg-b/src/x.py")
    assert not declaration.governs("pkg-ab/x.py")


def test_every_path_a_declaration_names_resolves_under_its_directory() -> None:
    """Given a sub-project declaration naming records, a radar, a runtime,
    a region and an exemption unit, When it is read, Then each is a path
    under the sub-project's directory."""
    declaration = _declared(
        {
            "pkg/adherence.toml": PKG
            + b'[radar]\npath = "RADAR.md"\n'
            + b'[runtimes]\ncli = ["src/**"]\n'
            + b'[[layers.regions]]\nfile = "tool.sh"\nlayer = "domain"\n'
            + b"lines = [1, 3]\n"
            + b'[[exemptions]]\ncheck = "Stub"\nunit = "src/x.py"\nreason = "r"\n'
        }
    )

    assert declaration.records_for("pkg/src/x.py") is not None
    records = declaration.records_for("pkg/src/x.py")
    assert records is not None and records.design == "pkg/docs/DESIGN.md"
    assert declaration.radar_for("pkg/src/x.py") == "pkg/RADAR.md"
    assert declaration.records_for("elsewhere.py") is None
    [runtime] = declaration.runtimes
    assert runtime.patterns == ("pkg/src/**",)
    assert runtime.source == "pkg/adherence.toml"
    assert declaration.layers.regions == (Region("pkg/tool.sh", 1, 3, Layer.DOMAIN),)
    [exemption] = declaration.exemptions
    assert exemption.unit == "pkg/src/x.py"


@pytest.mark.parametrize(
    "path", ["../outside/**", "/etc/**", "src/../../x.py", "src/.."]
)
def test_a_path_that_escapes_its_directory_is_unreadable(path: str) -> None:
    """Given a declaration naming a path with a `..` segment or a leading
    slash, When it is read, Then it is unreadable, naming the file and that
    it escapes its directory."""
    parsed = parse_file(
        "pkg/adherence.toml", f'[layers]\ndomain = ["{path}"]\n'.encode()
    )

    assert isinstance(parsed, DeclarationUnreadable)
    assert "pkg/adherence.toml" in parsed.reason
    assert "escapes its directory" in parsed.reason


def test_governing_declarations_union_their_layers() -> None:
    """Given a root declaration and a sub-project one, each assigning
    layers, When they are read as one, Then a path takes the assignment of
    whichever file assigns it."""
    declaration = _declared(
        {
            "adherence.toml": b'[layers]\ntest = ["tests/**"]\n',
            "pkg/adherence.toml": PKG,
        },
        tree=("tests/t.py", "pkg/src/domain/r.py"),
    )

    assert layer_of("tests/t.py", None, declaration) is Layer.TEST
    assert layer_of("pkg/src/domain/r.py", None, declaration) is Layer.DOMAIN
    assert declaration.governed == ("", "pkg")


def test_governing_declarations_are_read_as_one() -> None:
    """Given a root declaration naming the radar and a sub-project one
    naming its layers and design record, When they are read as one, Then a
    unit in the sub-project is under those layers, that record and that
    radar."""
    declaration = _declared({"adherence.toml": ROOT_RADAR, "pkg/adherence.toml": PKG})

    unit = "pkg/src/domain/r.py"
    assert layer_of(unit, None, declaration) is Layer.DOMAIN
    records = declaration.records_for(unit)
    assert records is not None and records.design == "pkg/docs/DESIGN.md"
    assert declaration.radar_for(unit) == "lmde/TECH_RADAR.md"


def test_an_override_replaces_a_parents_radar_for_its_subtree_only() -> None:
    """Given a root declaration naming a radar and a sub-project one naming
    its own under [override.radar], When they are read as one, Then the
    sub-project's paths are held to its radar and the rest to the root's."""
    declaration = _declared(
        {
            "adherence.toml": ROOT_RADAR,
            "pkg/adherence.toml": b'[override.radar]\npath = "RADAR.md"\n',
        }
    )

    assert declaration.radar_for("pkg/src/x.py") == "pkg/RADAR.md"
    assert declaration.radar_for("other/x.py") == "lmde/TECH_RADAR.md"
    assert declaration.radar == "lmde/TECH_RADAR.md"


def test_an_override_of_layers_voids_the_parents_for_its_subtree() -> None:
    """Given a root declaration placing every Python file in the domain and
    a sub-project that overrides [layers], When they are read as one, Then
    under the sub-project only its own assignments hold, and the root's
    still hold elsewhere."""
    declaration = _declared(
        {
            "adherence.toml": b'[layers]\ndomain = ["**/*.py"]\n',
            "pkg/adherence.toml": b'[override.layers]\nadapters = ["io/**"]\n',
        },
        tree=("pkg/io/a.py", "pkg/core.py", "lib/x.py"),
    )

    assert layer_of("pkg/io/a.py", None, declaration) is Layer.ADAPTERS
    assert layer_of("pkg/core.py", None, declaration) is None
    assert layer_of("lib/x.py", None, declaration) is Layer.DOMAIN


def test_two_files_placing_one_real_path_in_two_layers_are_unreadable() -> None:
    """Given a root declaration and a sub-project one that place one path
    of the tree in two layers, neither under [override], When they are read
    as one, Then the declaration cannot be read, naming both files, the
    section and the path."""
    merged = _merged(
        {
            "adherence.toml": b'[layers]\ndomain = ["**/*.py"]\n',
            "pkg/adherence.toml": b'[layers]\nadapters = ["io/**"]\n',
        },
        tree=("pkg/core.py", "pkg/io/a.py"),
    )

    assert isinstance(merged, DeclarationUnreadable)
    assert "adherence.toml and pkg/adherence.toml" in merged.reason
    assert "[layers]" in merged.reason and "pkg/io/a.py" in merged.reason


def test_two_files_agreeing_on_a_paths_layer_are_no_conflict() -> None:
    """Given two governing files that place one path in the same layer,
    When they are read as one, Then it reads."""
    merged = _merged(
        {
            "adherence.toml": b'[layers]\ndomain = ["pkg/core/**"]\n',
            "pkg/adherence.toml": b'[layers]\ndomain = ["core/*.py"]\n',
        },
        tree=("pkg/core/a.py",),
    )

    assert isinstance(merged, Declaration), merged


@pytest.mark.parametrize("section", ["records", "radar", "limits"])
def test_a_single_valued_section_defined_twice_is_unreadable(section: str) -> None:
    """Given a root declaration and a sub-project one that both define one
    single-valued section, neither under [override], When they are read as
    one, Then the declaration cannot be read, naming both files and the
    section."""
    tables = {
        "records": b'[records]\ndesign = "D.md"\narchitecture = "A.md"\n',
        "radar": b'[radar]\npath = "R.md"\n',
        "limits": b"[limits]\n",
    }
    merged = _merged(
        {"adherence.toml": tables[section], "pkg/adherence.toml": tables[section]}
    )

    assert isinstance(merged, DeclarationUnreadable)
    assert "adherence.toml and pkg/adherence.toml" in merged.reason
    assert f"[{section}]" in merged.reason


def test_sibling_sub_projects_each_define_their_own_records() -> None:
    """Given two sibling sub-projects that each define [records], When they
    are read as one, Then each subtree has its own record."""
    declaration = _declared({"a/adherence.toml": PKG, "b/adherence.toml": PKG})

    one, other = declaration.records_for("a/x.py"), declaration.records_for("b/x.py")
    assert one is not None and one.design == "a/docs/DESIGN.md"
    assert other is not None and other.design == "b/docs/DESIGN.md"


@pytest.mark.parametrize("section", ["radar", "layers"])
def test_an_override_of_nothing_is_unreadable(section: str) -> None:
    """Given a sub-project declaration with a section under [override] that
    no declaration above it defines, When it is read, Then it cannot be
    read, naming the file and the section."""
    body = {"radar": b'path = "R.md"\n', "layers": b'domain = ["**"]\n'}[section]
    merged = _merged(
        {
            "adherence.toml": b'[layers]\ntest = ["tests/**"]\n'
            if section == "radar"
            else ROOT_RADAR,
            "pkg/adherence.toml": f"[override.{section}]\n".encode() + body,
        }
    )

    assert isinstance(merged, DeclarationUnreadable)
    assert "pkg/adherence.toml" in merged.reason
    assert f"[override.{section}]" in merged.reason


def test_an_override_at_the_root_overrides_nothing() -> None:
    """Given a root declaration with an [override] section, When it is
    parsed alone, Then it cannot be read."""
    parsed = parse_declaration(b'[override.radar]\npath = "R.md"\n')

    assert isinstance(parsed, DeclarationUnreadable)
    assert "overrides nothing" in parsed.reason


def test_the_same_exemption_from_two_files_is_one_with_both_reasons() -> None:
    """Given a root declaration and a sub-project one exempting the same
    finding, When they are read as one, Then it is one exemption carrying
    both reasons."""
    merged = _declared(
        {
            "adherence.toml": b'[[exemptions]]\nfinding = "abc"\nreason = "root"\n',
            "pkg/adherence.toml": b'[[exemptions]]\nfinding = "abc"\nreason = "pkg"\n',
        }
    )

    [exemption] = merged.exemptions
    assert exemption.reason == "root; pkg"
    assert exemption.within == ""


def test_no_declaration_file_is_declaration_none() -> None:
    """Given no declaration file at all, When the governing declarations
    are read, Then the repository is undeclared and governs nothing."""
    merged = governing_declarations((), ())

    assert merged == Declaration.none
    assert not Declaration.none.governs("anything.py")
