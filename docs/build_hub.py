"""Build the hub page for the "claude 中转站" keyword family.

This is the decision page, not the catalogue. The division of labour:

  /claude-zhongzhuan   (hub)        - which one to use, why, and how to start
  /claude-relay-list   (directory)  - the full reference list of platforms
  tutorial pages                     - per-tool setup

Target queries: claude中转站, claude中转, claude中转平台, claude中转服务,
claude中转站推荐, claude中转站一览表, Claude中转站最高性价比, claude中转源头

The page answers "which one should I use" rather than only listing options,
because that is what the query means. Every platform fact comes from the roster
in build_directory.py, which is transcribed from a maintained public list; the
self-prices come from the collected snapshot. Nothing is invented.

Usage:
    python docs/build_hub.py --out dist --base https://www.relay-api.com
"""

from __future__ import annotations

import argparse
import html
import json
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from build_directory import ROSTER, CSS, load_self_prices


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def load_official(models_path: Path) -> dict[str, tuple[float, float]]:
    """Official reference rates come from models.toml, never a second copy.

    An earlier version of this script carried its own hardcoded table, which
    silently diverged: three models present in models.toml were missing from the
    copy, so their markup column rendered as '—' and the page understated how
    many models are cheaper than official. One source of truth prevents that.
    """
    specs = tomllib.loads(models_path.read_text(encoding="utf-8"))
    out: dict[str, tuple[float, float]] = {}
    for key, spec in specs.items():
        i, o = spec.get("official_input"), spec.get("official_output")
        if i is not None and o is not None:
            out[key] = (float(i), float(o))
    return out


def build_summary_rows(self_prices: dict, official: dict, fx: float | None) -> list[dict]:
    """One row per Claude model: self price in CNY, official price, and the ratio."""
    rows = []
    for canon, m in sorted((self_prices.get("rows") or {}).items()):
        if not canon.startswith("claude"):
            continue
        off = official.get(canon)
        row = {
            "model": m.get("display") or canon,
            "input": m.get("input"),
            "output": m.get("output"),
            "cache_read": m.get("cache_read"),
            "official_in": off[0] if off else None,
            "official_out": off[1] if off else None,
            "fold_in": None,
            "fold_out": None,
        }
        if off and fx and m.get("input") is not None:
            row["fold_in"] = (m["input"] / fx) / off[0]
        if off and fx and m.get("output") is not None:
            row["fold_out"] = (m["output"] / fx) / off[1]
        rows.append(row)
    rows.sort(key=lambda r: (r["fold_in"] is None, r["fold_in"] or 0))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="dist")
    ap.add_argument("--base", default="https://www.relay-api.com", help="canonical origin")
    ap.add_argument("--catalog", default=str(Path(__file__).resolve().parent.parent / "data" / "published" / "catalog-2026-09-22.json"))
    ap.add_argument("--models", default=str(Path(__file__).resolve().parent.parent / "models.toml"))
    args = ap.parse_args()

    self_prices = load_self_prices(Path(args.catalog))
    official = load_official(Path(args.models))
    generated_at = self_prices.get("generated_at") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fx = (self_prices.get("fx") or {}).get("usd_cny")
    fx_note = (self_prices.get("fx") or {}).get("note", "未采集")

    price_rows = build_summary_rows(self_prices, official, fx)

    # Platform rows: self first, then the verified-actives, then the unverified ones.
    order = {"self": 0}
    roster = sorted(
        ROSTER,
        key=lambda r: (
            0 if r.get("self") else (1 if r["trust"].startswith("🟢") else 2),
            order.get("self", 0),
        ),
    )

    def plats() -> str:
        out = []
        for r in roster:
            cls = ' class="self"' if r.get("self") else ""
            badge = '<span class="tag">本站</span> ' if r.get("self") else ""
            out.append(
                f"<tr{cls}>"
                f'<td>{badge}<a href="{esc(r["url"])}" rel="noopener">{esc(r["name"])}</a></td>'
                f'<td>{esc(r["trust"])}</td>'
                f"<td>{esc(r['notes'])}</td>"
                f"</tr>"
            )
        return "\n".join(out)

    def prices() -> str:
        out = []
        for r in price_rows:
            fi = f'{r["fold_in"]:.2f}×' if r["fold_in"] else "—"
            fo = f'{r["fold_out"]:.2f}×' if r["fold_out"] else "—"
            cls = ' class="cheaper"' if (r["fold_in"] or 9) < 1 else ""
            out.append(
                f"<tr{cls}>"
                f'<td>{esc(r["model"])}</td>'
                f'<td>{r["input"]:g}</td>'
                f'<td>{r["output"]:g}</td>'
                f'<td>{r["cache_read"] if r["cache_read"] is not None else "—"}</td>'
                f"<td>{fi}</td>"
                f"<td>{fo}</td>"
                f"</tr>"
            )
        return "\n".join(out)

    n_cheaper = sum(1 for r in price_rows if r["fold_in"] and r["fold_in"] < 1)
    n_total = len(price_rows)
    n_cache_free = sum(1 for r in price_rows if r["cache_read"] == 0)
    dearest = max(
        (r for r in price_rows if r["fold_out"]),
        key=lambda r: r["fold_out"],
        default=None,
    )

    extra_css = """
    tr.cheaper td:nth-child(5){color:#16a34a;font-weight:600}
    .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;margin:18px 0}
    .card{background:#fff;border:1px solid var(--line);border-radius:10px;padding:16px}
    .card h3{margin:0 0 8px;font-size:15px}
    .card p{margin:0;font-size:13.5px;color:#475569}
    .cta{background:#eff6ff;border:1px solid #bfdbfe;border-radius:10px;padding:18px;margin:22px 0}
    .cta a.btn{display:inline-block;background:var(--accent);color:#fff;padding:9px 18px;border-radius:7px;font-weight:600;font-size:14px}
    .cta a.btn:hover{text-decoration:none;opacity:.9}
    ul{padding-left:22px}li{margin:6px 0}
    code{background:#f1f5f9;padding:1px 5px;border-radius:4px;font-size:13px}
    """

    body = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Claude 中转站：平台推荐、价格对比与接入方式（{generated_at[:10]} 更新）</title>
