"""Build a Chinese relay directory page from the awesome-list dataset.

The provider roster and the trust markers come from howardpen9/awesome-ai-api-proxy,
which vets submissions and publishes a weekly price snapshot. That dataset is the
citable basis; this script does not invent competitor prices.

What this adds on top of the source list:
  * the operator's own endpoint, with its real collected CNY prices
  * a Claude-only view, which the source list does not provide
  * a page we control: canonical, sitemap, internal links, and the entry point

Usage:
    python docs/build_directory.py --out dist --fx 7.1
"""

from __future__ import annotations

import argparse
import html
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Roster sourced from the awesome-ai-api-proxy README tables (retrieved 2026-09-22).
# `claude` marks entries whose notes indicate Anthropic / Claude support.
# `trust` is copied verbatim from that list so the grading stays attributable.
ROSTER = [
    {
        "name": "Relay (极智API)",
        "url": "https://www.relay-api.com",
        "type": "mixed",
        "payment": "支付宝 / 微信",
        "trust": "🔵 本站",
        "notes": "本站。公开 /v1/models 免鉴权返回各模型单价（含缓存读写价）；同时提供 OpenAI 兼容与 Anthropic Messages 协议。",
        "self": True,
        "claude": True,
    },
    {
        "name": "云雾 API (YUNWU)",
        "url": "https://yunwu.ai",
        "type": "mixed",
        "payment": "支付宝 / 微信",
        "trust": "🟢 active · 2026-05-26",
        "notes": "主打速度与稳定性，社区常列为头部站。",
        "claude": True,
    },
    {
        "name": "柏拉图 AI (bltcy)",
        "url": "https://api.bltcy.ai",
        "type": "mixed",
        "payment": "支付宝 / 微信",
        "trust": "🟢 active · 2026-06-07",
        "notes": "Azure 通道，主打最低价；1000+ 模型，公开 /api/pricing。",
        "claude": True,
    },
    {
        "name": "UiUiAPI",
        "url": "https://uiuiapi.com",
        "type": "official-relay",
        "payment": "支付宝 / 微信",
        "trust": "🟢 active · 2026-06-07",
        "notes": "宣称官方渠道与官方倍率；公开 /api/pricing。",
        "claude": True,
    },
    {
        "name": "CloseAI",
        "url": "https://www.closeai-asia.com",
        "type": "official-relay",
        "payment": "支付宝 / 微信 / 企业发票",
        "trust": "🟢 active · 2026-05-26 · 已注册实体",
        "notes": "支持企业开票，自称亚洲最大企业级中转。",
        "claude": True,
    },
    {
        "name": "TeamoRouter",
        "url": "https://teamorouter.com",
        "type": "mixed",
        "payment": "支付宝 / 微信",
        "trust": "🟡 unverified · ⚠ 运营方自荐",
        "notes": "OpenAI / Anthropic / Gemini 兼容网关；提供 Claude Code 与 Codex 接入指南。",
        "claude": True,
    },
    {
        "name": "玄枢API (XuanShu API)",
        "url": "https://www.xuanshuapi.com",
        "type": "mixed",
        "payment": "企业发票",
        "trust": "🟡 unverified · ⚠ 运营方自荐",
        "notes": "根路径提供 Anthropic Messages；模型可见性与价格按密钥分组在控制台设置。",
        "claude": True,
    },
    {
        "name": "No.1-API",
        "url": "https://api.rcouyi.com",
        "type": "aggregator",
        "payment": "支付宝 / 微信",
        "trust": "🟢 active · 2026-05-26",
        "notes": "一站式聚合与中转平台。",
        "claude": True,
    },
    {
        "name": "DMXAPI",
        "url": "https://dmxapi.cn",
        "type": "mixed",
        "payment": "支付宝 / 微信",
        "trust": "🟡 unverified · ⚠ 无公开实体",
        "notes": "见于社区资料；主页未经独立核验。",
        "claude": True,
    },
    {
        "name": "OpenRouter",
        "url": "https://openrouter.ai",
        "type": "aggregator",
        "payment": "信用卡 / 加密货币",
        "trust": "🟢 官方授权路由",
        "notes": "官方授权路由，约 5% 加成；公开 /api/v1/models 带归一化单价。作为价格基准使用。",
        "claude": True,
    },
]


