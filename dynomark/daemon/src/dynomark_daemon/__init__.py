"""dynomark_daemon -- the Dynomark daemon runtime (docs/design/DYNOMARK.DESIGN.md).

Layers, dependencies pointing inward:

- ``domain``   the ubiquitous language: pure rules and frozen values; stdlib only
- ``ports``    one ``typing.Protocol`` per seam the daemon owns
- ``app``      use cases, one function per Behaviors row (ports as keyword deps)
- ``wire``     Pydantic models of contract v1 and the wire <-> domain mapping
- ``adapters`` the mechanisms behind the ports (none yet)
- ``testing``  in-memory fakes of every port, shared by unit and adapter suites
"""
