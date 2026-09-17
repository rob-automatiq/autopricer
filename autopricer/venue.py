"""Target Center seating geometry.

The arena is modelled as two concentric octagonal rings around the court, with
courtside strips hugging the floor. A ring is defined by which sections sit on
each of its eight edges plus one spacing constant; every other dimension is
derived, so sections come out evenly spaced by construction rather than from
transcribed coordinates that drift.

**Each edge is made exactly ``section count x spacing`` long.** That is what
makes the spacing uniform all the way round, including across the corners. Two
earlier attempts did not: centring each run on its own edge left the north edge
and the north-east diagonal with different spacings, so their end sections
crowded and collided where the edges met, and insetting the run ends moved the
collision without removing it. With proportional edges the gap across a bend is
the same ``spacing`` as everywhere else.

Each ring sizes its tiles as a fraction of its own spacing. At a 45-degree bend
a square tile has to be no more than about 0.71 x spacing to clear the corner
tile beside it, which is the ceiling ``TILE_FACTOR_MAX`` enforces.

What the layout takes from the published seat map is the part no formula knows:

* **The ordering.** Both bowls are numbered clockwise from the east side. 101
  faces the court from the east, 111 and 112 sit along the south edge, 131
  along the north, 121 to the west.
* **Which sections exist.** The lower bowl is not 101-138. Target Center has 22
  lower-bowl sections; the other sixteen numbers in that range are not seating
  at all, so drawing the full range invents sixteen sections that then render
  as "no data". The 22 here match the snapshot's section set exactly.
* **Courtside.** CS1 and CS2 flank the east sideline, CS3 to CS5 run along the
  south baseline east to west, CS6 and CS7 the west sideline, CS8 to CS10 the
  north baseline west to east.

Club, suite, table and theatre-box inventory (the map's C*, S*, TB* and TI*
labels) is not drawn: none of it appears in the VividSeats feed, so there would
be nothing to shade. The band between courtside and the lower bowl is where it
would sit.
"""

from __future__ import annotations

import math
from typing import Iterable

TIER_FLOOR = "floor"
TIER_LOWER = "lower"
TIER_UPPER = "upper"

#: Drawing canvas. Wider than tall, in the arena's proportions.
CANVAS_W, CANVAS_H = 100.0, 70.0
_CX, _CY = 50.0, 35.0

#: Tile side as a fraction of the ring's spacing, per ring. Above ~0.71 the
#: corner tiles, which sit at 45 degrees, start to clip the flat-edge tiles
#: beside them, so that is a hard ceiling.
#:
#: The lower bowl carries 22 sections around a ring nearly as large as the
#: upper's 40, so its spacing is much wider. Taking the same fraction of it
#: made lower-bowl tiles more than twice the area of upper-bowl ones, which
#: read as a mistake rather than as "these sections are wider"; a smaller
#: fraction keeps the two rings in proportion.
TILE_FACTOR_MAX = 0.7071

#: Ring edges, clockwise from the north.
_EDGE_ORDER = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")

_R2 = math.sqrt(2)


