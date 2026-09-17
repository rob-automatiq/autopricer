"""Target Center seating geometry, taken from the published seat map.

Sections are transcribed from Target Center's own seat map: a centre in that
image's pixel space, plus the arena edge the section sits on. Keeping the
source units means a position can be re-checked against the map instead of
being an opaque canvas number, and the edge tag fixes the tile's orientation
without having to be inferred.

Two things this gets right that a generated ring did not:

* **Where the sections are.** Both bowls are numbered clockwise from the east
  side, not from the bottom: 101 faces the court from the east, 111 and 112
  sit along the south edge, 131 along the north. An evenly spaced ellipse put
  them most of a quarter-turn away.
* **Which sections exist.** The lower bowl is not 101-138. Target Center has
  22 lower-bowl sections; the other sixteen numbers in that range are not
  seating at all, so drawing the full range invented sixteen sections that
  then rendered as "no data". The 22 here match the snapshot's section set
  exactly.

Club, suite, table and theatre-box inventory (the map's C*, S*, TB* and TI*
labels) is not drawn: none of it appears in the VividSeats feed, so there
would be nothing to shade.
"""

from __future__ import annotations

from typing import Iterable

TIER_FLOOR = "floor"
TIER_LOWER = "lower"
TIER_UPPER = "upper"

# --- projection from the seat map's pixel space onto the canvas -------------
#: Centre of the bowl's bounding box on the reference map.
_ORIGIN_X, _ORIGIN_Y = 728.0, 622.0
#: Pixels to canvas units, chosen so the bowl spans x 5..95.
_SCALE = 0.075
#: The canvas is wider than tall, like the arena; the bowl is centred in it.
CANVAS_W, CANVAS_H = 100.0, 74.0
_CANVAS_CY = 37.0

#: A tile lies flat along the edge it sits on. Angles are modulo 180, since a
#: rectangle rotated a half-turn is the same rectangle.
_EDGE_ANGLE = {"N": 0.0, "S": 0.0, "E": 90.0, "W": 90.0,
               "NE": 45.0, "SW": 45.0, "NW": 135.0, "SE": 135.0}

#: Upper bowl, 40 sections, clockwise from 201 on the east side.
#: ``(section, edge, x, y)``.
_UPPER: tuple[tuple[str, str, float, float], ...] = (
    ("201", "E", 1328, 617), ("202", "E", 1328, 703), ("203", "E", 1328, 785),
    ("204", "SE", 1295, 880), ("205", "SE", 1213, 950), ("206", "SE", 1147, 1028),
    ("207", "S", 1057, 1065), ("208", "S", 980, 1065), ("209", "S", 895, 1065),
    ("210", "S", 812, 1065), ("211", "S", 728, 1065), ("212", "S", 645, 1065),
    ("213", "S", 563, 1065), ("214", "S", 479, 1065), ("215", "S", 403, 1065),
    ("216", "SW", 313, 1028), ("217", "SW", 247, 950), ("218", "SW", 163, 885),
    ("219", "W", 128, 785), ("220", "W", 128, 703), ("221", "W", 128, 617),
    ("222", "W", 128, 532), ("223", "W", 128, 458),
    ("224", "NW", 163, 361), ("225", "NW", 247, 295), ("226", "NW", 318, 213),
    ("227", "N", 403, 180), ("228", "N", 479, 180), ("229", "N", 563, 180),
    ("230", "N", 645, 180), ("231", "N", 728, 180), ("232", "N", 812, 180),
    ("233", "N", 895, 180), ("234", "N", 980, 180), ("235", "N", 1057, 180),
    ("236", "NE", 1152, 213), ("237", "NE", 1213, 293), ("238", "NE", 1295, 358),
    ("239", "E", 1328, 458), ("240", "E", 1328, 532),
)

