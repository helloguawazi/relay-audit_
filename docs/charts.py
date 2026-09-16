"""Render charts from catalog data as SVG — no plotting library.

Charts that are drawn by hand drift from the data they claim to show. Charts
generated from the collected JSON cannot: re-run the collector, re-run this
script, and the picture changes with the numbers. That property is the entire
reason this script exists instead of a matplotlib call.

Usage:
    python docs/charts.py results/catalog-cny/catalog.json docs
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

W = 900
ROW_H = 34
PAD_L = 210
PAD_R = 120
BAR_MAX = W - PAD_L - PAD_R

INK = "#0f172a"
MUTED = "#64748b"
GRID = "#e2e8f0"
BELOW = "#22c55e"   # cheaper than the baseline: good
ABOVE = "#ef4444"   # more expensive than the baseline: the row that must stay
NEUTRAL = "#94a3b8"

FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif"


def esc(s: str) -> str:
    return (
        str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def load(json_path: Path) -> tuple[dict, dict]:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    providers = data["providers"]

    candidate = None
    for p in providers:
        if p["role"] == "candidate":
            candidate = p
            break
    reference = None
    for p in providers:
        if p["role"] == "reference":
            reference = p
            break
    if candidate is None or reference is None:
        raise SystemExit("catalog.json needs both a candidate and a reference provider")

    ref_by = {m["canonical"]: m for m in reference["models"]}
    rows = []
    for m in candidate["models"]:
        r = ref_by.get(m["canonical"])
        if not r or not r.get("input_usd_per_mtok") or not m.get("input_usd_per_mtok"):
            continue
        rows.append(
            {
                "canonical": m["canonical"],
                "display": m.get("display") or m["canonical"],
                "site": m["input_usd_per_mtok"],
                "official": r["input_usd_per_mtok"],
                "fold": m["input_usd_per_mtok"] / r["input_usd_per_mtok"],
                "routes": m.get("route_count", 1),
            }
        )
    rows.sort(key=lambda x: x["fold"])
    return data, {"rows": rows, "candidate": candidate, "reference": reference}


def render_markup_chart(data: dict, ctx: dict) -> str:
    rows = ctx["rows"]
    if not rows:
        raise SystemExit("no comparable rows: candidate and reference share no priced model")

    title_h = 92
    # The footer prints one 18px row per model plus its header. Estimating this
    # is how the first version silently dropped 13 of 15 rows past the bottom
    # edge of the canvas, so it is computed from the actual row count.
    footer_row_h = 18
    footer_h = 40 + len(rows) * footer_row_h
    height = title_h + len(rows) * ROW_H + footer_h

    # The bar scale is symmetric around the 1.0x baseline so that "cheaper" and
    # "more expensive" occupy proportional screen space. A truncated axis would
    # exaggerate small differences, which is the classic way a price chart lies.
    max_dev = max(abs(r["fold"] - 1.0) for r in rows) or 0.5
    max_dev = max(max_dev, 0.15)
    half = BAR_MAX / 2
    cx = PAD_L + half

    def x_of(fold: float) -> float:
        return cx + ((fold - 1.0) / max_dev) * half

    out: list[str] = []
    out.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {height}" '
        f'width="{W}" height="{height}" font-family="{FONT}">'
    )
    out.append(f'<rect width="{W}" height="{height}" fill="#f8fafc"/>')
    out.append(
        f'<text x="34" y="40" font-size="19" font-weight="700" fill="{INK}">'
        f'Input price vs the official baseline</text>'
    )
    out.append(
        f'<text x="34" y="62" font-size="12" fill="{MUTED}">'
        f'{esc(ctx["candidate"]["label"])} compared with {esc(ctx["reference"]["label"])}, '
        f'USD per million input tokens. Collected {esc(data["generated_at"])}.</text>'
    )
    out.append(
        f'<text x="34" y="80" font-size="12" fill="{MUTED}">'
        f'Bars show the ratio. Left of centre is cheaper than the baseline, right is more expensive.</text>'
    )

    # 1.0x baseline
    out.append(f'<line x1="{cx:.1f}" y1="{title_h - 14}" x2="{cx:.1f}" y2="{title_h + len(rows) * ROW_H + 6}" stroke="{NEUTRAL}" stroke-width="1.5" stroke-dasharray="5 4"/>')
    out.append(f'<text x="{cx:.1f}" y="{title_h - 20}" font-size="11" fill="{MUTED}" text-anchor="middle">1.00× official</text>')

    y = title_h
    for r in rows:
        fold = r["fold"]
        bar_x = min(cx, x_of(fold))
        bar_w = abs(x_of(fold) - cx)
        color = BELOW if fold < 1.0 else ABOVE

        out.append(f'<text x="{PAD_L - 14}" y="{y + 16}" font-size="13" fill="{INK}" text-anchor="end">{esc(r["display"])}</text>')
        # Grid tick for the row, so the baseline is readable across the chart.
        out.append(f'<line x1="{PAD_L}" y1="{y + 22}" x2="{W - PAD_R + 60}" y2="{y + 22}" stroke="{GRID}" stroke-width="1"/>')
        out.append(
            f'<rect x="{bar_x:.1f}" y="{y + 6}" width="{max(bar_w, 1.5):.1f}" height="16" '
            f'fill="{color}" rx="2"/>'
        )
        label = f'{fold:.2f}×'
        side = 1 if fold >= 1.0 else -1
        lx = x_of(fold) + side * 8
        anchor = "start" if side > 0 else "end"
        out.append(
            f'<text x="{lx:.1f}" y="{y + 18}" font-size="12.5" font-weight="600" '
            f'fill="{color}" text-anchor="{anchor}">{label}</text>'
        )
        if r["routes"] > 1:
            rx = lx + (0 if side > 0 else 0)
            out.append(
                f'<text x="{rx:.1f}" y="{y + 30}" font-size="10.5" fill="{MUTED}" '
                f'text-anchor="{anchor}">{r["routes"]} upstream routes</text>'
            )
        y += ROW_H

    # Footer table: the absolute numbers, because a ratio alone hides the scale.
    fy = y + 18
    out.append(f'<line x1="34" y1="{fy - 12}" x2="{W - 34}" y2="{fy - 12}" stroke="{GRID}" stroke-width="1"/>')
    out.append(f'<text x="34" y="{fy + 4}" font-size="12" font-weight="700" fill="{MUTED}">MODEL</text>')
    out.append(f'<text x="360" y="{fy + 4}" font-size="12" font-weight="700" fill="{MUTED}">OFFICIAL</text>')
    out.append(f'<text x="500" y="{fy + 4}" font-size="12" font-weight="700" fill="{MUTED}">SITE</text>')
    out.append(f'<text x="640" y="{fy + 4}" font-size="12" font-weight="700" fill="{MUTED}">RATIO</text>')
    fy += 22
    for r in rows:
        color = BELOW if r["fold"] < 1.0 else ABOVE
        out.append(f'<text x="34" y="{fy}" font-size="12" fill="{INK}">{esc(r["display"])}</text>')
        out.append(f'<text x="360" y="{fy}" font-size="12" fill="{MUTED}">${r["official"]:.2f}</text>')
        out.append(f'<text x="500" y="{fy}" font-size="12" fill="{INK}">${r["site"]:.2f}</text>')
        out.append(f'<text x="640" y="{fy}" font-size="12" font-weight="600" fill="{color}">{r["fold"]:.2f}×</text>')
        fy += footer_row_h

    # Last row must still be inside the canvas. A chart that silently truncates
    # its own data is worse than one that fails loudly.
    assert fy - footer_row_h + 6 <= height, (
        f"footer overflows the canvas: last row baseline {fy - footer_row_h}, canvas {height}"
    )

    out.append("</svg>")
    return "\n".join(out)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    json_path = Path(sys.argv[1])
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("docs")
    out_dir.mkdir(parents=True, exist_ok=True)

    data, ctx = load(json_path)
    svg = render_markup_chart(data, ctx)
    target = out_dir / "price-vs-official.svg"
    target.write_text(svg, encoding="utf-8")

    print(f"wrote {target}")
    print(f"  {len(ctx['rows'])} comparable model(s)")
    for r in ctx["rows"]:
        print(f"    {r['display']:22s} {r['fold']:.2f}x  (site ${r['site']:.2f} vs official ${r['official']:.2f}, {r['routes']} route(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
