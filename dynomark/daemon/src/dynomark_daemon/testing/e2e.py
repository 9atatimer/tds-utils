"""The daemon the integration e2e (``dynomark/e2e``) runs: production wiring
with the models replaced by this package's fakes.

``python -m dynomark_daemon.testing.e2e --script SCRIPT.json`` loads the
daemon's settings exactly as ``dynomark-daemon serve`` does (config file,
environment, state directory, socket) and serves them with the SQLite store,
the real fetch, the system clock -- and ``HashingEmbedding`` plus a
``ScriptedCompletion`` read from the script. It is test support, not a
production option: it is no console script, and no config key selects it.

The script is a JSON object; each key is optional and holds that method's
answers in the order they are consumed (an exhausted script fails the call
loudly, as in unit tests)::

    {"enrich":        [{"summary": str, "tags": [str]}],
     "choose_folder": [{"folder": FolderPath, "rationale": str}],
     "answer":        [{"text": str, "cited": [Identity], "urls": [str]}],
     "propose_diff":  [[{"action": "add"|"move"|"merge",
                         "description": str, "operations": [Operation]}]]}

``FolderPath`` and ``Operation`` are contract v1 shapes.
"""

import json
import os
import platform
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

import click
from pydantic import BaseModel, ConfigDict, ValidationError

from dynomark_daemon.adapters.fetch import FetchContentSource
from dynomark_daemon.adapters.socket_server import SocketUnavailable
from dynomark_daemon.adapters.sqlite_store import SqliteCorpusStore
from dynomark_daemon.container import (
    Ports,
    RandomIds,
    SystemClock,
    fetch_policy,
    private_state_dir,
    serve,
)
from dynomark_daemon.domain.bookmark import Enrichment, Identity
from dynomark_daemon.domain.chat import DraftAnswer
from dynomark_daemon.domain.diff import DiffAction, DiffProposal
from dynomark_daemon.domain.placement import FolderChoice
from dynomark_daemon.settings import ConfigError, Settings, load_settings
from dynomark_daemon.testing.completion import ScriptedCompletion
from dynomark_daemon.testing.embedding import HashingEmbedding
from dynomark_daemon.wire import values as w
from dynomark_daemon.wire.mapping import folder_path_from_wire, operation_from_wire

# --- Constants ---

EMBEDDING_ID: Final = "fake:hashing"
COMPLETION_ID: Final = "fake:scripted"


class ScriptError(ValueError):
    """The script is not JSON, or a key or value is not one the fakes know."""


# --- The script document ---


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _Enrich(_Strict):
    summary: str
    tags: list[str]


class _ChooseFolder(_Strict):
    folder: w.FolderPath
    rationale: str


class _Answer(_Strict):
    text: str
    cited: list[str]
    urls: list[str]


class _Proposal(_Strict):
    action: DiffAction
    description: str
    operations: list[w.Operation]


class _Script(_Strict):
    enrich: list[_Enrich] = []
    choose_folder: list[_ChooseFolder] = []
    answer: list[_Answer] = []
    propose_diff: list[list[_Proposal]] = []


# --- Pure helpers ---


def _proposals(items: Sequence[_Proposal]) -> tuple[DiffProposal, ...]:
    return tuple(
        DiffProposal(
            action=item.action,
            description=item.description,
            operations=tuple(operation_from_wire(op) for op in item.operations),
        )
        for item in items
    )


def load_script(document: Mapping[str, object]) -> ScriptedCompletion:
    """The scripted completion ``document`` describes.

    Raises:
        ScriptError: an unknown key, or a value of the wrong shape.
    """
    try:
        script = _Script.model_validate(document)
    except ValidationError as error:
        raise ScriptError(str(error)) from error
    return ScriptedCompletion(
        enrich=[
            Enrichment(summary=e.summary, tags=tuple(e.tags)) for e in script.enrich
        ],
        choose_folder=[
            FolderChoice(folder=folder_path_from_wire(c.folder), rationale=c.rationale)
            for c in script.choose_folder
        ],
        answer=[
            DraftAnswer(
                text=a.text,
                cited=tuple(Identity(value) for value in a.cited),
                urls=tuple(a.urls),
            )
            for a in script.answer
        ],
        propose_diff=[_proposals(items) for items in script.propose_diff],
        model_id=COMPLETION_ID,
    )


# --- Composition ---


def e2e_ports(settings: Settings, completion: ScriptedCompletion) -> Ports:
    """``build_ports`` with the models faked: SQLite, fetch, system clock."""
    return Ports(
        store=SqliteCorpusStore.open(Path(settings.config.store_path)),
        embedding=HashingEmbedding(model_id=EMBEDDING_ID),
        completion=completion,
        content=FetchContentSource(
            timeout_s=settings.capture.fetch_timeout_s,
            max_bytes=settings.capture.max_bytes,
            address_allowed=fetch_policy(settings),
        ),
        clock=SystemClock(),
        ids=RandomIds(),
    )


# --- Entry point ---


@click.command()
@click.option(
    "--script",
    "script_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="The JSON script the fake completion answers from.",
)
def main(script_path: Path) -> None:
    """Serve the daemon with scripted fake models (integration e2e only)."""
    try:
        settings = load_settings(os.environ, home=Path.home(), hostname=platform.node())
        document = json.loads(script_path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ScriptError(f"{script_path}: not a JSON object")
        completion = load_script(document)
    except (ConfigError, ScriptError, json.JSONDecodeError) as error:
        raise click.UsageError(str(error)) from error
    private_state_dir(settings)
    try:
        serve(settings, e2e_ports(settings, completion))
    except SocketUnavailable as error:
        raise click.ClickException(str(error)) from error


if __name__ == "__main__":
    main(sys.argv[1:])
