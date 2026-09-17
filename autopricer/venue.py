"""Target Center seating geometry.

The map this module produces is a *schematic* bowl, not a surveyed seat map.
Sections are laid out evenly around two concentric rings in section-number
order, which makes adjacency correct (101 sits beside 102, which sits beside
103) without claiming to reproduce the arena's true footprint. That is enough
to answer the question the map exists to answer: where in the bowl is the
money moving.
"""

from __future__ import annotations

import math
from typing import Iterable

# Nominal full ranges for each bowl, so gaps in the data render as gaps rather
# than silently closing up and shifting every other section's position.
LOWER_BOWL = list(range(101, 139))
UPPER_BOWL = list(range(201, 241))
FLOOR = list(range(1, 15))

TIER_FLOOR = "floor"
TIER_LOWER = "lower"
TIER_UPPER = "upper"


def tier(section: str | None) -> str | None:
    """Classify a canonical section key into a bowl tier."""
    if not section or not section.isdigit():
        return None
    n = int(section)
    if n < 100:
        return TIER_FLOOR
    if n < 200:
        return TIER_LOWER
    if n < 300:
        return TIER_UPPER
    return None


def _ellipse_arc_table(rx: float, ry: float, steps: int = 4000) -> tuple[list, list]:
    """Cumulative arc length around an ellipse, for equal-spacing lookups."""
    thetas, cum = [], [0.0]
    for i in range(steps + 1):
        thetas.append(2 * math.pi * i / steps)
    for i in range(1, len(thetas)):
        t0, t1 = thetas[i - 1], thetas[i]
        dx = rx * (math.sin(t1) - math.sin(t0))
        dy = ry * (math.cos(t1) - math.cos(t0))
        cum.append(cum[-1] + math.hypot(dx, dy))
    return thetas, cum


def _ring(sections: Iterable[int], rx: float, ry: float, start_deg: float) -> dict:
    """Place sections at equal *arc length* around an ellipse.

    Equal steps in the angle parameter bunch tiles where an ellipse is flattest,
    which made neighbouring lower-bowl sections overlap. Spacing by arc length
    keeps the gap between tiles constant all the way round.
    """
    sections = list(sections)
    n = len(sections)
    if n == 0:
        return {}
    thetas, cum = _ellipse_arc_table(rx, ry)
    total = cum[-1]
    offset = math.radians(start_deg)

    out = {}
    j = 0
    for i, sec in enumerate(sections):
        want = total * i / n
        while j < len(cum) - 1 and cum[j + 1] < want:
            j += 1
        theta = thetas[j] + offset
        # Tangent direction, so the tile faces the court.
        tx, ty = rx * math.cos(thetas[j]), ry * math.sin(thetas[j])
        out[str(sec)] = {
            "x": round(50 + rx * math.sin(theta), 3),
            "y": round(50 - ry * math.cos(theta), 3),
            "angle": round(math.degrees(math.atan2(tx, ty) + offset) % 360, 2),
        }
    return out


def layout(floor_sections: Iterable[str] | None = None) -> dict:
    """Return ``{section_key: {x, y, angle, tier}}`` on a 0-100 square canvas.

    Section 101 is anchored at the bottom of the bowl and numbering runs
    clockwise, matching how Target Center's 100 and 200 levels are numbered.

    The two bowls are drawn over their full nominal ranges so a section missing
    from the data reads as a gap instead of shifting every other tile. The floor
    is different: its real numbering is not known from the extract, so only the
    floor sections actually observed are drawn rather than inventing a ring of
    fourteen.
    """
    out: dict[str, dict] = {}
    # The lower bowl packs 38 sections, so it needs enough arc per section for
    # a three-digit label to sit inside its tile without touching a neighbour.
    for sec, pos in _ring(LOWER_BOWL, 33.0, 28.0, 180.0).items():
        out[sec] = {**pos, "tier": TIER_LOWER}
    for sec, pos in _ring(UPPER_BOWL, 45.0, 40.0, 180.0).items():
        out[sec] = {**pos, "tier": TIER_UPPER}

    floor = sorted(
        (s for s in (floor_sections or []) if tier(s) == TIER_FLOOR),
        key=lambda s: int(s),
    )
    for sec, pos in _ring(floor, 15.0, 12.0, 180.0).items():
        out[sec] = {**pos, "tier": TIER_FLOOR}
    return out


def court() -> dict:
    """Bounding box of the court, for drawing."""
    return {"x": 38.0, "y": 41.0, "w": 24.0, "h": 18.0}
