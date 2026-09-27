"""``EmbeddingPort`` and ``CompletionPort`` on a local Ollama (Design, Seams:
"local (Ollama)"; model id at the edge).

urllib to ``$OLLAMA_HOST`` (default ``http://127.0.0.1:11434``):
``/api/embed`` for vectors, ``/api/generate`` with ``format: json`` for
every completion, ``/api/tags`` for the check command. Prompts ask for one
JSON object; parsing is strict, and an answer that is not the object asked
for is a retryable ``PortError`` (the next attempt may do better). A model
Ollama does not have (404) is not retryable; a connection failure or a 5xx
is. The configured model id is recorded with each embedding; placements
record ``model().model_id`` (``app/place.py``).
"""

import json
import urllib.error
import urllib.request
from collections.abc import Sequence
from typing import Final

from dynomark_daemon.domain.bookmark import (
    Bookmark,
    Capture,
    CorpusEntry,
    Embedding,
    Enrichment,
    Identity,
)
from dynomark_daemon.domain.chat import DraftAnswer, Question, Turn
from dynomark_daemon.domain.config import ModelInfo
from dynomark_daemon.domain.diff import DiffKind, DiffProposal
from dynomark_daemon.domain.placement import EntryRef, FolderChoice, MoveFeedback
from dynomark_daemon.domain.tree import FolderPath, TreeOutline
from dynomark_daemon.ports.completion import CompletionError
from dynomark_daemon.ports.embedding import EmbeddingError

# --- Constants ---

MAX_PROMPT_TEXT: Final = 12_000
"""Captured text shown to the model, in code points."""
MAX_TAGS: Final = 8
MAX_TAG: Final = 64
"""A tag's longest form (contract v1 ``Tag``)."""
MAX_CONTEXT_TEXT: Final = 2_000
OPTIONS: Final = {"temperature": 0}

ENRICH_SYSTEM: Final = (
    "You summarize saved web pages for a personal bookmark index. Answer with "
    'one JSON object only: {"summary": "<one or two sentences>", "tags": '
    '["<1 to 8 short lower-case topic tags>"]}.'
)
PLACE_SYSTEM: Final = (
    "You file a bookmark into an existing folder tree. Choose the existing "
    "folder that fits best, or propose ONE new folder directly under an "
    "existing one. Never choose a folder marked (locked). Answer with one JSON "
    'object only: {"folder": ["<folder name>", "..."], "rationale": "<why>"} '
    "where folder lists the folder names from the top of the tree down."
)
ANSWER_SYSTEM: Final = (
    "You answer questions using only the bookmarked pages given. Answer with "
    'one JSON object only: {"text": "<answer>", "cited": ["<identity of each '
    'page you used>"], "urls": ["<any other URL you mention>"]}.'
)


class OllamaError(RuntimeError):
    """An Ollama call failed; ``retryable`` says whether trying again may help."""

    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


# --- Helpers ---


def has_model(installed: Sequence[str], name: str) -> bool:
    """Whether ``name`` is among Ollama's installed models (``x`` is ``x:latest``)."""
    wanted = {name, f"{name}:latest"} if ":" not in name else {name}
    return any(model in wanted for model in installed)


def _path(path: FolderPath) -> str:
    return "/".join(path.names) or f"({path.root.value})"


def _outline_lines(outline: TreeOutline) -> str:
    lines = [
        _path(folder.path) + (" (locked)" if folder.locked else "")
        for folder in outline.folders
    ]
    return "\n".join(lines) or _path(outline.root)


def _json_object(text: str) -> dict[str, object]:
    try:
        document = json.loads(text)
    except json.JSONDecodeError as error:
        raise CompletionError(
            f"model answer is not JSON: {error}", retryable=True
        ) from error
    if not isinstance(document, dict):
        raise CompletionError("model answer is not a JSON object", retryable=True)
    return document


