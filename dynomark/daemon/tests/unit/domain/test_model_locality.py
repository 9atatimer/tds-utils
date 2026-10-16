"""Security Considerations, "Cloud model egress": the user can see when page
text or questions leave the machine. A model is ``local`` only when the
Ollama host is loopback, its id is not cloud-tagged, and the config does not
declare the endpoint remote (issue #411, task-036)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from dynomark_daemon.domain.config import is_cloud_tagged, is_local_model


@pytest.mark.parametrize(
    "model",
    [
        "gpt-oss:120b-cloud",
        "qwen3-coder:480b-cloud",
        "deepseek-v3.1:671b-cloud",
        "llama3.1:cloud",
        "kimi-k2:1t-CLOUD",
    ],
)
def test_a_cloud_tagged_model_on_a_loopback_host_is_not_local(model: str) -> None:
    """Given Ollama on 127.0.0.1 serving a cloud-tagged model (the tag holds
    "cloud"), When locality is decided, Then the model is not local: Ollama
    forwards it to its cloud."""
    assert is_cloud_tagged(model)
    assert not is_local_model("127.0.0.1", model, declared_remote=False)


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "127.0.0.2"])
@pytest.mark.parametrize("model", ["llama3.1:8b", "nomic-embed-text", "qwen2.5:7b"])
def test_a_plain_model_on_a_loopback_host_is_local(host: str, model: str) -> None:
    """Given a loopback host and a model id with no cloud tag, When decided,
    Then it is local."""
    assert is_local_model(host, model, declared_remote=False)


@pytest.mark.parametrize("host", ["gpu-box", "10.0.0.5", "ollama.example.com", ""])
def test_a_model_on_a_host_that_is_not_loopback_is_not_local(host: str) -> None:
    """Given an Ollama host that is not loopback (or none), When decided, Then
    no model is local."""
    assert not is_local_model(host, "llama3.1:8b", declared_remote=False)


def test_an_endpoint_declared_remote_is_never_local() -> None:
    """Given ``[models] remote = true`` (a tunnel or proxy on 127.0.0.1), When a
    plain model on a loopback host is decided, Then it is not local."""
    assert not is_local_model("127.0.0.1", "llama3.1:8b", declared_remote=True)


def test_cloud_in_the_model_name_but_not_its_tag_is_no_cloud_tag() -> None:
    """Given "cloud" only in the name before the tag, When checked, Then it is
    not a cloud tag (Ollama marks cloud models by tag)."""
    assert not is_cloud_tagged("cloudberry:7b")


@given(
    host=st.sampled_from(["127.0.0.1", "localhost", "::1", "gpu-box", "10.0.0.5"]),
    model=st.text(min_size=1, max_size=40),
    remote=st.booleans(),
)
def test_local_implies_loopback_untagged_and_not_declared_remote(
    host: str, model: str, remote: bool
) -> None:
    """For any host, model id and flag: a model judged local is on a loopback
    host, carries no cloud tag, and the endpoint is not declared remote."""
    if is_local_model(host, model, declared_remote=remote):
        assert host in {"127.0.0.1", "localhost", "::1"}
        assert not is_cloud_tagged(model)
        assert not remote
