"""ollama and openai-compat CompletionPort adapters over a fake HTTP transport."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from chores.adapters.http import HttpResponse, TransportError, TransportTimeout
from chores.adapters.ollama import OllamaCompletion
from chores.adapters.openai_compat import OpenAICompatCompletion
from chores.domain.run import Billing
from chores.ports.backends import Price
from chores.ports.completion import CompletionRequest
from chores.ports.errors import (
    BackendError,
    BackendTimeout,
    ModelNotFound,
    RateLimited,
    Unauthorized,
    Unreachable,
)


class FakeTransport:
    def __init__(self, response: HttpResponse | Exception) -> None:
        self.response = response
        self.calls: list[
            tuple[str, Mapping[str, str], Mapping[str, object], float]
        ] = []

    def post_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        body: Mapping[str, object],
        timeout_sec: float,
    ) -> HttpResponse:
        self.calls.append((url, headers, body, timeout_sec))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


REQ = CompletionRequest(prompt="hi", model="m", timeout_sec=30, max_output_tokens=200)


def test_ollama_posts_chat_and_reads_counts() -> None:
    t = FakeTransport(
        HttpResponse(
            200,
            {
                "message": {"content": "hello"},
                "prompt_eval_count": 7,
                "eval_count": 3,
            },
        )
    )
    out = OllamaCompletion(t, base_url="http://localhost:11434").complete(REQ)
    url, headers, body, timeout = t.calls[0]
    assert url == "http://localhost:11434/api/chat"
    assert body["model"] == "m" and body["stream"] is False
    assert body["options"] == {"num_predict": 200}
    assert out.text == "hello" and (out.tokens_in, out.tokens_out) == (7, 3)
    assert out.usd is None and out.billing is Billing.NONE and out.provider == "ollama"


def test_openai_compat_sends_auth_header_and_prices_usage() -> None:
    t = FakeTransport(
        HttpResponse(
            200,
            {
                "choices": [{"message": {"content": "yo"}}],
                "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 500_000},
            },
        )
    )
    adapter = OpenAICompatCompletion(
        t,
        base_url="https://gw.example/v1/acct/compat",
        auth_header="cf-aig-authorization",
        credential="tok",
        prices={"m": Price(in_per_1m=0.15, out_per_1m=0.60)},
        provider="gateway",
    )
    out = adapter.complete(REQ)
    url, headers, body, _ = t.calls[0]
    assert url == "https://gw.example/v1/acct/compat/chat/completions"
    assert headers["cf-aig-authorization"] == "Bearer tok"
    assert (
        body["messages"] == [{"role": "user", "content": "hi"}]
        and body["max_tokens"] == 200
    )
    assert out.text == "yo" and out.usd == pytest.approx(0.15 + 0.30)
    assert out.billing is Billing.METERED and out.provider == "gateway"


def test_openai_compat_unpriced_model_reports_none_usd_and_missing_usage_zero() -> None:
    t = FakeTransport(HttpResponse(200, {"choices": [{"message": {"content": "x"}}]}))
    out = OpenAICompatCompletion(
        t, base_url="u", auth_header="h", credential="c", prices={}
    ).complete(REQ)
    assert out.usd is None and out.tokens_in == 0 and out.tokens_out == 0


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (HttpResponse(401, {"error": "bad key"}), Unauthorized),
        (HttpResponse(403, {}), Unauthorized),
        (HttpResponse(429, {}), RateLimited),
        (HttpResponse(404, {"error": {"message": "model not found"}}), ModelNotFound),
        (HttpResponse(500, {"error": "boom"}), BackendError),
        (TransportError("connection refused"), Unreachable),
        (TransportTimeout("slow"), BackendTimeout),
    ],
)
def test_http_failures_map_to_typed_errors(
    response: HttpResponse | Exception, error: type[Exception]
) -> None:
    adapter = OpenAICompatCompletion(
        FakeTransport(response),
        base_url="u",
        auth_header="h",
        credential="c",
        prices={},
    )
    with pytest.raises(error):
        adapter.complete(REQ)
    with pytest.raises(error):
        OllamaCompletion(FakeTransport(response), base_url="u").complete(REQ)


def test_malformed_success_body_is_a_backend_error() -> None:
    with pytest.raises(BackendError):
        OllamaCompletion(
            FakeTransport(HttpResponse(200, {"nope": 1})), base_url="u"
        ).complete(REQ)


def test_malformed_usage_counts_are_backend_errors() -> None:
    from chores.adapters.http import HttpResponse
    from chores.adapters.ollama import OllamaCompletion
    from chores.adapters.openai_compat import OpenAICompatCompletion
    from chores.ports.completion import CompletionRequest

    req = CompletionRequest(
        prompt="p", model="m", timeout_sec=1.0, max_output_tokens=None
    )
    bad_openai = HttpResponse(
        200,
        {
            "choices": [{"message": {"content": "x"}}],
            "usage": {"prompt_tokens": "lots", "completion_tokens": 1},
        },
    )
    with pytest.raises(BackendError, match="prompt_tokens"):
        OpenAICompatCompletion(
            FakeTransport(bad_openai),
            base_url="u",
            auth_header="x-auth",
            credential="c",
            prices={},
            provider="p",
        ).complete(req)
    bad_ollama = HttpResponse(
        200, {"message": {"content": "x"}, "prompt_eval_count": "1", "eval_count": {}}
    )
    with pytest.raises(BackendError, match="eval_count"):
        OllamaCompletion(FakeTransport(bad_ollama), base_url="u").complete(req)


@pytest.mark.parametrize("cost", ["nan", "inf", "-0.5"])
def test_provider_costs_must_be_finite_and_non_negative(cost: str) -> None:
    from chores.adapters._fields import float_field, int_field

    with pytest.raises(BackendError, match="total_cost_usd"):
        float_field(cost, provider="p", field="total_cost_usd")
    with pytest.raises(BackendError, match="negative"):
        int_field(-1, provider="p", field="output_tokens")
