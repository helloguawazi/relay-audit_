"""Microsoft Foundry protocol wiring.

Foundry is easy to get subtly wrong: it serves the Anthropic Messages payload but
uses a different auth header and base path. Getting it wrong produces a request
that looks fine and always fails, which is why it is pinned by tests.
"""

from __future__ import annotations

import pytest

from relay_audit.client import (
    build_headers,
    build_request,
    is_messages_protocol,
    parse_usage,
)
from relay_audit.config import ConfigError, Endpoint


def azure_ep(**kw) -> Endpoint:
    base = dict(
        id="foundry",
        label="Microsoft Foundry",
        role="peer",
        protocol="azure",
        base_url="https://res.services.ai.azure.com/anthropic",
        key_env="FOUNDRY_KEY",
        model="claude-sonnet-5",
        api_key="k",
    )
    base.update(kw)
    return Endpoint(**base)


def test_azure_url_keeps_the_anthropic_path():
    assert azure_ep().url == "https://res.services.ai.azure.com/anthropic/v1/messages"


def test_azure_base_url_with_trailing_slash_does_not_double_up():
    ep = azure_ep(base_url="https://res.services.ai.azure.com/anthropic/")
    assert ep.url == "https://res.services.ai.azure.com/anthropic/v1/messages"


def test_azure_authenticates_with_api_key_header_not_bearer():
    h = build_headers(azure_ep(), stream=True)
    assert h["api-key"] == "k"
    assert "Authorization" not in h
    assert "x-api-key" not in h
    assert h["anthropic-version"] == "2023-06-01"


def test_azure_sends_the_messages_payload_not_openai():
    """The bug this guards: sending an OpenAI-shaped body to a Messages endpoint."""
    body = build_request(azure_ep(), "hi", 8, stream=True)
    assert "messages" in body
    assert "max_tokens" in body
    # OpenAI-only fields must not appear.
    assert "stream_options" not in body
    assert "temperature" not in body


def test_azure_is_treated_as_a_messages_protocol():
    assert is_messages_protocol("azure")
    assert is_messages_protocol("anthropic")
    assert not is_messages_protocol("openai")


def test_azure_usage_parses_anthropic_field_names():
    u = parse_usage(
        "azure",
        {"usage": {"input_tokens": 10, "output_tokens": 2, "cache_read_input_tokens": 900,
                   "cache_creation_input_tokens": 0}},
    )
    assert (u.input_tokens, u.output_tokens) == (10, 2)
    assert u.cache_read_tokens == 900
    assert u.cache_write_tokens == 0


def test_azure_missing_key_names_the_env_var():
    with pytest.raises(ConfigError) as exc:
        azure_ep(api_key=None).require_key()
    assert "FOUNDRY_KEY" in str(exc.value)


def test_azure_url_differs_from_plain_anthropic():
    """A plain anthropic endpoint has no /v1 segment before /messages."""
    plain = azure_ep(protocol="anthropic", base_url="https://www.relay-api.com")
    assert plain.url == "https://www.relay-api.com/messages"
    assert azure_ep().url.endswith("/anthropic/v1/messages")
