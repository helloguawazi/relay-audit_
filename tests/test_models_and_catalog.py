"""Model identity normalisation and price extraction.

The bug these tests exist to prevent: a relay published 'Claude Opus 5' as a
display name, the matcher compared it against the id-shaped pattern
'claude-opus-5', nothing matched, and seven models silently fell out of the
comparison table. Identity errors are the highest-risk failure mode here
because they produce a table that looks complete and is wrong.
"""

from __future__ import annotations

import pytest

from relay_audit.catalog import parse_models_payload
from relay_audit.models import classify, matches_pattern, normalise

SPECS = {
    "claude-sonnet-5": {"display": "Claude Sonnet 5", "match": ["claude-sonnet-5"]},
    "claude-sonnet-4-6": {"display": "Claude Sonnet 4.6", "match": ["claude-sonnet-4.6"]},
    "claude-opus-5": {"display": "Claude Opus 5", "match": ["claude-opus-5"]},
    "claude-opus-4-8": {"display": "Claude Opus 4.8", "match": ["claude-opus-4.8"]},
    "gpt-5.6-terra": {"display": "GPT-5.6 Terra", "match": ["gpt-5.6-terra"]},
}


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("claude-sonnet-5", "claude-sonnet-5"),
        ("anthropic/claude-sonnet-5", "claude-sonnet-5"),
        ("Claude-Sonnet-5", "claude-sonnet-5"),
        ("Claude Opus 4.8", "claude-opus-4-8"),
        ("claude-opus-4.8", "claude-opus-4-8"),
        ("anthropic/claude-opus-4-8", "claude-opus-4-8"),
        ("aws/anthropic/claude-sonnet-5", "claude-sonnet-5"),
        ("~deepseek/deepseek-pro-latest", "deepseek-deepseek-pro"),
        ("meta-llama/llama-3.1-70b", "meta-llama-llama-3-1-70b"),
        ("GPT-5.6 Terra", "gpt-5-6-terra"),
        ("claude-sonnet-5-20250101", "claude-sonnet-5"),
    ],
)
def test_normalise_folds_all_published_shapes(raw, expected):
    assert normalise(raw)[0] == expected


@pytest.mark.parametrize(
    "raw,variant",
    [("claude-sonnet-5-thinking", "thinking"), ("claude-opus-5-high", "high")],
)
def test_variant_suffix_is_extracted_not_discarded(raw, variant):
    base, got = normalise(raw)
    assert got == variant
    assert base == raw.rsplit("-", 1)[0]


@pytest.mark.parametrize(
    "raw,expected_key",
    [
        ("Claude Sonnet 5", "claude-sonnet-5"),
        ("claude-sonnet-5", "claude-sonnet-5"),
        ("anthropic/claude-sonnet-5", "claude-sonnet-5"),
        ("Claude Sonnet 4.6", "claude-sonnet-4-6"),
        ("Claude Opus 4.8", "claude-opus-4-8"),
        ("Claude Opus 5", "claude-opus-5"),
        ("gpt-5.6-terra", "gpt-5.6-terra"),
        ("GPT-5.6 Terra", "gpt-5.6-terra"),
        ("deepseek/deepseek-v4-pro", None),
    ],
)
def test_classify_matches_display_names_and_ids(raw, expected_key):
    assert classify(raw, SPECS) == expected_key


def test_versions_do_not_collapse_into_each_other():
    """Opus 4.6/4.7/4.8/5 are priced differently and must stay separate."""
    assert classify("Claude Opus 4.8", SPECS) == "claude-opus-4-8"
    assert classify("Claude Opus 5", SPECS) == "claude-opus-5"
    assert classify("Claude Opus 4.8", SPECS) != classify("Claude Opus 5", SPECS)


def test_sonnet_5_and_sonnet_4_6_stay_separate():
    assert classify("Claude Sonnet 5", SPECS) != classify("Claude Sonnet 4.6", SPECS)


