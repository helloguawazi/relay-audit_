"""Report generation: raw.json, env.json, report.md."""

from __future__ import annotations

import json
import platform
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .config import Config
from .stats import fmt, fmt_int


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def egress_country() -> str:
    """Best-effort egress country. Recorded because latency without a vantage point is meaningless."""
    try:
        import httpx

        r = httpx.get("https://ipinfo.io/json", timeout=6.0)
        if r.status_code == 200:
            data = r.json()
            return f"{data.get('country', '?')} ({data.get('city', '?')}, {data.get('org', '?')})"
    except Exception:
        pass
    return "unknown (offline or blocked)"


def build_env(cfg: Config, suites: list[str], seed: int) -> dict:
    return {
        "tool": "relay-audit",
        "tool_version": __version__,
        "generated_at": utcnow(),
        "seed": seed,
        "suites": suites,
        "demo_mode": cfg.demo,
        "runner": {
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "egress_country": egress_country(),
        },
        "endpoints": [
            {
                "id": e.id,
                "label": e.label,
                "role": e.role,
                "protocol": e.protocol,
                "base_url": e.base_url,
                "model": e.model,
                "configured_rate": e.rate,
            }
            for e in cfg.endpoints
        ],
        "official_rates": cfg.official_rates,
        "warnings": [
            "Latency numbers are valid only for the runner recorded above. "
            "Do not compare across runners.",
            "This file is required alongside any published result: a latency number "
            "without its vantage point is not a measurement.",
        ]
        + (["DEMO MODE: all data in this report is synthetic."] if cfg.demo else []),
    }


def cost_accounting(cfg: Config, findings: dict) -> dict:
    """Effective cost from actual reported usage, plus markup against published rates."""
    out: dict = {}
    for ep in cfg.endpoints:
        rate = ep.rate
        if rate is None:
            official = cfg.official_rates.get(ep.model)
            if official:
                rate = {
                    "input": official.get("input"),
                    "output": official.get("output"),
                    "cache_read": official.get("cache_read"),
                }
        if rate is None:
            out[ep.id] = {"available": False, "reason": "no rate configured for this endpoint"}
            continue

        agg = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "requests": 0}
        for suite_name, suite_findings in findings.items():
            if suite_name == "billing":
                recon = suite_findings.get("token_reconciliation", {})
                reported = recon.get("reported_input_tokens")
                if reported:
                    agg["input_tokens"] += reported
                    agg["requests"] += 1
            if suite_name == "speed":
                for row in suite_findings.get("_usage_rows", []):
                    agg["input_tokens"] += row.get("input_tokens") or 0
                    agg["output_tokens"] += row.get("output_tokens") or 0
                    agg["cache_read_tokens"] += row.get("cache_read_tokens") or 0
                    agg["requests"] += 1
            if suite_name == "cache":
                for row in suite_findings.get("_usage_rows", []):
                    agg["input_tokens"] += row.get("input_tokens") or 0
                    agg["output_tokens"] += row.get("output_tokens") or 0
                    agg["cache_read_tokens"] += row.get("cache_read_tokens") or 0
                    agg["requests"] += 1

        billable_input = max(0, agg["input_tokens"] - agg["cache_read_tokens"])
        cost = 0.0
        if rate.get("input") is not None:
            cost += billable_input / 1e6 * rate["input"]
        if rate.get("output") is not None:
            cost += agg["output_tokens"] / 1e6 * rate["output"]
        if rate.get("cache_read") is not None:
            cost += agg["cache_read_tokens"] / 1e6 * rate["cache_read"]

        official = cfg.official_rates.get(ep.model)
        markup = None
        if official and rate.get("input") and official.get("input"):
            markup = round(rate["input"] / official["input"], 3)

        out[ep.id] = {
            "available": True,
            "rate_used_usd_per_mtok": rate,
            "rate_is_from_official_table": ep.rate is None,
            "totals": agg,
            "billable_input_tokens": billable_input,
            "estimated_cost_usd": round(cost, 6),
            "markup_ratio_vs_official_input": markup,
            "note": (
                "Estimated from reported usage and the configured rate. "
                "Reconcile against your provider dashboard; this tool cannot read your invoice."
            ),
        }
    return out


