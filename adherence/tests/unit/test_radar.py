"""The Radar-true quality's checks -- Dependency, Edge only -- driven through
`measure` with a fake behind every port, the radar read through the
records port (DESIGN.ARCH-ADHERENCE.md, Behaviors; ARCHITECTURE.ARCH-
ADHERENCE.md, Use-case surface)."""

from __future__ import annotations

from adherence.container import SHIPPED_VOCABULARY
from adherence.domain.finding import Finding
from adherence.domain.model import CodeModel, ImportEdge, Layer
from adherence.domain.records import Radar, RadarEntry, RecordsUnavailable, Ring
from adherence.domain.report import Report
from tests.measure_kit import measure_with

RULES = "src/app/domain/rules.py"
USE = "src/app/application/use.py"
FS = "src/app/adapters/fs.py"
RADAR_PATH = "docs/TECH_RADAR.md"


def _of(report: Report, check: str) -> list[Finding]:
    return [f for f in report.findings if f.check.name == check]


def _import(
    path: str, module: str, line: int, resolved: str | None = None
) -> ImportEdge:
    return ImportEdge(path, module, line, f"import {module}", resolved)


RADAR = Radar(
    entries=(
        RadarEntry("Requests", Ring.TRIAL, RADAR_PATH, 3),
        RadarEntry("markdown-it-py", Ring.ADOPT, RADAR_PATH, 4),
        RadarEntry("leftpad", Ring.HOLD, RADAR_PATH, 9),
    )
)


def test_measure_with_a_dependency_off_the_radar_finds_it() -> None:
    """Given an adapter importing a Trial dependency, an Adopt one under its
    package name, one on Hold, one the radar lacks, the standard library and
    the repository's own module, and an uncovered file importing what the
    radar lacks, When Dependency runs, Then a finding names each dependency
    not on Adopt or Trial and the ring it is on, or that it is absent."""
    scratch = "scratch.py"
    files = {FS: b"x\n" * 10, RULES: b"x\n", scratch: b"x\n"}
    facts = CodeModel(
        imports=(
            _import(FS, "requests", 1),
            _import(FS, "markdown_it.main", 2),
            _import(FS, "leftpad", 3),
            _import(FS, "yaml", 4),
            _import(FS, "dataclasses", 5),
            _import(FS, "app.domain.rules", 6, resolved=RULES),
            _import(scratch, "yaml", 1),
        )
    )

    report = measure_with(files, facts, radar=RADAR)

    assert "Dependency" in {c.name for c in report.ran}
    found = {
        (f.unit.path, f.evidence.line, f.subject) for f in _of(report, "Dependency")
    }
    assert found == {
        (FS, 3, "leftpad: on Hold"),
        (FS, 4, "yaml: not on the radar"),
    }
    assert {f.layer for f in _of(report, "Dependency")} == {Layer.ADAPTERS}


def test_measure_without_a_readable_radar_covers_dependency() -> None:
    """Given no readable radar, When Dependency runs, Then it is coverage
    naming the radar, never a clean result."""
    report = measure_with(
        {FS: b"x\n"}, radar=RecordsUnavailable(f"{RADAR_PATH} is absent")
    )

    assert "Dependency" not in {c.name for c in report.ran}
    assert any(
        c.check == "Dependency" and RADAR_PATH in c.reason for c in report.coverage
    )


def test_measure_with_a_radar_entry_in_the_core_finds_the_unit_and_entry() -> None:
    """Given a domain unit and a use case that import radar entries, an
    adapter importing one, and core imports of the standard library and of a
    package the radar lacks, When Edge only runs, Then a finding names each
    core unit and the entry it imports."""
    files = {RULES: b"x\n" * 10, USE: b"x\n" * 10, FS: b"x\n" * 10}
    facts = CodeModel(
        imports=(
            _import(RULES, "requests", 1),
            _import(RULES, "yaml", 2),
            _import(RULES, "dataclasses", 3),
            _import(USE, "markdown_it", 4),
            _import(FS, "requests", 1),
        )
    )

    report = measure_with(files, facts, radar=RADAR)

    assert "Edge only" in {c.name for c in report.ran}
    found = {
        (f.unit.path, f.layer, f.subject, f.evidence.line)
        for f in _of(report, "Edge only")
    }
    assert found == {
        (RULES, Layer.DOMAIN, "Requests", 1),
        (USE, Layer.APPLICATION, "markdown-it-py", 4),
    }


ADOPTED = (
    ("attr", "attrs"),
    ("dateutil.parser", "python-dateutil"),
    ("bs4", "beautifulsoup4"),
    ("PIL.Image", "Pillow"),
    ("cv2", "opencv-python"),
    ("sklearn.linear_model", "scikit-learn"),
    ("jwt", "PyJWT"),
    ("dotenv", "python-dotenv"),
    ("git", "GitPython"),
)


def test_measure_matches_an_import_to_its_distribution_on_the_radar() -> None:
    """Given the shipped vocabulary, an adapter importing packages whose
    import names differ from the distributions the radar adopts, and one
    whose radar row carries its import name, and a domain unit importing
    two of them, When Dependency and Edge only run, Then no dependency is
    off the radar and Edge only names both entries the domain imports
    (Self-review R11)."""
    radar = Radar(
        entries=(
            *(
                RadarEntry(name, Ring.ADOPT, RADAR_PATH, n)
                for n, (_, name) in enumerate(ADOPTED, start=1)
            ),
            RadarEntry("yaml", Ring.TRIAL, RADAR_PATH, 20),
        )
    )
    imports = [_import(FS, module, n) for n, (module, _) in enumerate(ADOPTED, 1)]
    imports.append(_import(FS, "yaml", 15))
    imports += [_import(RULES, "attr", 1), _import(RULES, "PIL", 2)]
    files = {FS: b"x\n" * 20, RULES: b"x\n" * 5}

    report = measure_with(
        files,
        CodeModel(imports=tuple(imports)),
        radar=radar,
        vocabulary=SHIPPED_VOCABULARY,
    )

    assert {"Dependency", "Edge only"} <= {c.name for c in report.ran}
    assert [f.subject for f in _of(report, "Dependency")] == []
    assert {f.subject for f in _of(report, "Edge only")} == {"attrs", "Pillow"}