def test_aliases_win_over_broader_patterns():
    specs = {
        "broad": {"match": ["claude-opus-*"]},
        "exact": {"aliases": ["claude-opus-4.8"], "match": ["claude-opus-4.8"]},
    }
    assert classify("Claude Opus 4.8", specs) == "exact"
    assert classify("Claude Opus 4.6", specs) == "broad"


def test_glob_pattern_ignores_separator_style():
    assert matches_pattern("Claude Opus 4.8", "claude-opus-4.8")
    assert matches_pattern("anthropic/claude-opus-4-8", "claude-opus-4.8")
    assert not matches_pattern("Claude Opus 5", "claude-opus-4.8")


def test_unmatched_is_reported_not_dropped():
    assert classify("some/other-model", SPECS) is None


# --- price extraction -------------------------------------------------------


def test_extracts_display_name_shaped_ids_and_strips_routes():
    """Payload shaped like the relay that triggered the original bug."""
    payload = {
        "code": 0,
        "data": [
            {
                "slug": "claude-opus-5",
                "name": "Claude Opus 5",
                "billing_mode": "token",
                "input_price": 20.0,
                "output_price": 120.0,
                "cache_read_price": 0.0,
                "cache_write_price": 35.0,
                "is_promo": False,
                "routes": [{"input_price": 20.0, "output_price": 120.0, "route_slug": "lowcost"}],
            }
        ],
    }
    prices, unmatched = parse_models_payload(payload, "CNY", 7.1)
    assert unmatched == []
    assert len(prices) == 1
    p = prices[0]
    assert p.model_id == "claude-opus-5"
    assert p.native_input == 20.0
    assert p.input_usd == pytest.approx(20.0 / 7.1, rel=1e-6)
    # A declared-CNY endpoint is quoted per million tokens, never per token.
    assert p.output_usd == pytest.approx(120.0 / 7.1, rel=1e-6)
    assert p.cache_read_usd == 0.0
    assert p.currency_native == "CNY"


def test_multi_route_spread_is_recorded_not_hidden():
    """Reporting only the cheapest route would cherry-pick the best number."""
    payload = {
        "data": [
            {
                "slug": "claude-opus-4-8",
                "input_price": 14.0,
                "output_price": 65.0,
                "routes": [
                    {"input_price": 14.0, "output_price": 65.0},
                    {"input_price": 35.0, "output_price": 130.0},
                    {"input_price": 20.0, "output_price": 90.0},
                ],
            }
        ]
    }
    prices, _ = parse_models_payload(payload, "CNY", 7.1)
    p = prices[0]
    assert p.route_count == 3
    assert p.input_spread == (14.0, 35.0)
    assert p.output_spread == (65.0, 130.0)


def test_prices_without_a_price_field_are_not_invented():
    """A bare model list must yield no prices, so the table says 未采集到."""
    payload = {"data": [{"id": "claude-sonnet-5"}, {"id": "claude-opus-5"}]}
    prices, unmatched = parse_models_payload(payload, "USD", None)
    assert prices == []
    assert sorted(unmatched) == ["claude-opus-5", "claude-sonnet-5"]


def test_openrouter_per_token_prices_are_scaled_to_per_million():
    payload = {
        "data": [
            {
                "id": "anthropic/claude-sonnet-5",
                "pricing": {"prompt": "0.000002", "completion": "0.00001", "input_cache_read": "0.0000002"},
            }
        ]
    }
    prices, _ = parse_models_payload(payload, "USD", None)
    p = prices[0]
    assert p.input_usd == pytest.approx(2.0)
    assert p.output_usd == pytest.approx(10.0)
    assert p.cache_read_usd == pytest.approx(0.2)


def test_cny_without_an_fx_rate_yields_a_null_not_a_wrong_number():
    payload = {"data": [{"id": "claude-sonnet-5", "input_price": 15.0, "output_price": 105.0}]}
    prices, _ = parse_models_payload(payload, "CNY", None)
    p = prices[0]
    assert p.input_usd is None
    assert p.output_usd is None
    assert p.native_input == 15.0
    assert "无法换算" in (p.note or "")