def build_report(cfg: Config, env: dict, findings: dict, results_by_suite: dict, costs: dict) -> str:
    lines: list[str] = []
    now = env["generated_at"]
    ep_by_id = {e.id: e for e in cfg.endpoints}

    lines.append("# relay-audit report")
    lines.append("")
    lines.append(f"- **Run at**: {now}")
    lines.append(f"- **Runner**: `{env['runner']['hostname']}` · {env['runner']['platform']} · Python {env['runner']['python']}")
    lines.append(f"- **Egress**: {env['runner']['egress_country']}")
    lines.append(f"- **Seed**: `{env['seed']}` · **Suites**: {', '.join(env['suites'])}")
    if env["demo_mode"]:
        lines.append("")
        lines.append("> **DEMO MODE — every number below is synthetic.** Nothing here reflects any real endpoint.")
    lines.append("")
    lines.append(
        "> Latency numbers are valid **only** for the runner recorded above. "
        "Comparing them against results from a different runner is invalid."
    )
    lines.append("")

    # --- headline verdicts ---
    lines.append("## Verdicts")
    lines.append("")
    lines.append("| endpoint | role | cache honesty | failures | model id echo |")
    lines.append("|---|---|---|---|---|")
    for ep in cfg.endpoints:
        cache = findings.get("cache", {}).get(ep.id, {})
        speed = findings.get("speed", {}).get(ep.id, {})
        billing = findings.get("billing", {}).get(ep.id, {})
        verdict = cache.get("verdict", "not run")
        failures = speed.get("failure_rate_pct")
        fails = "—" if failures is None else f"{failures}%"
        ident = billing.get("model_identity", {})
        echo = "—" if not ident else ("mismatch" if ident.get("mismatch") else "match")
        lines.append(f"| {ep.label} | {ep.role} | `{verdict}` | {fails} | {echo} |")
    lines.append("")

    # --- speed ---
    if "speed" in findings:
        lines.append("## Speed")
        lines.append("")
        lines.append(
            "Warm-ups discarded. `tps` is output tokens over the generation window "
            "(first delta to last delta), not including prefill."
        )
        lines.append("")
        lines.append("| endpoint | n ok | failures | TTFT p50 | TTFT p90 | TTFT p99 | total p50 | connect p50 | tps p50 |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for ep in cfg.endpoints:
            f = findings["speed"].get(ep.id)
            if not f:
                continue
            t = f["ttft_ms"]
            o = f["total_ms"]
            c = f["connect_ms"]
            s = f["tps"]
            lines.append(
                f"| {ep.label} | {t['n']} | {f['failures']} | {fmt(t['p50'], ' ms')} | {fmt(t['p90'], ' ms')} | "
                f"{fmt(t['p99'], ' ms')} | {fmt(o['p50'], ' ms')} | {fmt(c['p50'], ' ms')} | {fmt(s['p50'], '', 2)} |"
            )
        lines.append("")
        for ep in cfg.endpoints:
            f = findings["speed"].get(ep.id)
            if f and f["errors"]:
                lines.append(f"**{ep.label} errors** ({f['failures']} of {f['requests']} requests):")
                lines.append("")
                for err in f["errors"]:
                    lines.append(f"- `{err}`")
                lines.append("")

    # --- cache ---
    if "cache" in findings:
        lines.append("## Cache honesty")
        lines.append("")
        lines.append(
            "Two independent signals must agree: the **declared** counter "
            "(`cache_read_input_tokens` / `prompt_tokens_details.cached_tokens`) and the "
            "**physical** wall-clock drop on the warm pass. A counter without a speedup is decorative."
        )
        lines.append("")
        lines.append("| endpoint | declared read (warm, max) | TTFT cold | TTFT warm (median) | ratio | physical drop | verdict |")
        lines.append("|---|---|---|---|---|---|---|")
        for ep in cfg.endpoints:
            f = findings["cache"].get(ep.id)
            if not f:
                continue
            warm = f["warm"]["ttft_summary"]
            warm_median = warm.get("p50")
            lines.append(
                f"| {ep.label} | {fmt_int(f['warm']['declared_read_max'])} | "
                f"{fmt(f['cold']['ttft_ms'], ' ms')} | {fmt(warm_median, ' ms')} | "
                f"{fmt(f['ttft_ratio_cold_over_warm'], '×', 2)} | "
                f"{'yes' if f['physical_speedup'] else 'no'} | `{f['verdict']}` |"
            )
        lines.append("")
        for ep in cfg.endpoints:
            f = findings["cache"].get(ep.id)
            if not f:
                continue
            lines.append(f"- **{ep.label}** — `{f['verdict']}`: {f['verdict_note']}")
            lines.append(
                f"  - cold: read={fmt_int(f['cold']['cache_read'])} "
                f"write={fmt_int(f['cold']['cache_write'])} input={fmt_int(f['cold']['input_tokens'])}"
            )
            if f["expired"]["ran"]:
                lines.append(
                    f"  - after TTL: read={fmt_int(f['expired']['cache_read'])} "
                    f"ttft={fmt(f['expired']['ttft_ms'], ' ms')}"
                )
            else:
                lines.append("  - after TTL: not run (cache_ttl_seconds = 0)")
            lines.append(
                f"  - usage fields the endpoint returned: "
                f"{', '.join('`' + x + '`' for x in f['usage_fields_present']) or '**none**'}"
            )
        lines.append("")

    # --- billing ---
    if "billing" in findings:
        lines.append("## Billing honesty")
        lines.append("")
        lines.append("| endpoint | reported input | local exact | local approx | drift | within tol | model echo |")
        lines.append("|---|---|---|---|---|---|---|")
        for ep in cfg.endpoints:
            f = findings["billing"].get(ep.id)
            if not f:
                continue
            r = f["token_reconciliation"]
            ident = f["model_identity"]
            lines.append(
                f"| {ep.label} | {fmt_int(r['reported_input_tokens'])} | {fmt_int(r['local_exact_tokens'])} | "
                f"{fmt_int(r['local_approx_tokens'])} | {fmt(r['drift_pct_vs_baseline'], '%')} | "
                f"{'yes' if r['within_tolerance'] else 'no'} | {ident.get('echoed') or '—'} |"
            )
        lines.append("")
        for ep in cfg.endpoints:
            f = findings["billing"].get(ep.id)
            if not f:
                continue
            fb = f["failed_request_probe"]
            lines.append(f"**{ep.label}**")
            lines.append("")
            for probe in fb["probes"]:
                state = "did NOT fail" if probe["ok"] else f"failed ({probe['status']})"
                lines.append(
                    f"- `{probe['label']}`: {state}; content_chars={probe['content_chars']}; "
                    f"usage={'reported' if probe['reported_usage'] else 'none'}"
                )
            if fb["probes_that_did_not_fail"]:
                lines.append(
                    f"- ⚠️ probes that should have failed but returned success: "
                    f"{', '.join('`' + x + '`' for x in fb['probes_that_did_not_fail'])}"
                )
            if fb["suspected_billed_failures"]:
                lines.append(
                    f"- ⚠️ probes answered with billable output: "
                    f"{', '.join('`' + x + '`' for x in fb['suspected_billed_failures'])}"
                )
            lines.append(f"- post-failure request: {'ok' if fb['post_failure_ok'] else 'failed'}")
            lines.append("")

    # --- cost ---
    if costs:
        lines.append("## Cost")
        lines.append("")
        lines.append("Estimates from **reported usage** and the configured rates — not from marketing pages.")
        lines.append("")
        lines.append("| endpoint | rate source | input $/M | output $/M | cache read $/M | markup vs official | est. cost for this run |")
        lines.append("|---|---|---|---|---|---|---|")
        for ep in cfg.endpoints:
            c = costs.get(ep.id, {})
            if not c.get("available"):
                lines.append(f"| {ep.label} | — | — | — | — | — | not configured |")
                continue
            rate = c["rate_used_usd_per_mtok"]
            src = "official table" if c["rate_is_from_official_table"] else "endpoint config"
            markup = c["markup_ratio_vs_official_input"]
            lines.append(
                f"| {ep.label} | {src} | {fmt(rate.get('input'), '', 3)} | {fmt(rate.get('output'), '', 3)} | "
                f"{fmt(rate.get('cache_read'), '', 3)} | "
                f"{'—' if markup is None else f'{markup}×'} | ${c['estimated_cost_usd']:.5f} |"
            )
        lines.append("")
        for ep in cfg.endpoints:
            official = cfg.official_rates.get(ep.model)
            if official and official.get("_unverified"):
                lines.append(
                    f"- ⚠️ **{ep.model}** rates are marked unverified: `rates.toml` entry is missing a "
                    f"`source` or `retrieved` date."
                )
        lines.append("")

    # --- limitations ---
    lines.append("## Limitations (read before quoting any number above)")
    lines.append("")
    lines.append(
        "1. **One vantage point.** These latencies describe the route from the runner above, "
        "not the endpoint in general."
    )
    lines.append(
        "2. **Upstream identity is not verifiable from the client.** A relay may forward to the "
        "official API or to a pool of subscription accounts. Nothing here distinguishes those."
    )
    lines.append(
        "3. **TTFT depends on co-tenants.** You share upstream capacity with everyone else on "
        "the channel. One time window is an anecdote; run at several hours of the day."
    )
    lines.append(
        "4. **`cache_read` counters are self-reported** and are the most contested field in the "
        "relay ecosystem. That is why this report requires the physical TTFT signal to agree."
    )
    lines.append(
        "5. **Cost figures are estimates** from reported usage. Reconcile against a real invoice."
    )
    lines.append(
        "6. **Vendor-run results are weak evidence.** The value of this tool comes from third "
        "parties running it against a vendor, not the vendor running it against itself."
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("Generated by [relay-audit](https://github.com/) — methodology in `README.md`.")
    return "\n".join(lines) + "\n"


def write_outputs(
    out_dir: Path,
    env: dict,
    findings: dict,
    results_by_suite: dict,
    costs: dict,
    report_md: str,
    request_log: list[dict],
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "env": out_dir / "env.json",
        "raw": out_dir / "raw.json",
        "findings": out_dir / "findings.json",
        "report": out_dir / "report.md",
    }
    paths["env"].write_text(json.dumps(env, indent=2, ensure_ascii=False), encoding="utf-8")
    paths["raw"].write_text(
        json.dumps({"requests": request_log}, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    paths["findings"].write_text(
        json.dumps({"findings": findings, "costs": costs}, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    paths["report"].write_text(report_md, encoding="utf-8")
    return paths
