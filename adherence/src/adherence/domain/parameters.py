"""domain/parameters.py -- the tuned values a run is given.

Parameters bundles ThresholdPolicy, Vocabulary and Limits
(ARCHITECTURE.ARCH-ADHERENCE.md, Use-case surface); the composition root
supplies the shipped defaults and domain/declaration merges a
declaration's overrides in. Only Vocabulary exists so far.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from adherence.domain.model import Layer


@dataclass(frozen=True, slots=True)
class Vocabulary:
    """What counts as a marker of each kind, per language.

    regions maps a section marker's name, lower-cased, to the layer of the
    region it opens.
    """

    regions: Mapping[str, Layer]
