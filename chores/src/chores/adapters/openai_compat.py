"""OpenAICompatCompletion -- CompletionPort over any OpenAI-compatible
``/chat/completions`` endpoint. One adapter covers the family by config:
base URL, auth header name, credential, price table (Subsystem 4). The
Cloudflare AI Gateway is the first instance; its account path is part of
the configured base URL and nothing here knows it."""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence

from chores.adapters._http_errors import raise_for_status, raise_for_transport
from chores.adapters.http import HttpTransport, TransportError, TransportTimeout
from chores.domain.run import Billing
from chores.ports.backends import Price
from chores.ports.completion import CompletionRequest, CompletionResponse
from chores.ports.errors import BackendError


class OpenAICompatCompletion:
    def __init__(
        self,
        transport: HttpTransport,
        *,
        base_url: str,
        auth_header: str,
        credential: str,
        prices: Mapping[str, Price],
        provider: str = "openai-compat",
    ) -> None:
        self._transport = transport
        self._base_url = base_url.rstrip("/")
        self._auth_header = auth_header
        self._credential = credential
        self._prices = prices
        self._provider = provider

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        body: dict[str, object] = {
            "model": request.model,
            "messages": [{"role": "user", "content": request.prompt}],
        }
        if request.max_output_tokens is not None:
            body["max_tokens"] = request.max_output_tokens
        started = time.monotonic()
        try:
            response = self._transport.post_json(
                f"{self._base_url}/chat/completions",
                headers={self._auth_header: f"Bearer {self._credential}"},
                body=body,
                timeout_sec=request.timeout_sec,
            )
        except (TransportError, TransportTimeout) as e:
            raise raise_for_transport(e, provider=self._provider) from e
        raise_for_status(response, provider=self._provider)
        text = _first_choice_text(response.body.get("choices"), provider=self._provider)
        usage = response.body.get("usage")
        tokens_in = tokens_out = 0
        if isinstance(usage, Mapping):
            tokens_in = int(str(usage.get("prompt_tokens", 0)))
            tokens_out = int(str(usage.get("completion_tokens", 0)))
        return CompletionResponse(
            text=text,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            usd=self._price(request.model, tokens_in, tokens_out),
            provider=self._provider,
            model=request.model,
            latency_sec=time.monotonic() - started,
            billing=Billing.METERED,
        )

    def _price(self, model: str, tokens_in: int, tokens_out: int) -> float | None:
        price = self._prices.get(model)
        if price is None:
            return None
        return (tokens_in * price.in_per_1m + tokens_out * price.out_per_1m) / 1_000_000


def _first_choice_text(choices: object, *, provider: str) -> str:
    if not isinstance(choices, Sequence) or not choices:
        raise BackendError(f"{provider}: response carried no choices")
    first = choices[0]
    if not isinstance(first, Mapping):
        raise BackendError(f"{provider}: malformed choice")
    message = first.get("message")
    if not isinstance(message, Mapping) or "content" not in message:
        raise BackendError(f"{provider}: choice carried no message.content")
    return str(message["content"])
