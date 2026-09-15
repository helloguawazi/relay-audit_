"""Statistics helpers. Small on purpose: no numpy dependency."""

from __future__ import annotations

import math
from typing import Sequence


def percentile(values: Sequence[float], pct: float) -> float | None:
    """Linear-interpolated percentile. `pct` in [0, 100]."""
    clean = sorted(v for v in values if v is not None and not math.isnan(v))
    if not clean:
        return None
    if len(clean) == 1:
        return clean[0]
    rank = (pct / 100.0) * (len(clean) - 1)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return clean[int(rank)]
    frac = rank - low
    return clean[low] * (1 - frac) + clean[high] * frac


def mean(values: Sequence[float]) -> float | None:
    clean = [v for v in values if v is not None]
    if not clean:
        return None
    return sum(clean) / len(clean)


def summarise(values: Sequence[float | None]) -> dict:
    clean = [v for v in values if v is not None]
    return {
        "n": len(clean),
        "min": round(min(clean), 2) if clean else None,
        "p50": round(percentile(clean, 50), 2) if clean else None,
        "p90": round(percentile(clean, 90), 2) if clean else None,
        "p99": round(percentile(clean, 99), 2) if clean else None,
        "max": round(max(clean), 2) if clean else None,
        "mean": round(mean(clean), 2) if clean else None,
    }


def fmt(value: float | None, unit: str = "", digits: int = 1) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}{unit}"


def fmt_int(value: int | None) -> str:
    if value is None:
        return "—"
    return f"{value:,}"