def _string(document: dict[str, object], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CompletionError(f"model answer lacks a {key} string", retryable=True)
    return value.strip()


def _strings(document: dict[str, object], key: str) -> list[str]:
    value = document.get(key)
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise CompletionError(
            f"model answer's {key} is not a string list", retryable=True
        )
    return [str(v) for v in value]


def _tags(raw: list[str]) -> tuple[str, ...]:
    tags: list[str] = []
    for tag in (t.strip().lower()[:MAX_TAG].strip() for t in raw):
        if tag and tag not in tags:
            tags.append(tag)
    return tuple(tags[:MAX_TAGS])


def _folder(names: list[str], outline: TreeOutline) -> FolderPath:
    cleaned = [name.strip() for name in names]
    if not cleaned or not all(cleaned):
        raise CompletionError("model answer's folder is empty", retryable=True)
    root = outline.root
    if tuple(cleaned[: len(root.names)]) != root.names:
        cleaned = [*root.names, *cleaned]
    return FolderPath(root=root.root, names=tuple(cleaned))


# --- The client ---


class OllamaClient:
    """JSON over HTTP to one Ollama server; no retries (the job loop retries)."""

    def __init__(self, base_url: str, *, timeout_s: float) -> None:
        self._base = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _call(self, request: urllib.request.Request) -> dict[str, object]:
        try:
            with self._opener.open(request, timeout=self._timeout_s) as response:
                body = response.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:500]
            raise OllamaError(
                f"ollama {error.code}: {detail}", retryable=error.code >= 500
            ) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise OllamaError(f"ollama unreachable: {error}", retryable=True) from error
        try:
            document = json.loads(body)
        except json.JSONDecodeError as error:
            raise OllamaError("ollama answered non-JSON", retryable=True) from error
        if not isinstance(document, dict):
            raise OllamaError("ollama answered a non-object", retryable=True)
        return document

    def post(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        request = urllib.request.Request(
            self._base + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return self._call(request)

    def installed_models(self) -> list[str]:
        """The names of the models Ollama has pulled.

        Raises:
            OllamaError: Ollama is not reachable or answered garbage.
        """
        document = self._call(urllib.request.Request(self._base + "/api/tags"))
        models = document.get("models")
        if not isinstance(models, list):
            raise OllamaError("ollama /api/tags has no model list", retryable=True)
        names = (m.get("name") for m in models if isinstance(m, dict))
        return [name for name in names if isinstance(name, str)]


# --- The ports ---


class OllamaEmbedding:
    def __init__(self, client: OllamaClient, *, name: str, model: ModelInfo) -> None:
        self._client = client
        self._name = name
        self._model = model

    def model(self) -> ModelInfo:
        return self._model

    def embed(self, text: str) -> Embedding:
        try:
            document = self._client.post(
                "/api/embed", {"model": self._name, "input": text, "truncate": True}
            )
        except OllamaError as error:
            raise EmbeddingError(str(error), retryable=error.retryable) from error
        vectors = document.get("embeddings")
        vector = vectors[0] if isinstance(vectors, list) and vectors else None
        if not isinstance(vector, list) or not vector:
            raise EmbeddingError("ollama returned no embedding", retryable=True)
        if not all(isinstance(x, int | float) for x in vector):
            raise EmbeddingError("ollama returned a non-numeric vector", retryable=True)
        return Embedding(
            vector=tuple(float(x) for x in vector), model_id=self._model.model_id
        )


class OllamaCompletion:
    def __init__(self, client: OllamaClient, *, name: str, model: ModelInfo) -> None:
        self._client = client
        self._name = name
        self._model = model

    def model(self) -> ModelInfo:
        return self._model

    def _generate(self, system: str, prompt: str) -> dict[str, object]:
        try:
            document = self._client.post(
                "/api/generate",
                {
                    "model": self._name,
                    "system": system,
                    "prompt": prompt,
                    "format": "json",
                    "stream": False,
                    "options": OPTIONS,
                },
            )
        except OllamaError as error:
            raise CompletionError(str(error), retryable=error.retryable) from error
        response = document.get("response")
        if not isinstance(response, str):
            raise CompletionError("ollama returned no response", retryable=True)
        return _json_object(response)

    def enrich(self, bookmark: Bookmark, capture: Capture) -> Enrichment:
        prompt = "\n".join(
            [
                f"Title: {capture.title or bookmark.title}",
                f"URL: {bookmark.url}",
                "Page text:",
                capture.text[:MAX_PROMPT_TEXT] or "(no text could be captured)",
            ]
        )
        document = self._generate(ENRICH_SYSTEM, prompt)
        return Enrichment(
            summary=_string(document, "summary"), tags=_tags(_strings(document, "tags"))
        )

    def choose_folder(
        self,
        entry: CorpusEntry,
        *,
        neighbours: Sequence[EntryRef],
        outline: TreeOutline,
        feedback: Sequence[MoveFeedback],
    ) -> FolderChoice:
        similar = [f"- {n.title} -> {_path(n.path)}" for n in neighbours]
        moves = [
            f"- moved {_path(f.from_path)} -> {_path(f.to_path)}" for f in feedback
        ]
        prompt = "\n".join(
            [
                "Folder tree:",
                _outline_lines(outline),
                "",
                "Bookmark:",
                f"Title: {entry.bookmark.title}",
                f"Summary: {entry.summary}",
                f"Tags: {', '.join(entry.tags)}",
                "",
                "Similar bookmarks and their folders:",
                *(similar or ["(none)"]),
                "",
                "Recent moves the user made by hand:",
                *(moves or ["(none)"]),
            ]
        )
        document = self._generate(PLACE_SYSTEM, prompt)
        return FolderChoice(
            folder=_folder(_strings(document, "folder"), outline),
            rationale=_string(document, "rationale"),
        )

    def answer(
        self,
        question: Question,
        *,
        history: Sequence[Turn],
        context: Sequence[CorpusEntry],
    ) -> DraftAnswer:
        pages = [
            f"[{e.identity.value}] {e.bookmark.title}\n{e.summary}\n"
            f"{e.capture.text[:MAX_CONTEXT_TEXT]}"
            for e in context
        ]
        turns = [f"Q: {t.question}\nA: {t.answer}" for t in history]
        prompt = "\n\n".join(
            ["Pages:", *pages, "Conversation so far:", *turns, f"Q: {question.text}"]
        )
        document = self._generate(ANSWER_SYSTEM, prompt)
        return DraftAnswer(
            text=_string(document, "text"),
            cited=tuple(Identity(c) for c in _strings(document, "cited")),
            urls=tuple(_strings(document, "urls")),
        )

    def propose_diff(
        self, kind: DiffKind, *, outline: TreeOutline, own_bar: TreeOutline
    ) -> tuple[DiffProposal, ...]:
        """Diffs are MVP (task-029); this adapter proposes none yet."""
        raise CompletionError(
            f"{kind.value} diffs are not proposed by the Ollama adapter yet",
            retryable=False,
        )
