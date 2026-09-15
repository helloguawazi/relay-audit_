"""Usage normalisation across both response shapes, and config validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from relay_audit.client import parse_usage
from relay_audit.config import ConfigError, load_config


def test_openai_shape():
    payload = {
        "usage": {
            "prompt_tokens": 3038,
            "completion_tokens": 4,
            "total_tokens": 3042,
            "prompt_tokens_details": {"cached_tokens": 3200},
        }
    }
    u = parse_usage("openai", payload)
    assert u.input_tokens == 3038
    assert u.output_tokens == 4
    assert u.cache_read_tokens == 3200
    assert u.reported_total == 3042


def test_anthropic_shape():
    payload = {
        "usage": {
            "input_tokens": 12,
            "output_tokens": 5,
            "cache_read_input_tokens": 3000,
            "cache_creation_input_tokens": 0,
        }
    }
    u = parse_usage("anthropic", payload)
    assert u.input_tokens == 12
    assert u.output_tokens == 5
    assert u.cache_read_tokens == 3000
    assert u.cache_write_tokens == 0


def test_anthropic_fields_on_openai_body():
    """Some relays leak Anthropic field names onto an OpenAI-shaped body."""
    payload = {"usage": {"prompt_tokens": 10, "completion_tokens": 2, "cache_read_input_tokens": 900}}
    u = parse_usage("openai", payload)
    assert u.cache_read_tokens == 900


def test_missing_usage_stays_none():
    """'not reported' must never be silently turned into zero.

    The difference between "the provider did not report cache reads" and
    "the provider reported zero cache reads" is a real finding, so absence is
    preserved as None.
    """
    u = parse_usage("openai", {})
    assert u.input_tokens is None
    assert u.cache_read_tokens is None
    assert u.has_any is False


def test_partial_usage_keeps_none_for_absent_fields():
    u = parse_usage("openai", {"usage": {"prompt_tokens": 5, "completion_tokens": 1}})
    assert u.input_tokens == 5
    assert u.cache_read_tokens is None
    assert u.cache_write_tokens is None


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "config.toml"
    p.write_text(text, encoding="utf-8")
    return p


BASE = """
[meta]
name = "t"
[tests]
cache_ttl_seconds = 0
[[endpoint]]
id = "ref"
label = "Ref"
role = "reference"
protocol = "openai"
base_url = "https://example.com/v1"
key_env = "UNSET_KEY_XYZ"
model = "m"

[[endpoint]]
id = "cand"
label = "Cand"
role = "candidate"
protocol = "openai"
base_url = "https://example.com/v1"
key_env = "UNSET_KEY_XYZ"
model = "m"
"""


def test_disabled_endpoints_skipped(tmp_path, monkeypatch):
    monkeypatch.delenv("UNSET_KEY_XYZ", raising=False)
    text = BASE + """
[[endpoint]]
id = "off"
label = "Off"
role = "peer"
protocol = "openai"
base_url = "https://example.com/v1"
key_env = "UNSET_KEY_XYZ"
model = "m"
enabled = false
"""
    cfg = load_config(_write(tmp_path, text), demo=True)
    assert [e.id for e in cfg.endpoints] == ["ref", "cand"]


def test_missing_key_is_a_config_error_not_a_crash(tmp_path, monkeypatch):
    monkeypatch.delenv("UNSET_KEY_XYZ", raising=False)
    with pytest.raises(ConfigError) as exc:
        load_config(_write(tmp_path, BASE), demo=False)
    assert "UNSET_KEY_XYZ" in str(exc.value)
    assert "demo" in str(exc.value)


def test_missing_candidate_role_is_rejected(tmp_path):
    text = BASE.replace('role = "candidate"', 'role = "peer"')
    with pytest.raises(ConfigError) as exc:
        load_config(_write(tmp_path, text), demo=True)
    assert "candidate" in str(exc.value)


def test_reference_role_is_required(tmp_path):
    text = BASE.replace('role = "reference"', 'role = "candidate"')
    with pytest.raises(ConfigError) as exc:
        load_config(_write(tmp_path, text), demo=True)
    assert "reference" in str(exc.value) or "candidate" in str(exc.value)


def test_role_typo_is_rejected(tmp_path):
    text = BASE.replace('role = "reference"', 'role = "referance"')
    with pytest.raises(ConfigError) as exc:
        load_config(_write(tmp_path, text), demo=True)
    assert "role" in str(exc.value)


def test_protocol_defaults_and_url_shape(tmp_path):
    cfg = load_config(_write(tmp_path, BASE), demo=True)
    ep = cfg.endpoints[0]
    assert ep.url == "https://example.com/v1/chat/completions"

    text = BASE.replace('protocol = "openai"', 'protocol = "anthropic"')
    cfg = load_config(_write(tmp_path, text), demo=True)
    assert cfg.endpoints[0].url == "https://example.com/v1/messages"


def test_relative_base_url_rejected(tmp_path):
    text = BASE.replace('base_url = "https://example.com/v1"', 'base_url = "example.com/v1"')
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, text), demo=True)