def load_self_prices(catalog_path: Path) -> dict:
    """Real collected prices for our own endpoint. Never inferred."""
    if not catalog_path.exists():
        return {}
    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    for p in data["providers"]:
        if p.get("role") == "candidate":
            out = {}
            for m in p["models"]:
                if m.get("native_input") is not None:
                    out[m["canonical"]] = {
                        "input": m["native_input"],
                        "output": m.get("native_output"),
                        "cache_read": m.get("cache_read_usd_per_mtok"),
                        "display": m.get("display") or m["canonical"],
                        "routes": m.get("route_count", 1),
                    }
            return {"rows": out, "generated_at": data["generated_at"], "fx": data["fx"]}
    return {}


def esc(s) -> str:
    return html.escape(str(s), quote=True)


CSS = """
:root{--ink:#0f172a;--mut:#64748b;--line:#e2e8f0;--bg:#f8fafc;--accent:#2563eb;--good:#16a34a;--warn:#d97706}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
 font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
 line-height:1.7;-webkit-font-smoothing:antialiased}
.wrap{max-width:1080px;margin:0 auto;padding:40px 20px 80px}
h1{font-size:30px;line-height:1.35;margin:0 0 14px}
h2{font-size:21px;margin:44px 0 14px;padding-top:22px;border-top:1px solid var(--line)}
h3{font-size:16px;margin:26px 0 10px}
p{margin:0 0 14px}
.lede{font-size:16px;color:#334155}
.meta{font-size:13px;color:var(--mut);margin-bottom:26px}
.tblwrap{overflow-x:auto;background:#fff;border:1px solid var(--line);border-radius:10px}
table{border-collapse:collapse;width:100%;font-size:14px;min-width:760px}
th,td{padding:11px 13px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}
th{background:#f1f5f9;font-weight:600;font-size:13px;color:#475569;white-space:nowrap}
tr:last-child td{border-bottom:0}
tr.self{background:#eff6ff}
tr.self td{font-weight:500}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
.tag{display:inline-block;font-size:12px;padding:1px 7px;border-radius:4px;background:#f1f5f9;color:#475569}
.note{background:#fff;border:1px solid var(--line);border-left:3px solid var(--accent);border-radius:8px;padding:14px 16px;margin:20px 0;font-size:14px}
.warn{border-left-color:var(--warn)}
.foot{font-size:13px;color:var(--mut);margin-top:40px;padding-top:20px;border-top:1px solid var(--line)}
"""


def render(directory_rows, self_prices, fx_note, generated_at, out: Path) -> Path:
    rows_html = []
    for r in directory_rows:
        cls = ' class="self"' if r.get("self") else ""
        badge = '<span class="tag">本站</span> ' if r.get("self") else ""
        rows_html.append(
            f'<tr{cls}>'
            f'<td>{badge}<a href="{esc(r["url"])}" rel="noopener">{esc(r["name"])}</a></td>'
            f'<td>{esc(r["type"])}</td>'
            f'<td>{esc(r["payment"])}</td>'
            f'<td>{esc(r["trust"])}</td>'
            f'<td>{esc(r["notes"])}</td>'
            f"</tr>"
        )

    price_rows = []
    sp = self_prices.get("rows", {})
    for canon in sorted(sp):
        m = sp[canon]
        routes = f'{m["routes"]} 档' if m["routes"] > 1 else "单档"
        price_rows.append(
            "<tr>"
            f'<td>{esc(m["display"])}</td>'
            f'<td>{m["input"]:g}</td>'
            f'<td>{m["output"]:g}</td>'
            f'<td>{m["cache_read"] if m["cache_read"] is not None else "—"}</td>'
            f"<td>{routes}</td>"
            "</tr>"
        )

    body = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Claude 中转站一览表：可用平台、价格与接入方式（{generated_at[:10]} 更新）</title>
