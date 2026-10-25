"""domain/declaration: regions found by the fleet's section markers.

A one-file tool declares its regions by marker (ARCHITECTURE.ARCH-
ADHERENCE.md, Mechanism > Measurement): each `# --- <Section> ---` line
opens a region that runs to the line before the next marker; the
section-to-layer mapping is Vocabulary.regions.
"""

from __future__ import annotations

from adherence.domain.declaration import marker_regions
from adherence.domain.model import Layer, Region
from adherence.domain.parameters import Vocabulary

VOCABULARY = Vocabulary(
    regions={
        "predicates": Layer.DOMAIN,
        "action functions": Layer.ADAPTERS,
        "flow functions": Layer.APPLICATION,
        "main": Layer.COMPOSITION_ROOT,
    }
)

TOOL = """#!/usr/bin/env bash
set -euo pipefail

# --- Predicates ---
is_ready() { true; }

# --- Action functions -------------------------------------------------------
fetch() { curl "$1"; }

# --- Scratch ---
junk() { :; }

# --- Main ---
main() { fetch x; }
main "$@"
"""


def test_marker_regions_run_from_each_marker_to_the_next() -> None:
    """Given a file with section markers, When its regions are found, Then each
    known section is a region of its layer up to the next marker, and an
    unknown section ends the one before it and covers nothing."""
    assert marker_regions("bin/tool", TOOL, VOCABULARY) == (
        Region("bin/tool", 4, 6, Layer.DOMAIN),
        Region("bin/tool", 7, 9, Layer.ADAPTERS),
        Region("bin/tool", 13, 15, Layer.COMPOSITION_ROOT),
    )


def test_marker_regions_of_a_file_without_markers_are_none() -> None:
    """Given a file with no section marker, When its regions are found,
    Then there are none."""
    assert marker_regions("bin/plain", "echo hi\n", VOCABULARY) == ()
