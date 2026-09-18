"""chores -- laptop-local herd of LLM-adjacent scheduled jobs.

Design record: docs/design/CHORES.DESIGN.md. Layout follows the coding skill:
``domain/`` (pure decisions and values), ``ports/`` (the named seams as
Protocols), ``adapters/`` (mechanisms), ``application/`` (use cases over
ports only), ``cli/`` (entry points and the composition root).
"""

from __future__ import annotations

__version__ = "0.1.0"