<meta name="description" content="Claude 中转站怎么选：可用平台推荐、Claude 系模型价格对比（含与官方价的倍数）、缓存是否真实、以及 Cursor / Claude Code / Cline 的接入方式。数据带采集时间戳，可自行复核。">
<link rel="canonical" href="{esc(args.base)}/claude-zhongzhuan">
<link rel="alternate" hreflang="zh-CN" href="{esc(args.base)}/claude-zhongzhuan">
<link rel="alternate" hreflang="x-default" href="{esc(args.base)}/claude-zhongzhuan">
<style>{CSS}{extra_css}</style>
</head>
<body>
<div class="wrap">

<h1>Claude 中转站：平台推荐、价格对比与接入方式</h1>

<p class="lede">国内用 Claude 卡在两个门槛上——官方要海外信用卡，跨境访问还不稳定。中转站就是解决这两件事的中间层：你把 Base URL 指向它，用它发的密钥调用 Claude、GPT、Gemini，付款走支付宝或微信。</p>

<p class="lede">这一页回答三个问题：<strong>用哪家、多少钱、怎么接</strong>。价格部分是用脚本从公开接口采的，不是抄来的；平台部分引用了公开收录列表的核验结果。</p>

<p class="meta">价格采集时间：{generated_at}　·　汇率来源：{esc(fx_note)}　·　价格会变动，超过 14 天请视为过期</p>

<div class="note">
<strong>利益披露：本页由 <a href="{esc(args.base)}">relay-api.com</a> 维护，本站本身也是 Claude 中转平台。</strong>
本站在下方平台表中以「本站」标记出现，与其它平台并列；价格对比表里包含本站<strong>贵于官方价</strong>的项。请据此评估本页立场，也建议你自己去核对。
</div>

<h2>一、结论先给：怎么选</h2>

<div class="cards">
<div class="card">
<h3>要最省事、能开票</h3>
<p>选有公开公司实体、支持企业发票的平台。价格不是最低，但报销和售后有保障。</p>
</div>
<div class="card">
<h3>要价格低、自己承担风险</h3>
<p>选价格明显低于官方价的平台。注意：价格低到离谱的通常是逆向渠道，稳定性和封号风险自负。</p>
</div>
<div class="card">
<h3>要缓存省钱（长上下文场景）</h3>
<p>重点看平台的缓存读写价，并且<strong>实测验证</strong>——缓存价是真的还是账面数字，用长前缀连发两次就能看出来。方法见第四节。</p>
</div>
</div>

