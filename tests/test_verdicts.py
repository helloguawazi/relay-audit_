"""Verdict matrix: declared counter vs physical speedup.

This is the core logic of the cache suite, so it gets its own table-driven test.
The decision table is imported from the real code, not reimplemented here.
"""

from __future__ import annotations

import pytest

from relay_audit.suites import cache_verdict


def verdict_for(declared_hit: bool, cold_ttft: float, warm_ttft: float, min_ratio: float = 1.15) -> str:
    return cache_verdict(declared_hit, cold_ttft, warm_ttft, min_ratio)[0]


@pytest.mark.parametrize(
    "declared,cold,warm,expected",
    [
        # honest cache
        (True, 1400.0, 350.0, "consistent"),
        # reports hits, wall clock flat -> the failure this suite exists to catch
        (True, 1400.0, 1390.0, "counter-only"),
        (True, 1400.0, 1400.0, "counter-only"),
        # faster without declaring anything
        (False, 1400.0, 300.0, "speed-only"),
        # nothing at all
        (False, 1400.0, 1400.0, "no-cache"),
        # exactly at the threshold counts as physical evidence
        (True, 1150.0, 1000.0, "consistent"),
        # just under the threshold does not
        (True, 1140.0, 1000.0, "counter-only"),
    ],
)
def test_verdict_matrix(declared, cold, warm, expected):
    assert verdict_for(declared, cold, warm) == expected


def test_counter_only_is_not_mistaken_for_honest():
    """A fake counter must never be graded as consistent."""
    assert verdict_for(True, 1400.0, 1450.0) != "consistent"
    assert verdict_for(True, 1400.0, 1450.0) == "counter-only"


def test_ratio_is_reported_for_consistent_verdict():
    verdict, note, ratio = cache_verdict(True, 1400.0, 350.0, 1.15)
    assert verdict == "consistent"
    assert ratio == pytest.approx(4.0)
    assert "measurably faster" in note


def test_missing_ttft_never_produces_a_cache_claim():
    """If the clock produced nothing, the tool must not invent a speedup."""
    for cold, warm in ((None, None), (1400.0, None), (None, 300.0)):
        verdict, _, ratio = cache_verdict(True, cold, warm, 1.15)
        assert ratio is None
        assert verdict == "counter-only"