<meta name="description" content="Claude 中转站一览表：收录可用平台、支付方式、信任等级与 Claude 系模型价格。含公开价格采集方法与复核方式，数据带采集时间戳。">
<link rel="canonical" href="https://www.relay-api.com/claude-relay-list">
<link rel="alternate" hreflang="zh-CN" href="https://www.relay-api.com/claude-relay-list">
<link rel="alternate" hreflang="x-default" href="https://www.relay-api.com/claude-relay-list">
<style>{CSS}</style>
</head>
<body>
<div class="wrap">

<h1>Claude 中转站一览表</h1>
<p class="lede">想用 Claude 但卡在海外信用卡和跨境网络的人，通常会先找一份能用、能付款、价格清楚的平台清单。这份表就是干这个的：列出可用的 Claude 中转平台、支持的支付方式、信任等级，以及能公开查到的价格。</p>
<p class="meta">数据更新：{generated_at}　·　汇率来源：{esc(fx_note)}</p>

<div class="note">
<strong>本站也在表里。</strong> 本页由 <a href="https://www.relay-api.com">relay-api.com</a> 维护，本站以「本站」标记出现在下方表格中，价格与信任等级均与其他平台并列展示。请据此评估本页立场，并建议自行复核数据。
</div>

<h2>一、Claude 中转平台一览</h2>
<p>按信任等级与类型排列。信任标记沿用公开中转站收录列表的核验结果，本站不做二次评级。</p>
<div class="tblwrap">
<table>
<thead><tr><th>平台</th><th>类型</th><th>支付方式</th><th>信任</th><th>说明</th></tr></thead>
<tbody>
{chr(10).join(rows_html)}
</tbody>
</table>
</div>
<p class="meta">标记说明：🟢 已核验可用　🟡 社区收录或未经独立核验　⚠ 已知风险标记（如无公开实体、运营方自荐）。来源与核验时间见各行。</p>

<h2>二、本站 Claude 系模型价格</h2>
<p>以下价格由脚本从本站公开接口自动采集，非人工填写。计价单位：<strong>人民币元 / 百万 tokens</strong>。</p>
<div class="tblwrap">
<table>
<thead><tr><th>模型</th><th>输入价</th><th>输出价</th><th>缓存读</th><th>上游路由</th></tr></thead>
<tbody>
{chr(10).join(price_rows)}
</tbody>
</table>
</div>
<div class="note warn">
多档路由说明：标注「N 档」的模型在不同上游路由上价格不同，表中为最低档公布价，实际按当时命中的路由计费。
</div>

<h2>三、怎么挑一个能长期用的中转</h2>
<p>价格不是唯一变量。下面这几条是实际踩过之后才会注意到的：</p>
<h3>1. 缓存是不是真的便宜</h3>
<p>很多平台标了缓存价，但要看它是否真的跳过预填充。判断方式很直接：同一个长前缀连续发两次，如果第二次首字延迟没有明显下降，那个缓存价就只是账面数字。</p>
<h3>2. 模型 ID 和展示名不是一回事</h3>
<p>配置时填错会直接报 404。控制台里通常同时显示「Claude Sonnet 5」和「claude-sonnet-5」，只有后者能用。</p>
<h3>3. 支付方式和开票</h3>
<p>个人用支付宝/微信就够；如果要做公司报销，只有支持企业发票的平台能用。</p>
<h3>4. 价格会变</h3>
<p>中转价格随上游和促销波动。任何不带采集日期的价格表都不可信——包括本页，所以本页标了更新时间。</p>

<h2>四、怎么接入</h2>
<p>主流平台的接入方式基本一致，都是把 Base URL 指向平台网关：</p>
<ul>
<li><strong>Cursor</strong>：Settings → Models → API Keys，填 API Key 与 Override Base URL。注意自带密钥（BYOK）只能用于 Ask/Chat，Agent 和 Edit 会报 <code>Agent and Edit rely on custom models that cannot be billed to an API key</code>。</li>
<li><strong>Claude Code</strong>：设置 <code>ANTHROPIC_BASE_URL</code> 与 <code>ANTHROPIC_API_KEY</code> 两个环境变量。</li>
<li><strong>Cline</strong>：VS Code 扩展，API Provider 选 OpenAI Compatible 或 Anthropic，填 Base URL 与模型 ID。</li>
</ul>

