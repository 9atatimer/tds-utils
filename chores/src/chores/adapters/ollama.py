"""OllamaCompletion -- CompletionPort over a local Ollama (``/api/chat``)."""

from __future__ import annotations

import time
from collections.abc import Mapping

from chores.adapters._fields import int_field
from chores.adapters._http_errors import raise_for_status, raise_for_transport
from chores.adapters.http import HttpTransport, TransportError, TransportTimeout
from chores.domain.run import Billing
from chores.ports.completion import CompletionRequest, CompletionResponse
from chores.ports.errors import BackendError

PROVIDER = "ollama"
DEFAULT_BASE_URL = "http://localhost:11434"


class OllamaCompletion:
    def __init__(
        self, transport: HttpTransport, *, base_url: str = DEFAULT_BASE_URL
    ) -> None:
        self._transport = transport
        self._base_url = base_url.rstrip("/")

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        body: dict[str, object] = {
            "model": request.model,
            "messages": [{"role": "user", "content": request.prompt}],
            "stream": False,
        }
        if request.max_output_tokens is not None:
            body["options"] = {"num_predict": request.max_output_tokens}
        started = time.monotonic()
        try:
            response = self._transport.post_json(
                f"{self._base_url}/api/chat",
                headers={},
                body=body,
                timeout_sec=request.timeout_sec,
            )
        except (TransportError, TransportTimeout) as e:
            raise raise_for_transport(e, provider=PROVIDER) from e
        raise_for_status(response, provider=PROVIDER)
        message = response.body.get("message")
        if not isinstance(message, Mapping) or "content" not in message:
            raise BackendError(f"{PROVIDER}: response carried no message.content")
        return CompletionResponse(
            text=str(message["content"]),
            tokens_in=int_field(
                response.body.get("prompt_eval_count"),
                provider=PROVIDER,
                field="prompt_eval_count",
            ),
            tokens_out=int_field(
                response.body.get("eval_count"), provider=PROVIDER, field="eval_count"
            ),
            usd=None,
            provider=PROVIDER,
            model=request.model,
            latency_sec=time.monotonic() - started,
            billing=Billing.NONE,
        )
