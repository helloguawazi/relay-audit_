"""Test suites: speed, cache honesty, billing honesty.

Each suite returns (results, findings) where `findings` are the interpreted
conclusions. Results stay raw; findings are always traceable to result rows.
"""

from __future__ import annotations

import time
import uuid
from typing import Callable

from .client import Client, Result
from .config import Config, Endpoint
from .prompts import (
    billing_prompt,
    cache_prompt,
    count_tokens_approx,
    count_tokens_exact,
    speed_prompt,
)
from .stats import summarise

Progress = Callable[[str], None]

# Demo-only: which behaviour each endpoint id should simulate.
DEMO_BEHAVIOR = {
    "candidate": "honest",
    "peer": "counter-only-fake",
    "openrouter": "no-cache",
}


def _noop(_: str) -> None:
    pass


def _client(cfg: Config, ep: Endpoint) -> Client:
    return Client(ep, cfg.tests, demo=cfg.demo, demo_behavior=DEMO_BEHAVIOR)


def _sleep_visible(seconds: float, progress: Progress, reason: str) -> None:
    """Sleep without going silent. A long silent wait looks like a hang."""
    if seconds <= 0:
        return
    if seconds <= 3:
        progress(f"    {reason} ({seconds:g}s)")
        time.sleep(seconds)
        return
    progress(f"    {reason}: {seconds / 60:.1f} min (cache TTLs cannot be shortened; Ctrl+C to abort)")
    deadline = time.monotonic() + seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(30.0, remaining))
        remaining = deadline - time.monotonic()
        if remaining > 0:
            progress(f"      {remaining / 60:.1f} min remaining")


def run_speed(cfg: Config, ep: Endpoint, seed: int, progress: Progress = _noop) -> tuple[list[Result], dict]:
    p = cfg.tests
    results: list[Result] = []
    with _client(cfg, ep) as client:
        for i in range(p.warmup):
            progress(f"    warm-up {i + 1}/{p.warmup}")
            client.request(speed_prompt(p.speed_prompt_tokens, seed, i), p.speed_max_tokens, "speed", f"warmup-{i}")
        for i in range(p.speed_requests):
            progress(f"    request {i + 1}/{p.speed_requests}")
            results.append(
                client.request(
                    speed_prompt(p.speed_prompt_tokens, seed, i + 100),
                    p.speed_max_tokens,
                    "speed",
                    f"req-{i + 1}",
                )
            )

    ok = [r for r in results if r.ok]
    findings = {
        "endpoint_id": ep.id,
        "requests": len(results),
        "failures": len(results) - len(ok),
        "failure_rate_pct": round(100.0 * (len(results) - len(ok)) / len(results), 1) if results else None,
        "ttft_ms": summarise([r.ttft_ms for r in ok]),
        "total_ms": summarise([r.total_ms for r in ok]),
        "connect_ms": summarise([r.connect_ms for r in ok]),
        "tps": summarise([r.tps for r in ok]),
        "model_mismatches": [r.model_echoed for r in results if r.model_echoed and r.model_echoed != ep.model],
        "errors": sorted({r.error for r in results if r.error}),
    }
    return results, findings


def cache_verdict(
    declared_hit: bool, cold_ttft: float | None, warm_ttft: float | None, min_ratio: float
) -> tuple[str, str, float | None]:
    """The decision table for the cache suite.

    Two independent signals must agree:
      * declared — the endpoint reports cache_read > 0 on the warm pass
      * physical — the warm pass is measurably faster than the cold pass

    Returns (verdict, note, ratio).
    """
    ratio: float | None = None
    if cold_ttft and warm_ttft and warm_ttft > 0:
        ratio = cold_ttft / warm_ttft
    physical_drop = bool(ratio is not None and ratio >= min_ratio)

    if declared_hit and physical_drop:
        return (
            "consistent",
            "declared cache hits and the warm pass is measurably faster",
            ratio,
        )
    if declared_hit and not physical_drop:
        return (
            "counter-only",
            "reports cache_read > 0 but the warm pass shows no meaningful speedup: "
            "the counter is not backed by a real prefill skip",
            ratio,
        )
    if not declared_hit and physical_drop:
        return (
            "speed-only",
            "warm pass is faster without declaring any cache read: either caching is "
            "real but unreported, or the speedup has another cause",
            ratio,
        )
    return (
        "no-cache",
        "neither a declared hit nor a physical speedup was observed",
        ratio,
    )