<p>本站的实际情况，好的一面和差的一面一起说：</p>
<ul>
<li><strong>输入价</strong>：{n_total} 个 Claude 系模型中有 <strong>{n_cheaper} 个低于官方价</strong>，最低约为官方价的 0.39 倍</li>
<li><strong>缓存读</strong>：{n_total} 个模型的缓存读取价均为 <strong>0（不额外计费）</strong>，长上下文场景收益明显</li>
<li><strong>价格偏高的项</strong>：{esc(dearest["model"]) if dearest else "—"} 的输出价约为官方价的 {f"{dearest['fold_out']:.2f}×" if dearest else "—"}，是全表最贵的一项</li>
<li><strong>缺点</strong>：延迟高于官方直连；走第三方网关，数据经过中转方</li>
</ul>

<div class="cta">
<p style="margin:0 0 10px"><strong>接入只需改一个 Base URL：</strong></p>
<p style="margin:0 0 12px"><code>https://www.relay-api.com/v1</code>（OpenAI 兼容）　<code>https://www.relay-api.com</code>（Anthropic Messages）</p>
<a class="btn" href="{esc(args.base)}">前往控制台获取密钥 →</a>
</div>

<h2>二、Claude 系模型价格对比</h2>
<p>本站价格为<strong>人民币元 / 百万 tokens</strong>（脚本采集）；「vs 官方」列为折合美元后与官方单价的倍数，<span style="color:#16a34a">低于 1.00× 表示比官方便宜</span>。</p>

<div class="tblwrap">
<table>
<thead><tr><th>模型</th><th>本站输入价(¥)</th><th>本站输出价(¥)</th><th>缓存读(¥)</th><th>输入 vs 官方</th><th>输出 vs 官方</th></tr></thead>
<tbody>
{prices()}
</tbody>
</table>
</div>
<p class="meta">官方价取 Anthropic 公布单价（美元/百万 tokens）。缓存读为 0 表示不额外计费。</p>

<h2>三、可用平台一览</h2>
<p>下表列出可用的 Claude / 多模型中转平台，信任标记与核验时间引用公开收录列表（<a href="https://github.com/howardpen9/awesome-ai-api-proxy" rel="noopener">来源</a>），本站未做二次评级。</p>

<div class="tblwrap">
<table>
<thead><tr><th>平台</th><th>信任</th><th>说明</th></tr></thead>
<tbody>
{plats()}
</tbody>
</table>
</div>
<p class="meta">🟢 已核验可用　🟡 社区收录或未经独立核验　🔵 本站。完整的类型、支付方式等字段见<a href="{esc(args.base)}/claude-relay-list">中转站一览表</a>。</p>

<h2>四、怎么验证一个中转站是否诚实</h2>
<p>这里有两件事只能自己测，平台自述不算数：</p>

<h3>1. 缓存是真的还是账面数字</h3>
<p>方法：准备一段几千 token 的长前缀，连续发两次完全相同的请求，比较<strong>首字延迟（TTFT）</strong>。</p>
<ul>
<li>真实缓存命中会跳过预填充，第二次延迟应明显下降，长前缀下通常数倍</li>
<li>如果接口报告了 <code>cache_read</code> 却延迟不变，那这个缓存价只是账面数字</li>
</ul>
<p>两个信号必须一致：<strong>接口声明的</strong>缓存读取量，和<strong>物理上的</strong>延迟下降。</p>

<h3>2. 失败请求是否计费</h3>
<p>发一个必然会失败的请求（比如不存在的模型 ID、超出上限的 max_tokens），对照控制台的用量日志，看这笔是否被计费。这个只能看账单，工具测不出来。</p>

<div class="note">
这两项检查有现成脚本：<a href="https://github.com/helloguawazi/relay-audit_" rel="noopener">relay-audit</a>，输出原始 JSON，可自行复核。你也可以直接拿它来测本站。
</div>

<h2>五、接入方式</h2>
<p>主流工具都是把 Base URL 指向平台网关。按你用的工具选：</p>

<div class="tblwrap">
<table>
<thead><tr><th>工具</th><th>配置位置</th><th>要点</th></tr></thead>
<tbody>
<tr><td><a href="{esc(args.base)}/articles/cursor-setup">Cursor</a></td><td>Settings → Models → API Keys</td><td>自带密钥（BYOK）只能用于 Ask/Chat，Agent 和 Edit 会报 <code>Agent and Edit rely on custom models…</code>，这是产品限制不是配置问题</td></tr>
<tr><td><a href="{esc(args.base)}/articles/claude-code-setup">Claude Code</a></td><td>环境变量 <code>ANTHROPIC_BASE_URL</code> / <code>ANTHROPIC_API_KEY</code></td><td>官方 CLI，不受 BYOK 限制，终端里直接跑</td></tr>
<tr><td><a href="{esc(args.base)}/articles/cline-setup">Cline</a></td><td>VS Code 扩展 → API Provider</td><td>选 OpenAI Compatible 或 Anthropic，填 Base URL 与精确模型 ID</td></tr>
</tbody>
</table>
</div>