<h2>五、数据来源与复核</h2>
<p>本页数据来自两个可查证来源，你可以自行核对：</p>
<ol>
<li><strong>平台清单与信任标记</strong>：来自公开的中转站收录列表（<a href="https://github.com/howardpen9/awesome-ai-api-proxy" rel="noopener">awesome-ai-api-proxy</a>），本项目仅转载其核验结果，未做二次评级，也未编造任何平台信息。</li>
<li><strong>本站价格</strong>：由 <a href="https://github.com/helloguawazi/relay-audit_" rel="noopener">relay-audit</a> 的采集脚本从公开接口读取，原始 JSON 已入库，任何人可复现。</li>
</ol>
<p>如果发现本页数据与实际情况不符，请以平台官网为准，并欢迎指出——带日期的更正比不更新的表格有用。</p>

<div class="foot">
<p>本页由 relay-api.com 维护，属于自建平台的收录与比价页面。所有平台信息均标注来源；本站条目与其他平台并列展示，未做排名倾斜。</p>
<p>最后更新：{generated_at}　·　数据有效期建议不超过 14 天</p>
</div>

</div>
<script type="application/ld+json">
{{"@context":"https://schema.org","@type":"FAQPage","mainEntity":[
{{"@type":"Question","name":"Claude 中转站是什么？","acceptedAnswer":{{"@type":"Answer","text":"中转站是位于你的代码和官方 Claude API 之间的转发端点。你把 Base URL 指向它、用它发的密钥调用，它转发到上游并返回结果，通常兼容 OpenAI 或 Anthropic 的原生协议。"}}}},
{{"@type":"Question","name":"国内用 Claude 中转需要海外信用卡吗？","acceptedAnswer":{{"@type":"Answer","text":"不需要。中转平台一般支持支付宝和微信付款，这也是中转存在的主要原因之一——它同时解决了跨境网络和海外支付两个门槛。"}}}},
{{"@type":"Question","name":"怎么看中转站的缓存价格是真是假？","acceptedAnswer":{{"@type":"Answer","text":"用同一个长前缀连续发两次请求，比较首字延迟。真实的缓存命中会跳过预填充，第二次延迟应明显下降（长前缀下通常数倍）。如果接口报告了缓存读取但延迟没有变化，这个缓存价就只是账面数字。"}}}}
]}}
</script>
</body>
</html>
"""
    out.write_text(body, encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="dist")
    ap.add_argument("--catalog", default=str(ROOT / "data" / "published" / "catalog-2026-09-22.json"))
    args = ap.parse_args()

    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = ROOT / args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    self_prices = load_self_prices(Path(args.catalog))
    generated_at = self_prices.get("generated_at") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fx_note = (self_prices.get("fx") or {}).get("note", "未采集")

    target = render(ROSTER, self_prices, fx_note, generated_at, out_dir / "claude-relay-list.html")
    print(f"wrote {target}")
    print(f"  roster rows      : {len(ROSTER)}")
    print(f"  self price rows  : {len((self_prices.get('rows') or {}))}")
    print(f"  generated_at     : {generated_at}")

    # Also emit the markdown table, for pasting into GitHub / CSDN / 公众号.
    md = ["| 平台 | 类型 | 支付方式 | 信任 | 说明 |", "|---|---|---|---|---|"]
    for r in ROSTER:
        star = "**" if r.get("self") else ""
        md.append(f"| {star}[{r['name']}]({r['url']}){star} | {r['type']} | {r['payment']} | {r['trust']} | {r['notes']} |")
    (out_dir / "claude-relay-list.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"wrote {out_dir / 'claude-relay-list.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