def run_cache(cfg: Config, ep: Endpoint, seed: int, progress: Progress = _noop) -> tuple[list[Result], dict]:
    """Cold -> warm x N -> expired. Requires the physical signal to agree with the declared one."""
    p = cfg.tests
    cold_token = uuid.uuid4().hex[:8]
    results: list[Result] = []

    def one(label: str, pass_id: str, extra: dict | None = None) -> Result:
        prompt = cache_prompt(p.cache_prefix_tokens, seed, pass_id, cold_token)
        return client.request(prompt, p.cache_max_tokens, "cache", label, extra=extra)

    with _client(cfg, ep) as client:
        progress(f"    pass A (cold), cache namespace {cold_token}")
        cold = one("A-cold", "A", {"phase": "cold"})
        results.append(cold)

        warm: list[Result] = []
        for i in range(p.cache_warm_passes):
            progress(f"    pass B{i + 1} (warm)")
            r = one(f"B{i + 1}-warm", "B", {"phase": "warm", "iteration": i + 1})
            warm.append(r)
            results.append(r)

        expired: Result | None = None
        ttl = p.cache_ttl_seconds
        if cfg.demo:
            # The demo exists to validate the harness, not to wait out a real TTL.
            ttl = min(ttl, 1)
        if ttl > 0:
            _sleep_visible(ttl, progress, "waiting for cache TTL to lapse")
            progress("    pass C (after TTL)")
            expired = one("C-expired", "C", {"phase": "expired"})
            results.append(expired)

    cold_read = cold.usage.cache_read_tokens
    warm_reads = [r.usage.cache_read_tokens for r in warm if r.ok]
    warm_ttft = [r.ttft_ms for r in warm if r.ok and r.ttft_ms is not None]
    cold_ttft = cold.ttft_ms

    warm_read_max = max([v for v in warm_reads if v is not None], default=None)
    declared_hit = bool(warm_read_max and warm_read_max > 0)

    warm_median = None
    if warm_ttft:
        import statistics

        warm_median = statistics.median(warm_ttft)

    verdict, verdict_note, ratio = cache_verdict(
        declared_hit, cold_ttft, warm_median, p.cache_min_speedup_ratio
    )
    physical_drop = bool(ratio is not None and ratio >= p.cache_min_speedup_ratio)

    expired_read = expired.usage.cache_read_tokens if expired else None

    findings = {
        "endpoint_id": ep.id,
        "cold_namespace": cold_token,
        "cache_prefix_tokens_target": p.cache_prefix_tokens,
        "cold": {
            "ok": cold.ok,
            "error": cold.error,
            "ttft_ms": cold.ttft_ms,
            "cache_read": cold_read,
            "cache_write": cold.usage.cache_write_tokens,
            "input_tokens": cold.usage.input_tokens,
        },
        "warm": {
            "declared_reads": warm_reads,
            "declared_read_max": warm_read_max,
            "ttft_ms": [round(v, 2) for v in warm_ttft],
            "ttft_summary": summarise(warm_ttft),
        },
        "expired": {
            "ran": expired is not None,
            "ttft_ms": expired.ttft_ms if expired else None,
            "cache_read": expired_read,
            "cache_write": expired.usage.cache_write_tokens if expired else None,
        },
        "ttft_ratio_cold_over_warm": round(ratio, 3) if ratio is not None else None,
        "min_speedup_ratio_required": p.cache_min_speedup_ratio,
        "declared_hit": declared_hit,
        "physical_speedup": physical_drop,
        "verdict": verdict,
        "verdict_note": verdict_note,
        "usage_fields_present": sorted(cold.usage.raw.keys()),
    }
    return results, findings