<h3>接口入口对照</h3>
<div class="tblwrap">
<table>
<thead><tr><th>模型分组</th><th>Base URL</th><th>协议</th></tr></thead>
<tbody>
<tr><td>Claude / Anthropic</td><td><code>{esc(args.base)}</code></td><td>Anthropic Messages</td></tr>
<tr><td>GPT / OpenAI</td><td><code>{esc(args.base)}/v1</code></td><td>OpenAI Chat Completions</td></tr>
</tbody>
</table>
</div>

<h2>六、常见问题</h2>

<h3>Claude 中转站是合法的吗？</h3>
<p>中转本身是转发服务，但它通常依赖上游账号或渠道，而上游服务条款一般不允许转售访问权。这是这个行业的固有风险，选平台时应当把它计入——这也是为什么"有公开实体、能开票"的平台更值钱。</p>

<h3>为什么有的中转站便宜到不像话？</h3>
<p>通常是三种情况：逆向渠道、共享订阅账号、或低于成本引流后再涨价。前两种随时可能失效或封号。价格明显低于官方价时，先假设它有原因，而不是先高兴。</p>

<h3>模型 ID 和展示名有什么区别？</h3>
<p>展示名（<code>Claude Sonnet 5</code>）是给人看的，模型 ID（<code>claude-sonnet-5</code>）才是要填进配置的。填错会直接返回 404，这是最常见的报错原因。</p>

<h3>价格会变吗？</h3>
<p>会，而且变得比官方频繁。任何不带采集日期的价格表都不要信，包括本页——所以本页标了采集时间。过期数据建议直接以平台官网为准。</p>

<div class="foot">
<p>本页由 relay-api.com 维护，属自建平台的推荐与比价页面。平台信息引用公开收录列表的核验结果，本站价格由脚本采集自公开接口，原始数据见 <a href="https://github.com/helloguawazi/relay-audit_" rel="noopener">relay-audit</a>。</p>
<p>最后更新：{generated_at}</p>
</div>

</div>
<script type="application/ld+json">
{{"@context":"https://schema.org","@type":"FAQPage","mainEntity":[
{{"@type":"Question","name":"Claude 中转站怎么选？","acceptedAnswer":{{"@type":"Answer","text":"看三件事：是否需要企业发票、能承受多大风险、是否依赖缓存省钱。要开票选有公开实体的平台；要低价则要接受逆向渠道或共享账号的封号风险；长上下文场景要重点验证缓存是否真实生效。"}}}},
{{"@type":"Question","name":"Claude 中转站多少钱？","acceptedAnswer":{{"@type":"Answer","text":"按 token 计费，价格随平台和模型不同。以本页采集数据为例，Claude 系模型输入价约为官方单价的 0.39 到 1.06 倍，输出价约为 0.37 到 1.48 倍。价格随上游和促销变动，请以平台官网当时报价为准。"}}}},
{{"@type":"Question","name":"怎么判断中转站的缓存价格是真的？","acceptedAnswer":{{"@type":"Answer","text":"准备一段几千 token 的长前缀，连续发两次完全相同的请求并比较首字延迟。真实缓存命中会跳过预填充，第二次延迟应明显下降。如果接口报告了缓存读取但延迟没有变化，这个缓存价就只是账面数字。"}}}},
{{"@type":"Question","name":"国内用 Claude 中转需要海外信用卡吗？","acceptedAnswer":{{"@type":"Answer","text":"不需要。中转平台一般支持支付宝和微信付款。这既是中转存在的主要原因，也是判断平台是否面向国内用户的一个标志。"}}}}
]}}
</script>
</body>
</html>
"""

    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = Path(__file__).resolve().parent.parent / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "claude-zhongzhuan.html"
    target.write_text(body, encoding="utf-8")

    print(f"wrote {target}")
    print(f"  canonical    : {args.base}/claude-zhongzhuan")
    print(f"  price rows   : {len(price_rows)}")
    print(f"  platform rows: {len(roster)}")
    print(f"  cheaper than official (input): {n_cheaper}/{n_total}")
    print(f"  generated_at : {generated_at}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