class _Ring:
    """One bowl: the sections on each of its eight edges, plus a spacing.

    Every dimension follows from the section counts, so the edges stay
    proportional to what they carry and the spacing stays uniform.
    """

    def __init__(self, spacing: float, tile_factor: float,
                 edges: dict[str, list[str]]) -> None:
        if tile_factor > TILE_FACTOR_MAX:
            raise ValueError(
                f"tile factor {tile_factor} exceeds {TILE_FACTOR_MAX}; the "
                "45-degree corner tiles would clip their neighbours")
        self.edges = edges
        self.s = spacing
        self.tile = round(tile_factor * spacing, 3)

        n = {e: len(edges[e]) for e in _EDGE_ORDER}
        # Opposite edges must match or the ring is not centred on the court.
        for a, b in (("N", "S"), ("E", "W"), ("NE", "SW"), ("NW", "SE")):
            if n[a] != n[b]:
                raise ValueError(
                    f"ring is lopsided: {a} has {n[a]} sections, {b} has {n[b]}")
        corner = n["NE"] * spacing / _R2
        self.hx = n["N"] * spacing / 2
        self.hy = n["E"] * spacing / 2
        self.rx = self.hx + corner
        self.ry = self.hy + corner

    def _edge_points(self, edge: str) -> tuple[tuple[float, float], tuple[float, float]]:
        rx, ry, hx, hy = self.rx, self.ry, self.hx, self.hy
        return {
            "N": ((-hx, -ry), (hx, -ry)),
            "NE": ((hx, -ry), (rx, -hy)),
            "E": ((rx, -hy), (rx, hy)),
            "SE": ((rx, hy), (hx, ry)),
            "S": ((hx, ry), (-hx, ry)),
            "SW": ((-hx, ry), (-rx, hy)),
            "W": ((-rx, hy), (-rx, -hy)),
            "NW": ((-rx, -hy), (-hx, -ry)),
        }[edge]

    def place(self) -> dict[str, dict]:
        """Position every section on its edge, one spacing apart."""
        out: dict[str, dict] = {}
        for edge in _EDGE_ORDER:
            secs = self.edges[edge]
            (x0, y0), (x1, y1) = self._edge_points(edge)
            dx, dy = x1 - x0, y1 - y0
            # A tile's width lies along its edge, so rotating by the edge's
            # bearing leaves it flat against the bowl. Modulo 180 because a
            # rectangle turned a half-turn is the same rectangle.
            angle = math.degrees(math.atan2(dy, dx)) % 180.0
            for i, sec in enumerate(secs):
                # Half a spacing in from each end, so the last section of one
                # edge and the first of the next are a full spacing apart.
                t = (i + 0.5) / len(secs)
                out[sec] = {
                    "x": round(_CX + x0 + dx * t, 3),
                    "y": round(_CY + y0 + dy * t, 3),
                    "angle": round(angle, 3),
                    "w": self.tile,
                    "h": self.tile,
                }
        return out


#: Upper bowl, 40 sections. Spacing is the largest the canvas allows.
_UPPER = _Ring(
    spacing=6.91, tile_factor=0.70,
    edges={
        "N": ["227", "228", "229", "230", "231", "232", "233", "234", "235"],
        "NE": ["236", "237", "238"],
        "E": ["239", "240", "201", "202", "203"],
        "SE": ["204", "205", "206"],
        "S": ["207", "208", "209", "210", "211", "212", "213", "214", "215"],
        "SW": ["216", "217", "218"],
        "W": ["219", "220", "221", "222", "223"],
        "NW": ["224", "225", "226"],
    },
)

#: Lower bowl, 22 sections, spaced so it sits one and a half units inside the
#: upper ring on the east side. Its sections are physically wider than the
#: upper bowl's, and the wider tile falls out of the larger spacing. The gaps
#: in the numbering are real -- there is no 102, 103, 105, 107, 108, 114, 115,
#: 117, 119, 123, 125, 127, 128, 134, 135 or 137.
_LOWER = _Ring(
    spacing=10.31, tile_factor=0.62,
    edges={
        "N": ["126", "129", "130", "131", "132", "133"],
        "NE": ["136"],
        "E": ["138", "101", "104"],
        "SE": ["106"],
        "S": ["109", "110", "111", "112", "113", "116"],
        "SW": ["118"],
        "W": ["120", "121", "122"],
        "NW": ["124"],
    },
)

# --- the court and courtside, sized to fit inside the lower ring ------------
_CS_DEPTH = 2.6          # strip thickness
_CS_OFFSET = 1.8         # strip centre, out from the court edge
_CLEARANCE = 1.5         # held between courtside and the lower bowl

_hh_limit = (_CY - (_LOWER.ry - _LOWER.tile / 2) - _CLEARANCE) - _CS_DEPTH / 2 - _CS_OFFSET
_hw_limit = (_LOWER.rx - _LOWER.tile / 2) - _CLEARANCE - _CS_DEPTH / 2 - _CS_OFFSET
#: Court half-extents, at a regulation 94x50 foot ratio.
_COURT_HH = round(min(_hh_limit, _hw_limit / 1.875), 3)
_COURT_HW = round(_COURT_HH * 1.875, 3)

#: Baseline strips span the court in thirds, sideline strips in halves.
_CS_BASELINE = (round(_COURT_HW * 2 / 3 - 1.1, 3), _CS_DEPTH)
_CS_SIDELINE = (round(_COURT_HH - 1.1, 3), _CS_DEPTH)


