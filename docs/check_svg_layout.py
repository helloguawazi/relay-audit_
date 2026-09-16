"""Layout self-check for the hand-written SVG diagrams.

I cannot visually inspect a rendered image in this environment, so the diagrams
are checked geometrically instead: every <text> element is measured against the
container it sits in, and anything that would overflow or collide is reported.

The width estimate is deliberately crude (a per-character advance table). It does
not need to match a browser exactly; it needs to catch a label that would run off
the edge of its box, which a 10% error margin still catches.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Average advance width in pixels at font-size 100, for a UI sans-serif.
WIDE = set("mwMW@%&")
NARROW = set("iljI.,:;'|!()[]")
CJK = re.compile(r"[\u3000-\u9fff\uff00-\uffef]")


def text_width(text: str, size: float, bold: bool = False, mono: bool = False) -> float:
    total = 0.0
    for ch in text:
        if CJK.match(ch):
            total += 1.0  # a CJK glyph is full-width
        elif ch in NARROW:
            total += 0.30
        elif ch in WIDE:
            total += 0.88
        elif ch == " ":
            total += 0.28
        else:
            total += 0.53 if not mono else 0.60
    if bold:
        total *= 1.05
    return total * size


def parse_boxes(svg: str) -> list[tuple[float, float, float, float]]:
    """Rects that look like containers (have a rx or a stroke class), as x, y, w, h."""
    boxes = []
    for m in re.finditer(r'<rect\s([^>]*)/>', svg):
        attrs = m.group(1)
        g = lambda n: float(re.search(rf'{n}="([-\d.]+)"', attrs).group(1)) if re.search(rf'{n}="([-\d.]+)"', attrs) else None
        x, y, w, h = g("x"), g("y"), g("width"), g("height")
        if None in (x, y, w, h):
            continue
        if w >= 900 and h >= 400:
            continue  # the canvas background
        boxes.append((x, y, w, h))
    return boxes


def check(path: Path) -> list[str]:
    svg = path.read_text(encoding="utf-8")
    vb = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg)
    if not vb:
        return [f"{path.name}: no viewBox found"]
    vw, vh = float(vb.group(1)), float(vb.group(2))
    boxes = parse_boxes(svg)
    problems: list[str] = []

    for m in re.finditer(r'<text\s([^>]*)>(.*?)</text>', svg, re.S):
        attrs, raw = m.group(1), m.group(2)
        x = float(re.search(r'x="([-\d.]+)"', attrs).group(1))
        y = float(re.search(r'y="([-\d.]+)"', attrs).group(1))
        cls = (re.search(r'class="([^"]*)"', attrs) or [None, ""])[1]
        if "t-title" in cls:
            size, bold = 19.0, True
        elif "t-sec" in cls:
            size, bold = 12.0, True
        elif "t-b" in cls:
            size, bold = 14.0, True
        elif "mono" in cls:
            size, bold = 12.5, False
        else:
            size, bold = 12.0, False
        mono = "mono" in cls

        text = re.sub(r"<[^>]+>", "", raw)
        text = (
            text.replace("&gt;", ">").replace("&lt;", "<").replace("&amp;", "&")
            .replace("&nbsp;", " ").replace("&#x27;", "'").replace("&quot;", '"')
        )
        w = text_width(text, size, bold, mono)

        if x + w > vw:
            problems.append(f"{path.name}: '{text[:52]}' ends at {x + w:.0f}px, past the {vw:.0f}px canvas")
        if y > vh:
            problems.append(f"{path.name}: '{text[:52]}' sits at y={y:.0f}, below the {vh:.0f}px canvas")

        # Does the label start inside a container box? If so it must also end inside.
        for (bx, by, bw, bh) in boxes:
            starts_inside = bx <= x <= bx + bw and by <= y <= by + bh
            if not starts_inside:
                continue
            if x + w > bx + bw - 6:
                problems.append(
                    f"{path.name}: '{text[:48]}' starts in box x={bx:.0f} w={bw:.0f} "
                    f"but needs {w:.0f}px from x={x:.0f} (overflows by {x + w - (bx + bw):.0f}px)"
                )
            if y > by + bh:
                problems.append(f"{path.name}: '{text[:48]}' falls below its box bottom")
    return problems


def main() -> int:
    root = Path(__file__).resolve().parent
    files = sorted(root.glob("*.svg"))
    if not files:
        print("no SVG files found")
        return 1
    all_problems: list[str] = []
    for f in files:
        problems = check(f)
        status = "OK" if not problems else f"{len(problems)} problem(s)"
        print(f"{f.name:32s} {status}")
        all_problems.extend(problems)
    print()
    for p in all_problems:
        print("  !", p)
    return 1 if all_problems else 0


if __name__ == "__main__":
    sys.exit(main())