#: Lower bowl, 22 sections, clockwise from 101 on the east side. The gaps in
#: the numbering are real -- there is no 102, 103, 105, 107, 108, 114, 115,
#: 117, 119, 123, 125, 127, 128, 134, 135 or 137.
_LOWER: tuple[tuple[str, str, float, float], ...] = (
    ("101", "E", 1113, 620), ("104", "E", 1100, 728),
    ("106", "SE", 1000, 842),
    ("109", "S", 895, 842), ("110", "S", 812, 842), ("111", "S", 728, 842),
    ("112", "S", 645, 842), ("113", "S", 563, 842), ("116", "S", 453, 842),
    ("118", "SW", 355, 778),
    ("120", "W", 327, 700), ("121", "W", 327, 617), ("122", "W", 327, 543),
    ("124", "NW", 400, 502),
    ("126", "N", 453, 402), ("129", "N", 563, 402), ("130", "N", 645, 402),
    ("131", "N", 728, 402), ("132", "N", 812, 402), ("133", "N", 895, 402),
    ("136", "NE", 1000, 410),
    ("138", "E", 1100, 510),
)

#: Courtside. The feed labels these with a bare number ("03", "06", "10")
#: while the map labels courtside CS1-CS10, so each is placed at the matching
#: CS slot. That correspondence is an inference from the numbering, not
#: something the data states; it decides where a courtside tile is drawn and
#: never affects a price.
_COURTSIDE: tuple[tuple[str, str, float, float], ...] = (
    ("1", "E", 913, 600), ("2", "E", 913, 663),
    ("3", "S", 832, 730), ("4", "S", 728, 730), ("5", "S", 627, 730),
    ("6", "W", 543, 663), ("7", "W", 543, 600),
    ("8", "N", 627, 505), ("9", "N", 728, 505), ("10", "N", 832, 505),
)

#: Tile footprints per tier, in canvas units, sized to the spacing on the map.
TILE_SIZES = {
    TIER_UPPER: (5.4, 5.4),
    TIER_LOWER: (5.4, 4.8),
    TIER_FLOOR: (3.4, 2.6),
}

#: The court, as drawn on the reference map: x0, y0, x1, y1.
_COURT_PX = (575.0, 570.0, 885.0, 715.0)

LOWER_BOWL = [s for s, _, _, _ in _LOWER]
UPPER_BOWL = [s for s, _, _, _ in _UPPER]
COURTSIDE = [s for s, _, _, _ in _COURTSIDE]


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


def _project(px: float, py: float) -> tuple[float, float]:
    return (
        50.0 + (px - _ORIGIN_X) * _SCALE,
        _CANVAS_CY + (py - _ORIGIN_Y) * _SCALE,
    )


def layout(floor_sections: Iterable[str] | None = None) -> dict:
    """Return ``{section_key: {x, y, angle, tier}}`` on the drawing canvas.

    Both bowls are always drawn in full -- every number in them is a real
    section, so one with no listings in scope is genuinely missing data rather
    than a gap in the arena. Courtside is drawn only for the sections present
    in the snapshot, since the feed exposes a few of the ten and an empty ring
    of them would read as absent inventory.
    """
    out: dict[str, dict] = {}
    for src, t in ((_LOWER, TIER_LOWER), (_UPPER, TIER_UPPER)):
        for sec, edge, px, py in src:
            x, y = _project(px, py)
            out[sec] = {"x": round(x, 3), "y": round(y, 3),
                        "angle": _EDGE_ANGLE[edge], "tier": t}

    wanted = {s for s in (floor_sections or []) if tier(s) == TIER_FLOOR}
    for sec, edge, px, py in _COURTSIDE:
        if sec not in wanted:
            continue
        x, y = _project(px, py)
        out[sec] = {"x": round(x, 3), "y": round(y, 3),
                    "angle": _EDGE_ANGLE[edge], "tier": TIER_FLOOR}
    return out


def court() -> dict:
    """Bounding box of the court on the canvas, for drawing."""
    x0, y0 = _project(_COURT_PX[0], _COURT_PX[1])
    x1, y1 = _project(_COURT_PX[2], _COURT_PX[3])
    return {"x": round(x0, 3), "y": round(y0, 3),
            "w": round(x1 - x0, 3), "h": round(y1 - y0, 3)}


def canvas() -> dict:
    """Canvas the layout is expressed in, for the SVG viewBox."""
    return {"w": CANVAS_W, "h": CANVAS_H}
