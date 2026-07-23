"""Classifier adapter that rides the local ``claude`` CLI (the default provider).

The subprocess call is injected so tests never touch a real binary or the
network. Robustness contract: a malformed batch response is retried once, then
that batch degrades to low-confidence triage results (never raises). A missing
or failing binary raises ``InfrastructureError`` so the pipeline degrades to
rules-only.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Sequence

from orgmarks.domain.errors import InfrastructureError
from orgmarks.domain.model import Bookmark, FolderPath
from orgmarks.domain.taxonomy import Intent
from orgmarks.ports.classifier import ClassifyResult

Runner = Callable[[str], str]

_TRIAGE_FOLDER = FolderPath(("work",))
_TRIAGE_REF = FolderPath(("uncategorized",))


class ClaudeCliClassifier:
    """Classify residue by shelling out to the ``claude`` CLI."""

    def __init__(
        self, *, model: str | None = None, runner: Runner | None = None
    ) -> None:
        """Build the classifier; inject ``runner`` in tests to avoid the binary."""
        self._model = model
        self._runner = runner if runner is not None else self._subprocess_runner

    def _subprocess_runner(self, prompt: str) -> str:
        argv = ["claude", "-p"]
        if self._model:
            argv += ["--model", self._model]
        try:
            completed = subprocess.run(
                argv,
                input=prompt,
                capture_output=True,
                text=True,
                check=True,
            )
        except FileNotFoundError as err:
            raise InfrastructureError("claude CLI not found on PATH") from err
        except subprocess.CalledProcessError as err:
            raise InfrastructureError(
                f"claude CLI failed (exit {err.returncode})"
            ) from err
        return completed.stdout

    def classify(
        self,
        batch: Sequence[Bookmark],
        *,
        intents: Sequence[Intent],
        skeleton: str,
    ) -> list[ClassifyResult]:
        """Classify ``batch``; malformed responses degrade to triage."""
        prompt = _build_prompt(batch, intents, skeleton)
        parsed = self._invoke_with_retry(prompt)
        if parsed is None:
            return [_triage_result(bm) for bm in batch]
        by_url = {str(row.get("url")): row for row in parsed if isinstance(row, dict)}
        return [_row_to_result(bm, by_url.get(bm.url)) for bm in batch]

    def _invoke_with_retry(self, prompt: str) -> list[object] | None:
        """Call the runner, retrying once on a malformed response."""
        for _ in range(2):
            raw = self._runner(prompt)
            parsed = _parse_rows(raw)
            if parsed is not None:
                return parsed
        return None


def _build_prompt(
    batch: Sequence[Bookmark], intents: Sequence[Intent], skeleton: str
) -> str:
    payload = {
        "intents": [{"name": intent.name, "hint": intent.hint} for intent in intents],
        "folder_skeleton": skeleton,
        "bookmarks": [
            {
                "url": bm.url,
                "title": bm.title,
                "current_folder": str(bm.source_path),
            }
            for bm in batch
        ],
    }
    return (
        "You are filing bookmarks into an intent-first folder tree.\n"
        "For each bookmark return a JSON array (and nothing else) of objects "
        'with keys: "url", "folder" (intent path like work/dev), "ref" '
        '(reference category like technical/dev), "confidence" (0..1), and '
        'optional "proposed_new_folder".\n\n'
        f"{json.dumps(payload, indent=2)}\n"
    )


def _parse_rows(raw: str) -> list[object] | None:
    """Parse a JSON array from the model response, tolerating surrounding text."""
    text = raw.strip()
    for candidate in (text, _slice_array(text)):
        if candidate is None:
            continue
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, list):
            return value
    return None


def _slice_array(text: str) -> str | None:
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start : end + 1]


def _row_to_result(bookmark: Bookmark, row: object) -> ClassifyResult:
    if not isinstance(row, dict):
        return _triage_result(bookmark)
    try:
        folder = FolderPath.from_string(str(row["folder"]))
        ref = FolderPath.from_string(str(row["ref"]))
        confidence = float(row["confidence"])
    except (KeyError, TypeError, ValueError):
        return _triage_result(bookmark)
    proposed = row.get("proposed_new_folder")
    return ClassifyResult(
        url=bookmark.url,
        folder=folder,
        ref=ref,
        confidence=confidence,
        proposed_new_folder=str(proposed) if proposed else None,
    )


def _triage_result(bookmark: Bookmark) -> ClassifyResult:
    return ClassifyResult(
        url=bookmark.url,
        folder=_TRIAGE_FOLDER,
        ref=_TRIAGE_REF,
        confidence=0.0,
    )
