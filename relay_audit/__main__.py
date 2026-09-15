"""CLI entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import ConfigError, load_config, load_models
from . import __version__
from .catalog import build_catalog, render_markdown, utcnow as catalog_utcnow
from .report import build_env, build_report, cost_accounting, utcnow, write_outputs
from .suites import SUITES

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config.toml"
DEFAULT_RATES = ROOT / "rates.toml"
DEFAULT_MODELS = ROOT / "models.toml"
DEFAULT_ENV = ROOT / ".env"

DEMO_BEHAVIOR = {
    "candidate": "honest",
    "peer": "counter-only-fake",
    "openrouter": "no-cache",
}


def estimate_plan(cfg) -> dict:
    p = cfg.tests
    per_endpoint = {
        "speed_requests": p.warmup + p.speed_requests,
        "cache_requests": 1 + p.cache_warm_passes + (1 if p.cache_ttl_seconds > 0 else 0),
        "billing_requests": 5,
    }
    per_endpoint["total_requests"] = sum(per_endpoint.values())
    cache_prompt_tokens = p.cache_prefix_tokens + 40
    input_tokens = (
        per_endpoint["speed_requests"] * p.speed_prompt_tokens
        + per_endpoint["cache_requests"] * cache_prompt_tokens
        + per_endpoint["billing_requests"] * p.speed_prompt_tokens
    )
    output_tokens = per_endpoint["speed_requests"] * p.speed_max_tokens + per_endpoint["cache_requests"] * p.cache_max_tokens + per_endpoint["billing_requests"] * 8
    estimate = {"per_endpoint": per_endpoint, "input_tokens": input_tokens, "output_tokens": output_tokens}

    costs = {}
    for ep in cfg.endpoints:
        rate = ep.rate or cfg.official_rates.get(ep.model) or {}
        cost = 0.0
        if rate.get("input") is not None:
            cost += input_tokens / 1e6 * rate["input"]
        if rate.get("output") is not None:
            cost += output_tokens / 1e6 * rate["output"]
        costs[ep.id] = round(cost, 5)
    estimate["estimated_cost_usd"] = costs
    estimate["estimated_total_usd"] = round(sum(costs.values()), 5)
    return estimate


def cmd_plan(args) -> int:
    cfg = _load(args)
    est = estimate_plan(cfg)
    print(f"config: {args.config}")
    print(f"endpoints ({len(cfg.endpoints)}):")
    for ep in cfg.endpoints:
        key_state = "demo" if cfg.demo else ("set" if ep.api_key else "MISSING")
        print(f"  - {ep.id:12s} role={ep.role:9s} proto={ep.protocol:9s} model={ep.model:28s} key={key_state}")
        print(f"    {ep.base_url}")
    print()
    print("planned requests per endpoint:")
    for k, v in est["per_endpoint"].items():
        print(f"  {k:20s} {v}")
    print()
    print(f"approx input tokens : {est['input_tokens']:,}")
    print(f"approx output tokens: {est['output_tokens']:,}")
    print()
    print("estimated spend (upper bound, ignores cache discounts and failed requests):")
    for ep_id, cost in est["estimated_cost_usd"].items():
        print(f"  {ep_id:12s} ${cost:.5f}")
    print(f"  {'TOTAL':12s} ${est['estimated_total_usd']:.5f}")
    print()
    if any(v == 0.0 for v in est["estimated_cost_usd"].values()):
        print("note: a $0.00000 estimate means no rate was configured for that endpoint.")
    if cfg.tests.cache_ttl_seconds > 0:
        print(f"note: the cache suite sleeps {cfg.tests.cache_ttl_seconds}s per endpoint for the TTL pass.")
    return 0


def cmd_run(args) -> int:
    cfg = _load(args)
    suites = list(SUITES) if args.only in (None, "all") else [args.only]
    for s in suites:
        if s not in SUITES:
            print(f"unknown suite: {s} (choose from {', '.join(SUITES)})", file=sys.stderr)
            return 2

    seed = args.seed
    out_dir = Path(args.out) if args.out else ROOT / "results" / utcnow().replace(":", "").replace("-", "")

    print(f"relay-audit {__version__}")
    print(f"suites: {', '.join(suites)} | seed: {seed}")
    if cfg.demo:
        print("DEMO MODE: synthetic transport, no money spent, no real endpoint contacted.")
    print()

    findings: dict[str, dict] = {s: {} for s in suites}
    results_by_suite: dict[str, list] = {s: [] for s in suites}
    request_log: list[dict] = []
    total_failures = 0

    for suite_name in suites:
        runner = SUITES[suite_name]
        for ep in cfg.endpoints:
            print(f"[{suite_name}] {ep.label} ({ep.id})")
            results, ep_findings = runner(cfg, ep, seed, progress=lambda m: print(m))
            findings[suite_name][ep.id] = ep_findings
            results_by_suite[suite_name].extend(results)
            for r in results:
                request_log.append(r.to_dict())
            bad = sum(1 for r in results if not r.ok)
            total_failures += bad
            summary = ""
            if suite_name == "cache":
                summary = f" verdict={ep_findings.get('verdict')}"
            elif suite_name == "speed":
                summary = f" failures={bad}/{len(results)}"
            print(f"  done: {len(results)} requests, {bad} failed{summary}")
            print()

    # Usage rows feed cost accounting from actual reported usage.
    for suite_name, results in results_by_suite.items():
        if suite_name not in ("speed", "cache"):
            continue
        for ep in cfg.endpoints:
            rows = [
                {
                    "label": r.label,
                    "input_tokens": r.usage.input_tokens or 0,
                    "output_tokens": r.usage.output_tokens or 0,
                    "cache_read_tokens": r.usage.cache_read_tokens or 0,
                }
                for r in results
                if r.endpoint_id == ep.id and r.ok
            ]
            findings[suite_name].setdefault(ep.id, {})["_usage_rows"] = rows

    env = build_env(cfg, suites, seed)
    costs = cost_accounting(cfg, findings)
    report_md = build_report(cfg, env, findings, results_by_suite, costs)
    paths = write_outputs(out_dir, env, findings, results_by_suite, costs, report_md, request_log)

    print("wrote:")
    for name, path in paths.items():
        print(f"  {name:9s} {path}")
    print()
    print(f"total failed requests: {total_failures}")
    print(f"estimated spend this run: ${sum(c['estimated_cost_usd'] for c in costs.values() if c.get('available')):.5f}")
    return 0


def cmd_catalog(args) -> int:
    # keys_optional: the catalog reads publicly published prices, and many
    # relays expose their price list without authentication.
    cfg = load_config(
        Path(args.config),
        Path(args.rates),
        Path(args.env_file),
        demo=False,
        only_ids=args.endpoint,
        include_disabled=args.include_disabled,
        keys_optional=True,
    )
    specs = load_models(Path(getattr(args, "models", DEFAULT_MODELS)))

    print(f"relay-audit {__version__} · catalog")
    print(f"collecting from {len(cfg.endpoints)} endpoint(s) plus the public reference")
    print()

    data = build_catalog(cfg, specs, cfg.manual_rates, args.fx)

    for entry in data["probe_log"]:
        print(f"  {entry}")
    print()

    providers = []
    from .catalog import ProviderResult, ModelPrice  # local import for typing clarity

    for p in data["providers"]:
        res = ProviderResult(
            provider_id=p["provider_id"],
            label=p["label"],
            role=p["role"],
            base_url=p["base_url"],
            collected_at=p["collected_at"],
            status=p["status"],
            error=p["error"],
            probe_log=p["probe_log"],
            raw_sample=p.get("raw_sample"),
        )
        res.unmatched = p["unmatched"]
        for m in p["models"]:
            res.models.append(
                ModelPrice(
                    model_id=m["model_id"],
                    canonical=m["canonical"],
                    variant=m["variant"],
                    display=m["display"],
                    input_usd=m["input_usd_per_mtok"],
                    output_usd=m["output_usd_per_mtok"],
                    cache_read_usd=m["cache_read_usd_per_mtok"],
                    cache_write_usd=m["cache_write_usd_per_mtok"],
                    currency_native=m["native_currency"],
                    native_input=m["native_input"],
                    native_output=m["native_output"],
                    source=m["source"],
                    note=m["note"],
                    route_count=m.get("route_count", 1),
                    input_spread=tuple(m["input_spread"]) if m.get("input_spread") else None,
                    output_spread=tuple(m["output_spread"]) if m.get("output_spread") else None,
                )
            )
        providers.append(res)
        state = p["status"] if p["status"] == "ok" else p["status"].upper()
        print(f"  {p['label']:28s} {state:12s} matched={len(p['models']):3d} unmatched={len(p['unmatched']):3d}")

    print()
    if args.probe:
        for p in providers:
            if p.raw_sample:
                print(f"--- raw sample: {p.label} ({p.base_url}) ---")
                print(p.raw_sample[:1200])
                print()

    title = args.title
    md = render_markdown(providers, specs, data["fx"]["note"], data["generated_at"], title)

    out_dir = Path(args.out) if args.out else ROOT / "results" / "catalog"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "catalog.md").write_text(md, encoding="utf-8")
    (out_dir / "catalog.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    unavailable = [p.label for p in providers if p.status != "ok"]
    print("wrote:")
    print(f"  markdown  {out_dir / 'catalog.md'}")
    print(f"  json      {out_dir / 'catalog.json'}")
    print()
    if unavailable:
        print("could not collect prices for:")
        for label in unavailable:
            print(f"  - {label}")
        print()
        print(
            "This is expected for relays that only show prices inside a logged-in\n"
            "dashboard. Run with --probe to see the raw payload, then declare the\n"
            "rates by hand in config.toml as [[rates]] blocks. Do not guess: a table\n"
            "with invented numbers is worthless."
        )
    else:
        print("all providers returned collectable price data.")
    return 0


def _load(args):
    return load_config(
        Path(args.config),
        Path(args.rates),
        Path(args.env_file),
        demo=args.demo,
        only_ids=args.endpoint,
        include_disabled=args.include_disabled,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="relay-audit",
        description="Reproducible audit of LLM API relays: cache honesty, billing honesty, latency, cost.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--config", default=str(DEFAULT_CONFIG), help="path to config.toml")
        p.add_argument("--rates", default=str(DEFAULT_RATES), help="path to rates.toml")
        p.add_argument("--env-file", default=str(DEFAULT_ENV), help="path to .env")
        p.add_argument("--demo", action="store_true", help="synthetic transport; validates the harness, spends nothing")
        p.add_argument("--endpoint", action="append", help="only these endpoint ids or roles (repeatable)")
        p.add_argument("--include-disabled", action="store_true", help="also run endpoints marked enabled=false")

    p_plan = sub.add_parser("plan", help="validate config and print the request plan and estimated spend")
    common(p_plan)
    p_plan.set_defaults(func=cmd_plan)

    p_run = sub.add_parser("run", help="run the audit")
    common(p_run)
    p_run.add_argument("--only", default="all", help="all | speed | cache | billing")
    p_run.add_argument("--out", default=None, help="output directory")
    p_run.add_argument("--seed", type=int, default=20260915, help="seed for deterministic prompt generation")
    p_run.set_defaults(func=cmd_run)

    p_cat = sub.add_parser(
        "catalog",
        help="collect published prices from each provider and render a comparison table",
    )
    common(p_cat)
    p_cat.add_argument("--models", default=str(DEFAULT_MODELS), help="path to models.toml")
    p_cat.add_argument("--out", default=None, help="output directory")
    p_cat.add_argument("--fx", type=float, default=None, help="USD->CNY rate; overrides the live lookup")
    p_cat.add_argument("--title", default="Claude 中转站价格对比表", help="table title")
    p_cat.add_argument(
        "--probe",
        action="store_true",
        help="print a raw sample of each /models payload, for writing manual [[rates]] blocks",
    )
    p_cat.set_defaults(func=cmd_catalog)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
