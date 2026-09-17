"""Small statistics helpers.

No numpy, and not ``statistics.quantiles`` either: it needs at least two data
points and cuts the distribution rather than interpolating a position within
it, so percentiles are implemented directly here -- comp sets are routinely
one or two listings deep and must still return an answer.
"""

from __future__ import annotations

from typing import Sequence


def pct(values: Sequence[float], p: float) -> float | None:
    """Linear-interpolated percentile of ``values``; ``p`` in ``[0, 1]``."""
    if not values:
        return None
    xs = sorted(values)
    if len(xs) == 1:
        return float(xs[0])
    p = min(max(p, 0.0), 1.0)
    pos = p * (len(xs) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    frac = pos - lo
    return float(xs[lo] * (1 - frac) + xs[hi] * frac)


def median(values: Sequence[float]) -> float | None:
    return pct(values, 0.5)


def clamp(x: float, lo: float | None, hi: float | None) -> float:
    if lo is not None and x < lo:
        x = lo
    if hi is not None and x > hi:
        x = hi
    return x


def describe(values: Sequence[float]) -> dict:
    """Five-number summary plus count and mean, all ``None`` when empty."""
    if not values:
        return {"n": 0, "min": None, "p25": None, "median": None,
                "p75": None, "max": None, "mean": None}
    xs = sorted(values)
    return {
        "n": len(xs),
        "min": round(xs[0], 2),
        "p25": round(pct(xs, 0.25), 2),          # type: ignore[arg-type]
        "median": round(pct(xs, 0.5), 2),        # type: ignore[arg-type]
        "p75": round(pct(xs, 0.75), 2),          # type: ignore[arg-type]
        "max": round(xs[-1], 2),
        "mean": round(sum(xs) / len(xs), 2),
    }