def run_billing(cfg: Config, ep: Endpoint, seed: int, progress: Progress = _noop) -> tuple[list[Result], dict]:
    """Token reconciliation, model identity, and whether failures are billed."""
    p = cfg.tests
    results: list[Result] = []

    prompt = billing_prompt(p.speed_prompt_tokens, seed)
    approx = count_tokens_approx(prompt)
    exact, exact_source = count_tokens_exact(prompt)

    with _client(cfg, ep) as client:
        progress("    token reconciliation (non-streaming, usage required)")
        recon = client.request(prompt, 8, "billing", "reconcile", stream=False)
        results.append(recon)

        progress("    model identity check")
        identity = client.request(prompt, 8, "billing", "identity", stream=False)
        results.append(identity)

        progress("    failed-request probe 1/2 (invalid model id)")
        fail1 = client.request(
            prompt, 8, "billing", "fail-invalid-model", stream=False,
            model="__relay_audit_nonexistent_model__",
        )
        results.append(fail1)

        progress("    failed-request probe 2/2 (impossible max_tokens)")
        fail2 = client.request(prompt, 10**9, "billing", "fail-max-tokens", stream=False)
        results.append(fail2)

        progress("    post-failure valid request")
        after = client.request(prompt, 8, "billing", "post-failure", stream=False)
        results.append(after)

    reported = recon.usage.input_tokens
    drift_pct: float | None = None
    baseline = exact if exact is not None else approx
    if reported is not None and baseline:
        drift_pct = round(100.0 * (reported - baseline) / baseline, 2)

    within_tolerance = drift_pct is not None and abs(drift_pct) <= p.billing_tolerance_pct

    failed = [r for r in results if r.label.startswith("fail-")]

    def billed(probe: Result) -> bool:
        """A probe that was expected to fail, but was answered with billable output.

        Two shapes count as suspected billing for a doomed request:
          * the probe came back HTTP 200 and produced content, and
          * the probe came back with an error status but still reported usage.
        """
        if probe.ok and probe.content_chars > 0:
            return True
        if probe.status is not None and probe.status >= 400 and probe.usage.has_any:
            return True
        return False

    suspected_billed = [r.label for r in failed if billed(r)]
    probes_that_did_not_fail = [r.label for r in failed if r.ok]

    identity_mismatch = bool(
        identity.model_echoed and identity.model_echoed != identity.model_requested
    )

    findings = {
        "endpoint_id": ep.id,
        "token_reconciliation": {
            "prompt_chars": len(prompt),
            "reported_input_tokens": reported,
            "local_approx_tokens": approx,
            "local_exact_tokens": exact,
            "local_exact_source": exact_source,
            "drift_pct_vs_baseline": drift_pct,
            "baseline_used": "exact" if exact is not None else "approx",
            "tolerance_pct": p.billing_tolerance_pct,
            "within_tolerance": within_tolerance,
            "note": (
                "Drift is reported, not pass/fail. Tokenizers differ across model "
                "families, so only large drift is meaningful."
            ),
        },
        "failed_request_probe": {
            "probes": [
                {"label": r.label, "status": r.status, "ok": r.ok, "error": (r.error or "")[:200],
                 "content_chars": r.content_chars,
                 "reported_usage": r.usage.to_dict() if r.usage.has_any else None}
                for r in failed
            ],
            "suspected_billed_failures": suspected_billed,
            "probes_that_did_not_fail": probes_that_did_not_fail,
            "post_failure_ok": after.ok,
            "post_failure_status": after.status,
            "interpretation": (
                "A probe that did not fail means the endpoint accepted a request that "
                "cannot legitimately be served (a nonexistent model id, or max_tokens "
                "far beyond any model limit). That is a signal about channel honesty, "
                "and it matters for billing because such requests are often still charged. "
                "Confirm with the provider dashboard; this tool cannot read your invoice."
            ),
        },
        "model_identity": {
            "requested": identity.model_requested,
            "echoed": identity.model_echoed,
            "mismatch": identity_mismatch,
            "note": (
                "A mismatch means the endpoint answered with a different model id "
                "than requested. Silent channel substitution looks exactly like this."
            ),
        },
        "usage_fields_present": sorted(set(recon.usage.raw.keys()) | set(after.usage.raw.keys())),
    }
    return results, findings


SUITES = {
    "speed": run_speed,
    "cache": run_cache,
    "billing": run_billing,
}
