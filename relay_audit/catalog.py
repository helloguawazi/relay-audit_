"""Price catalogue: collect what each provider actually publishes, normalise, render.

Design rule: this module never invents a number.

A provider that does not publish its prices yields `None`, and the rendered
table shows an explicit "未采集到" rather than a plausible-looking guess. One
invented figure would invalidate the whole table, because the entire value of
the table is that every cell can be traced to a source.

Extraction order per provider:
  1. `/models` (and `/v1/models`) with a pricing-shaped payload field
  2. manual rates declared in the config (authoritative, used when a provider
     publishes prices only inside a logged-in dashboard)
  3. nothing -> recorded as unavailable
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from .config import Config, Endpoint
from .models import canonical_display, classify, normalise

# Field names seen in the wild for per-token or per-million prices.
INPUT_FIELDS = ("input", "input_price", "prompt", "prompt_price", "input_cost", "price_in")
OUTPUT_FIELDS = ("output", "output_price", "completion", "completion_price", "output_cost", "price_out")
CACHE_READ_FIELDS = ("cache_read", "cache_read_price", "input_cache_read", "cached_input_price")
CACHE_WRITE_FIELDS = ("cache_write", "cache_write_price", "input_cache_write")

OPENROUTER_MODELS = "https://openrouter.ai/api/v1/models"


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class ModelPrice:
    model_id: str
    canonical: str | None = None
    variant: str | None = None
    display: str | None = None
    input_usd: float | None = None
    output_usd: float | None = None
    cache_read_usd: float | None = None
    cache_write_usd: float | None = None
    currency_native: str | None = None
    native_input: float | None = None
    native_output: float | None = None
    source: str = "unavailable"
    note: str | None = None
    # Several relays expose multiple upstream routes per model at different
    # prices. Reporting only the top-level figure would silently pick whichever
    # route looks best, so the spread is recorded and disclosed.
    route_count: int = 1
    input_spread: tuple[float, float] | None = None
    output_spread: tuple[float, float] | None = None

    def to_dict(self) -> dict:
        return {
            "model_id": self.model_id,
            "canonical": self.canonical,
            "variant": self.variant,
            "display": self.display,
            "input_usd_per_mtok": self.input_usd,
            "output_usd_per_mtok": self.output_usd,
            "cache_read_usd_per_mtok": self.cache_read_usd,
            "cache_write_usd_per_mtok": self.cache_write_usd,
            "native_currency": self.currency_native,
            "native_input": self.native_input,
            "native_output": self.native_output,
            "source": self.source,
            "note": self.note,
            "route_count": self.route_count,
            "input_spread": list(self.input_spread) if self.input_spread else None,
            "output_spread": list(self.output_spread) if self.output_spread else None,
        }


@dataclass
class ProviderResult:
    provider_id: str
    label: str
    role: str
    base_url: str
    collected_at: str = field(default_factory=utcnow)
    models: list[ModelPrice] = field(default_factory=list)
    unmatched: list[str] = field(default_factory=list)
    status: str = "ok"
    error: str | None = None
    probe_log: list[str] = field(default_factory=list)
    raw_sample: str | None = None

    def by_canonical(self) -> dict[str, ModelPrice]:
        out: dict[str, ModelPrice] = {}
        for m in self.models:
            if m.canonical and m.canonical not in out:
                out[m.canonical] = m
        return out

    def to_dict(self) -> dict:
        return {
            "provider_id": self.provider_id,
            "label": self.label,
            "role": self.role,
            "base_url": self.base_url,
            "collected_at": self.collected_at,
            "status": self.status,
            "error": self.error,
            "probe_log": self.probe_log,
            "raw_sample": self.raw_sample,
            "model_count": len(self.models),
            "unmatched": self.unmatched,
            "models": [m.to_dict() for m in self.models],
        }


# --------------------------------------------------------------------------
# currency
# --------------------------------------------------------------------------

def fetch_usd_cny(cli: httpx.Client, configured: float | None, probe_log: list[str]) -> tuple[float | None, str]:
    """USD->CNY rate. A configured value wins; otherwise try a public feed."""
    if configured:
        probe_log.append(f"fx: using configured rate {configured}")
        return configured, f"configured ({configured})"
    for url, extract in (
        ("https://open.er-api.com/v6/latest/USD", lambda j: j.get("rates", {}).get("CNY")),
        ("https://api.frankfurter.app/latest?from=USD&to=CNY", lambda j: j.get("rates", {}).get("CNY")),
    ):
        try:
            r = cli.get(url, timeout=12.0)
            if r.status_code == 200:
                rate = extract(r.json())
                if rate:
                    probe_log.append(f"fx: {url} -> {rate}")
                    return float(rate), f"live ({url})"
        except Exception as exc:
            probe_log.append(f"fx: {url} failed ({exc.__class__.__name__})")
    probe_log.append("fx: no rate available; CNY prices cannot be converted")
    return None, "unavailable"


# --------------------------------------------------------------------------
# extraction
# --------------------------------------------------------------------------

def _num(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _pick(d: dict, names: tuple[str, ...]) -> float | None:
    for n in names:
        if n in d:
            v = _num(d[n])
            if v is not None:
                return v
    return None


def _price_scale(values: list[float]) -> float:
    """Infer whether prices are per-token or per-million-token.

    OpenRouter-style per-token prices are tiny (1e-5), while per-million prices
    are order 1-100. Mixing the two would produce a table wrong by 1e6, so the
    scale is inferred from the magnitude and recorded.
    """
    known = [v for v in values if v is not None and v > 0]
    if not known:
        return 1.0
    return 1_000_000.0 if max(known) < 1e-3 else 1.0


def parse_models_payload(
    payload: dict, currency: str, usd_cny: float | None
) -> tuple[list[ModelPrice], list[str]]:
    """Extract prices from a /models response. Returns (prices, unmatched_ids).

    `currency` comes from the endpoint's own config, never from guessing. The
    magnitude heuristic is used only to decide per-token vs per-million-token
    scaling within a declared currency.
    """
    items = payload.get("data")
    if not isinstance(items, list):
        items = payload.get("models") if isinstance(payload.get("models"), list) else []
    prices: list[ModelPrice] = []
    unmatched: list[str] = []

    for item in items:
        if not isinstance(item, dict):
            continue
        # `slug` is the machine id when present; `description` and `name` are
        # progressively looser fallbacks. `name` is last because relays use it
        # for marketing labels ('Claude Opus 5 限时特价').
        model_id = (
            item.get("slug")
            or item.get("id")
            or item.get("model")
            or item.get("description")
            or item.get("name")
        )
        if not model_id:
            continue
        model_id = str(model_id)
        display_name = item.get("name") or item.get("display_name")

        pricing = item.get("pricing") if isinstance(item.get("pricing"), dict) else item
        raw_in = _pick(pricing, INPUT_FIELDS)
        raw_out = _pick(pricing, OUTPUT_FIELDS)
        raw_cr = _pick(pricing, CACHE_READ_FIELDS)
        raw_cw = _pick(pricing, CACHE_WRITE_FIELDS)

        if raw_in is None and raw_out is None:
            unmatched.append(model_id)
            continue

        # Per-token vs per-million. Only meaningful for USD figures, which
        # arrive in either convention. Declared-CNY figures are per-million.
        scale = 1.0
        if currency == "USD":
            scale = _price_scale([v for v in (raw_in, raw_out) if v is not None])

        # Upstream routes may be priced differently. The top-level figure is
        # usually just the cheapest, so the spread is captured too.
        routes = item.get("routes") if isinstance(item.get("routes"), list) else []
        route_count = max(1, len(routes))
        in_vals = [_num(r.get("input_price")) for r in routes if isinstance(r, dict)]
        out_vals = [_num(r.get("output_price")) for r in routes if isinstance(r, dict)]
        in_vals = [v for v in in_vals if v is not None]
        out_vals = [v for v in out_vals if v is not None]
        input_spread = (min(in_vals), max(in_vals)) if in_vals else None
        output_spread = (min(out_vals), max(out_vals)) if out_vals else None

        note_parts: list[str] = []
        if item.get("is_promo") or item.get("discount_label"):
            note_parts.append(str(item.get("discount_label") or "促销中"))
        if display_name and str(display_name) != model_id:
            note_parts.append(f"显示名 {display_name}")
        if route_count > 1:
            note_parts.append(f"{route_count} 条上游路由")

        def to_usd(v: float | None) -> float | None:
            if v is None:
                return None
            v = v * scale
            if currency == "CNY":
                if usd_cny is None:
                    return None
                return v / usd_cny
            return v

        unavailable_reason = None
        if currency == "CNY" and usd_cny is None:
            unavailable_reason = "CNY 价格无法换算（缺少汇率）"

        prices.append(
            ModelPrice(
                model_id=model_id,
                input_usd=to_usd(raw_in),
                output_usd=to_usd(raw_out),
                cache_read_usd=to_usd(raw_cr),
                cache_write_usd=to_usd(raw_cw),
                currency_native=currency,
                native_input=raw_in,
                native_output=raw_out,
                source="models endpoint",
                note=unavailable_reason or ("；".join(note_parts) if note_parts else None),
                route_count=route_count,
                input_spread=input_spread,
                output_spread=output_spread,
            )
        )
    return prices, unmatched


# --------------------------------------------------------------------------
# provider probing
# --------------------------------------------------------------------------

def probe_endpoint(
    cli: httpx.Client,
    ep: Endpoint,
    manual_rates: dict | None,
    usd_cny: float | None,
    specs: dict,
) -> ProviderResult:
    res = ProviderResult(
        provider_id=ep.id, label=ep.label, role=ep.role, base_url=ep.base_url
    )

    if manual_rates:
        for canonical, rate in manual_rates.items():
            spec = specs.get(canonical, {})
            res.models.append(
                ModelPrice(
                    model_id=canonical,
                    canonical=canonical,
                    display=canonical_display(canonical, spec),
                    input_usd=_num(rate.get("input")),
                    output_usd=_num(rate.get("output")),
                    cache_read_usd=_num(rate.get("cache_read")),
                    cache_write_usd=_num(rate.get("cache_write")),
                    currency_native=rate.get("currency", "USD"),
                    native_input=_num(rate.get("input")),
                    native_output=_num(rate.get("output")),
                    source=f"manual config ({rate.get('retrieved', 'no date')})",
                    note=rate.get("note"),
                )
            )
        res.probe_log.append(f"manual: {len(res.models)} rate(s) declared in config")
        if res.models:
            _finalise(res, specs)
            return res

    # Try the models endpoints. Both /models and /v1/models are attempted
    # because relays differ on whether base_url already includes a version.
    candidates = []
    base = ep.base_url.rstrip("/")
    candidates.append(base + "/models")
    if "/v1" in base:
        candidates.append(base.replace("/v1", "") + "/v1/models")
    else:
        candidates.append(base + "/v1/models")
    seen: set[str] = set()
    ordered = [c for c in candidates if not (c in seen or seen.add(c))]

    headers = {}
    if ep.api_key:
        if ep.protocol == "anthropic":
            headers = {"x-api-key": ep.api_key, "anthropic-version": "2023-06-01"}
        elif ep.protocol == "azure":
            headers = {"api-key": ep.api_key, "anthropic-version": "2023-06-01"}
        else:
            headers = {"Authorization": f"Bearer {ep.api_key}"}

    collected: list[ModelPrice] = []
    unmatched: list[str] = []
    # A models endpoint that answers 200 with ids but no prices is the single
    # most common relay shape. Saying so explicitly saves the reader from
    # concluding the tool is broken.
    responded_without_prices = False
    last_status: int | None = None
    for url in ordered:
        try:
            r = cli.get(url, headers=headers, timeout=20.0)
        except Exception as exc:
            res.probe_log.append(f"GET {url} -> {exc.__class__.__name__}")
            continue
        last_status = r.status_code
        res.probe_log.append(f"GET {url} -> HTTP {r.status_code}")
        if r.status_code != 200:
            continue
        if res.raw_sample is None:
            # Generous: the sample exists to be pasted into a [[rates]] block, and
            # a truncated JSON body is worse than useless for that.
            res.raw_sample = r.text[:20000]
        try:
            payload = r.json()
        except (json.JSONDecodeError, ValueError):
            res.probe_log.append("  body was not JSON")
            continue
        prices, unmatched_ids = parse_models_payload(payload, ep.currency, usd_cny)
        if prices:
            collected = prices
            unmatched = unmatched_ids
            res.probe_log.append(
                f"  parsed {len(prices)} priced model(s), declared currency {ep.currency}"
            )
            break
        # The endpoint listed models but attached no prices to them.
        listed = len(unmatched_ids)
        if listed:
            responded_without_prices = True
            res.probe_log.append(f"  listed {listed} model(s) with no price fields present")

    if not collected:
        res.status = "unavailable"
        if responded_without_prices:
            res.error = (
                "该接口返回了模型列表，但**不含任何价格字段**。"
                "这是中转站的常见行为：价格只在其登录后的控制台里展示。"
                "请在 config.toml 中用 [[rates]] 手工登记价格。"
            )
        elif last_status is not None and last_status != 200:
            res.error = (
                f"模型列表接口返回 HTTP {last_status}。"
                f"若为 401/403，说明需要有效的 API key 才能读取价格；"
                f"若为 404，说明该平台的模型列表不在这个路径下。"
            )
        else:
            res.error = "无法访问任何模型列表路径。"
        return res

    res.models = collected
    res.unmatched = unmatched
    _finalise(res, specs)
    return res


def _finalise(res: ProviderResult, specs: dict) -> None:
    """Attach canonical ids, and separate unmatched entries from matched ones."""
    matched: list[ModelPrice] = []
    unmatched: list[str] = []
    for m in res.models:
        key = classify(m.model_id, specs)
        if key is None:
            if m.canonical and m.canonical in specs:
                key = m.canonical
            else:
                unmatched.append(m.model_id)
                continue
        m.canonical = key
        base, variant = normalise(m.model_id)
        m.variant = variant
        m.display = canonical_display(key, specs.get(key, {}))
        matched.append(m)
    res.models = matched
    res.unmatched = sorted(set(res.unmatched + unmatched))


def probe_official(cli: httpx.Client, specs: dict, probe_log: list[str]) -> ProviderResult:
    """OpenRouter publishes per-token prices publicly, so it serves as the reference."""
    res = ProviderResult(
        provider_id="official",
        label="OpenRouter (reference)",
        role="reference",
        base_url=OPENROUTER_MODELS,
    )
    try:
        r = cli.get(OPENROUTER_MODELS, timeout=25.0)
        res.probe_log.append(f"GET {OPENROUTER_MODELS} -> HTTP {r.status_code}")
        if r.status_code != 200:
            res.status = "unavailable"
            res.error = f"HTTP {r.status_code}"
            return res
        payload = r.json()
    except Exception as exc:
        res.status = "unavailable"
        res.error = f"{exc.__class__.__name__}: {exc}"
        return res

    prices, unmatched = parse_models_payload(payload, "USD", None)
    res.models = prices
    res.unmatched = unmatched
    _finalise(res, specs)
    probe_log.append(f"official: {len(res.models)} matched model(s)")
    return res


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def _fmt_price(v: float | None, currency: str = "USD") -> str:
    if v is None:
        return "未采集到"
    if v == 0:
        return "0（免费）"
    if v < 0.01:
        return f"{v:.4f}"
    if v < 1:
        return f"{v:.3f}"
    return f"{v:.2f}"


def _fold_ratio(value: float | None, official: float | None) -> str:
    if value is None or not official:
        return "—"
    return f"{value / official:.2f}×"


def render_markdown(
    providers: list[ProviderResult],
    specs: dict,
    fx_note: str,
    generated_at: str,
    title: str,
) -> str:
    """Render the comparison table. Chinese, because that is the target audience."""
    lines: list[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"> 采集时间：{generated_at}")
    lines.append(f"> 汇率来源：{fx_note}")
    lines.append("")
    lines.append(
        "> 本表所有价格均来自各平台**公开发布**的数据，采集方式与时间见下方说明。"
        "未采集到的项一律留空并标注，**不做任何推测填充**。"
    )
    lines.append("")

    for canonical, spec in specs.items():
        official_in = spec.get("official_input")
        official_out = spec.get("official_output")
        rows = []
        for p in providers:
            m = p.by_canonical().get(canonical)
            if m is None:
                continue
            rows.append((p, m))
        if not rows:
            continue

        display = spec.get("display") or canonical
        lines.append(f"## {display}")
        lines.append("")
        if official_in is None:
            lines.append(
                "> ⚠️ 该模型缺少已核实的官方基准价（`models.toml` 中 `source` 为空），"
                "因此无法计算溢价倍数。"
            )
            lines.append("")
        lines.append(
            "| 平台 | 输入价 (USD/百万) | 输出价 (USD/百万) | 缓存读 (USD/百万) | "
            "输入价 vs 官方 | 上游路由 | 数据来源 |"
        )
        lines.append("|---|---|---|---|---|---|---|")
        for p, m in rows:
            route_cell = "单档"
            if m.route_count > 1:
                route_cell = f"{m.route_count} 档"
                if m.input_spread and m.input_spread[0] != m.input_spread[1]:
                    route_cell = (
                        f"{m.route_count} 档<br>输入 {m.input_spread[0]:g}–{m.input_spread[1]:g} "
                        f"{m.currency_native or ''}"
                    )
            lines.append(
                f"| {p.label} | {_fmt_price(m.input_usd)} | {_fmt_price(m.output_usd)} | "
                f"{_fmt_price(m.cache_read_usd)} | {_fold_ratio(m.input_usd, official_in)} | "
                f"{route_cell} | {m.source} |"
            )
        lines.append("")
        multi = [(p, m) for p, m in rows if m.route_count > 1]
        if multi:
            lines.append(
                "多档路由说明：表中价格为该模型**最低档**路由的公布价。"
                "同一模型的不同上游路由价格不同，实际按当时命中的路由计费。"
            )
            lines.append("")
            for p, m in multi:
                detail = f"- {p.label}：{m.route_count} 档"
                if m.input_spread and m.input_spread[0] != m.input_spread[1]:
                    detail += (
                        f"，输入 {m.input_spread[0]:g}–{m.input_spread[1]:g} "
                        f"{m.currency_native or ''}/百万，"
                        f"输出 {m.output_spread[0]:g}–{m.output_spread[1]:g} "
                        f"{m.currency_native or ''}/百万"
                        if m.output_spread
                        else ""
                    )
                lines.append(detail)
            lines.append("")
        for p, m in rows:
            if m.note:
                lines.append(f"- {p.label} · {display}：{m.note}")
        lines.append("")
        if official_in is not None:
            source_text = spec.get("source") or "来源未标注"
            lines.append(
                f"官方基准价（{source_text}，"
                f"采集于 {spec.get('retrieved') or '未标注'}）："
                f"输入 {_fmt_price(official_in)} / 输出 {_fmt_price(official_out)} USD/百万 tokens。"
            )
            lines.append("")

    lines.append("## 采集说明与已知限制")
    lines.append("")
    for p in providers:
        status = p.status if p.status == "ok" else f"**{p.status}**"
        lines.append(f"### {p.label}（`{p.provider_id}`，{p.role}）")
        lines.append("")
        lines.append(f"- 状态：{status}")
        lines.append(f"- 基址：`{p.base_url}`")
        lines.append(f"- 采集时间：{p.collected_at}")
        lines.append(f"- 匹配到 {len(p.models)} 个已登记模型，未登记 {len(p.unmatched)} 个")
        if p.error:
            lines.append(f"- 说明：{p.error}")
        if p.probe_log:
            lines.append("- 探测记录：")
            for entry in p.probe_log:
                lines.append(f"  - `{entry}`")
        if p.unmatched:
            sample = ", ".join(f"`{u}`" for u in p.unmatched[:8])
            more = "" if len(p.unmatched) <= 8 else f" 等 {len(p.unmatched)} 个"
            lines.append(f"- 未登记模型（未纳入比价）：{sample}{more}")
        lines.append("")

    lines.append("## 如何复核本表")
    lines.append("")
    lines.append(
        "本表由 `relay-audit catalog` 生成。任何数字都可以通过以下方式独立复核："
    )
    lines.append("")
    lines.append("1. 直接请求该平台的模型列表接口，比对返回的原始 JSON")
    lines.append("2. 用 `relay-audit run` 对该平台做实测，比对声明价格与实际计费是否一致")
    lines.append("3. 对照平台官网的定价页面")
    lines.append("")
    lines.append(
        "**价格会变。** 表中每项都带采集时间，超过 14 天的价格请视为过期。"
    )
    lines.append("")
    lines.append(
        "**声明价不等于实际计费。** 本表记录的是平台自己公布的价格；"
        "缓存是否真实生效、失败请求是否计费等问题，需要用 `relay-audit run` 实测才能回答。"
    )
    lines.append("")
    return "\n".join(lines) + "\n"


def build_catalog(cfg: Config, specs: dict, manual: dict, fx_override: float | None) -> dict:
    """Collect from every endpoint plus the public reference. No values are invented."""
    probe_log: list[str] = []
    providers: list[ProviderResult] = []

    with httpx.Client(
        timeout=30.0, follow_redirects=True, headers={"User-Agent": "relay-audit/0.1"}
    ) as cli:
        usd_cny, fx_note = fetch_usd_cny(cli, fx_override, probe_log)
        official = probe_official(cli, specs, probe_log)
        for ep in cfg.endpoints:
            providers.append(probe_endpoint(cli, ep, manual.get(ep.id), usd_cny, specs))

        # If a configured endpoint already IS the public reference, showing both
        # would put the same prices on two rows and make the table look padded.
        # The configured one wins because it is the actual comparison target.
        configured_openrouter = any("openrouter.ai" in p.base_url for p in providers)
        if configured_openrouter:
            probe_log.append(
                "reference: skipped the built-in OpenRouter source because a configured "
                "endpoint already points at openrouter.ai"
            )
        else:
            providers.insert(0, official)

    generated_at = utcnow()
    return {
        "generated_at": generated_at,
        "fx": {"usd_cny": usd_cny, "note": fx_note},
        "probe_log": probe_log,
        "providers": [p.to_dict() for p in providers],
    }