def _courtside() -> dict[str, dict]:
    out: dict[str, dict] = {}
    third = _COURT_HW * 2 / 3
    half = _COURT_HH
    base = dict(angle=0.0, w=_CS_BASELINE[0], h=_CS_BASELINE[1])
    side = dict(angle=90.0, w=_CS_SIDELINE[0], h=_CS_SIDELINE[1])
    for i, sec in enumerate(("8", "9", "10")):        # north, west to east
        out[sec] = {**base, "x": round(_CX + (i - 1) * third, 3),
                    "y": round(_CY - _COURT_HH - _CS_OFFSET, 3)}
    for i, sec in enumerate(("3", "4", "5")):         # south, east to west
        out[sec] = {**base, "x": round(_CX + (1 - i) * third, 3),
                    "y": round(_CY + _COURT_HH + _CS_OFFSET, 3)}
    for i, sec in enumerate(("1", "2")):              # east, north to south
        out[sec] = {**side, "x": round(_CX + _COURT_HW + _CS_OFFSET, 3),
                    "y": round(_CY + (i - 0.5) * half, 3)}
    for i, sec in enumerate(("6", "7")):              # west, south to north
        out[sec] = {**side, "x": round(_CX - _COURT_HW - _CS_OFFSET, 3),
                    "y": round(_CY + (0.5 - i) * half, 3)}
    return out


_COURTSIDE = _courtside()

LOWER_BOWL = [s for e in _EDGE_ORDER for s in _LOWER.edges[e]]
UPPER_BOWL = [s for e in _EDGE_ORDER for s in _UPPER.edges[e]]
COURTSIDE = sorted(_COURTSIDE, key=int)


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


def layout(floor_sections: Iterable[str] | None = None) -> dict:
    """Return ``{section: {x, y, angle, w, h, tier}}`` on the drawing canvas.

    Both bowls are drawn in full -- every number in them is a real section, so
    one with no listings in scope is genuinely missing data rather than a gap
    in the arena. Courtside is drawn only for the sections present in the
    snapshot, since the feed exposes a few of the ten and an empty ring of them
    would read as absent inventory.
    """
    out: dict[str, dict] = {}
    for ring, t in ((_LOWER, TIER_LOWER), (_UPPER, TIER_UPPER)):
        for sec, pos in ring.place().items():
            out[sec] = {**pos, "tier": t}

    wanted = {s for s in (floor_sections or []) if tier(s) == TIER_FLOOR}
    for sec in sorted(wanted, key=int):
        pos = _COURTSIDE.get(sec)
        if pos is not None:
            out[sec] = {**pos, "tier": TIER_FLOOR}
    return out


def court() -> dict:
    """Bounding box of the court on the canvas, for drawing."""
    return {
        "x": round(_CX - _COURT_HW, 3), "y": round(_CY - _COURT_HH, 3),
        "w": round(_COURT_HW * 2, 3), "h": round(_COURT_HH * 2, 3),
    }


def canvas() -> dict:
    """Canvas the layout is expressed in, for the SVG viewBox."""
    return {"w": CANVAS_W, "h": CANVAS_H}


def tile_bounds(pos: dict) -> tuple[float, float, float, float]:
    """Axis-aligned bounds of a placed tile, accounting for its rotation."""
    th = math.radians(pos["angle"])
    hx = (abs(pos["w"] * math.cos(th)) + abs(pos["h"] * math.sin(th))) / 2
    hy = (abs(pos["w"] * math.sin(th)) + abs(pos["h"] * math.cos(th))) / 2
    return pos["x"] - hx, pos["y"] - hy, pos["x"] + hx, pos["y"] + hy


def tile_corners(pos: dict) -> list[tuple[float, float]]:
    """The four corners of a placed tile, in canvas coordinates."""
    th = math.radians(pos["angle"])
    c, s = math.cos(th), math.sin(th)
    hw, hh = pos["w"] / 2, pos["h"] / 2
    return [
        (pos["x"] + dx * c - dy * s, pos["y"] + dx * s + dy * c)
        for dx, dy in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh))
    ]


def tiles_overlap(a: dict, b: dict, slack: float = 0.01) -> bool:
    """Whether two placed tiles overlap, by separating axes.

    The corner tiles sit at 45 degrees, where an axis-aligned bounding box
    overstates the footprint by about 40% and reports collisions between
    neighbours that in fact clear each other. This tests the rotated
    rectangles themselves.
    """
    for rect in (a, b):
        th = math.radians(rect["angle"])
        for ax, ay in ((math.cos(th), math.sin(th)), (-math.sin(th), math.cos(th))):
            pa = [x * ax + y * ay for x, y in tile_corners(a)]
            pb = [x * ax + y * ay for x, y in tile_corners(b)]
            if min(pa) >= max(pb) - slack or min(pb) >= max(pa) - slack:
                return False
    return True
