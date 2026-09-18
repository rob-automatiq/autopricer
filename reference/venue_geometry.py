"""Generate the bowl geometry the desk draws (``artifact/venue.json``).

Target Center's three rings are each numbered **clockwise from due east**, in
plain numeric order — that is the one fact the whole layout rests on, and it is
read off the published seat map:

    floor   1 .. 10          (courtside strips, CS1-CS10 on the map)
    lower   22 sections      (the arena does NOT have 101-138)
    upper   201 .. 240

Each ring is laid on a **superellipse** — a rounded rectangle, which is the
shape an arena bowl actually is — and sections are spaced by **equal arc
length**, so the gap between neighbours is the same on a straight run as it is
through a corner. An earlier version placed tiles on an octagon and snapped
corner tiles to 45 degrees; that produced diamonds wedged between squares, with
collisions where the bends met. There are no corners to special-case here.

Run it with::

    python3 reference/venue_geometry.py            # writes artifact/venue.json
    python3 reference/venue_geometry.py --check     # geometry report only
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

CANVAS_W, CANVAS_H = 100.0, 70.0
CX, CY = CANVAS_W / 2, CANVAS_H / 2

#: An NBA court is 94 x 50 feet. Kept to that ratio so the middle of the map
#: reads as a court rather than as a generic box.
COURT_W = 30.5
COURT_H = COURT_W * 50 / 94

LOWER = ["101", "104", "106", "109", "110", "111", "112", "113", "116", "118",
         "120", "121", "122", "124", "126", "129", "130", "131", "132", "133",
         "136", "138"]
UPPER = [str(n) for n in range(201, 241)]
FLOOR = [str(n) for n in range(1, 11)]


@dataclass(frozen=True)
class Ring:
    tier: str
    sections: list[str]
    a: float          # semi-axis, east-west
    b: float          # semi-axis, north-south
    depth: float      # radial thickness of a tile
    n: float          # superellipse exponent; 2 is an ellipse, higher is boxier
    fill: float       # fraction of the arc step a tile occupies

    def point(self, t: float) -> tuple[float, float]:
        """A point on the ring at parameter ``t`` radians, clockwise on screen."""
        c, s = math.cos(t), math.sin(t)
        e = 2.0 / self.n
        x = self.a * math.copysign(abs(c) ** e, c)
        y = self.b * math.copysign(abs(s) ** e, s)
        return CX + x, CY + y

    def _samples(self, steps: int = 4000) -> list[tuple[float, float, float]]:
        """(t, x, y) walked once around, for arc-length work."""
        out = []
        for i in range(steps + 1):
            t = 2 * math.pi * i / steps
            x, y = self.point(t)
            out.append((t, x, y))
        return out

    def place(self) -> dict[str, dict]:
        """Lay the ring's sections out evenly by arc length."""
        samples = self._samples()
        # Cumulative arc length along the sampled path.
        cum = [0.0]
        for i in range(1, len(samples)):
            _, x0, y0 = samples[i - 1]
            _, x1, y1 = samples[i]
            cum.append(cum[-1] + math.hypot(x1 - x0, y1 - y0))
        perimeter = cum[-1]
        count = len(self.sections)
        step = perimeter / count

        def at_length(target: float) -> tuple[float, float, float]:
            """Interpolate (t, x, y) at an arc length, wrapping around."""
            target %= perimeter
            lo, hi = 0, len(cum) - 1
            while lo < hi:
                mid = (lo + hi) // 2
                if cum[mid] < target:
                    lo = mid + 1
                else:
                    hi = mid
            i = max(1, lo)
            span = cum[i] - cum[i - 1]
            f = 0.0 if span == 0 else (target - cum[i - 1]) / span
            t0, x0, y0 = samples[i - 1]
            t1, x1, y1 = samples[i]
            return (t0 + (t1 - t0) * f, x0 + (x1 - x0) * f, y0 + (y1 - y0) * f)

        def tangent(s: float) -> float:
            _, ax, ay = at_length(s - step * 0.2)
            _, bx, by = at_length(s + step * 0.2)
            return math.atan2(by - ay, bx - ax)

        out: dict[str, dict] = {}
        for i, sec in enumerate(self.sections):
            # Half a step in: the first and last sections then straddle due
            # east symmetrically, which is how the real numbering sits.
            s = (i + 0.5) * step
            _, px, py = at_length(s)
            angle = tangent(s)

            # Tiles are rectangles on a curving path, so neighbours converge on
            # their INNER edge wherever the ring turns. Around a bend of radius
            # R the inner edge is shorter than the centre line by h*dtheta/2,
            # so the width a tile may take is the step less exactly that. A
            # single fixed width is what wedged the corner tiles together.
            d = tangent(s + step / 2) - tangent(s - step / 2)
            d = (d + math.pi) % (2 * math.pi) - math.pi     # shortest turn
            usable = step - self.depth * abs(d) / 2
            w = max(step * 0.35, usable * self.fill)

            out[sec] = {
                "x": round(px - w / 2, 2),
                "y": round(py - self.depth / 2, 2),
                "w": round(w, 2),
                "h": round(self.depth, 2),
                "a": round(math.degrees(angle), 1),
                "t": self.tier,
            }
        return out


RINGS = (
    Ring("floor", FLOOR, a=21.8, b=12.6, depth=3.0, n=3.0, fill=0.86),
    Ring("lower", LOWER, a=31.6, b=19.7, depth=5.0, n=3.6, fill=0.84),
    Ring("upper", UPPER, a=42.0, b=27.6, depth=4.8, n=3.9, fill=0.86),
)


def corners(tile: dict) -> list[tuple[float, float]]:
    """The tile's four corners after rotation, for overlap checks."""
    cx = tile["x"] + tile["w"] / 2
    cy = tile["y"] + tile["h"] / 2
    th = math.radians(tile["a"])
    co, si = math.cos(th), math.sin(th)
    hw, hh = tile["w"] / 2, tile["h"] / 2
    pts = []
    for dx, dy in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)):
        pts.append((cx + dx * co - dy * si, cy + dx * si + dy * co))
    return pts


def overlap(t1: dict, t2: dict) -> bool:
    """Separating-axis test. An axis-aligned box test overstates a rotated
    tile by up to 40% and would report collisions that are not there."""
    for poly, other in ((corners(t1), corners(t2)), (corners(t2), corners(t1))):
        for i in range(4):
            x0, y0 = poly[i]
            x1, y1 = poly[(i + 1) % 4]
            ax, ay = -(y1 - y0), x1 - x0
            norm = math.hypot(ax, ay) or 1.0
            ax, ay = ax / norm, ay / norm
            p = [px * ax + py * ay for px, py in poly]
            q = [px * ax + py * ay for px, py in other]
            if max(p) < min(q) - 1e-9 or max(q) < min(p) - 1e-9:
                return False
    return True


def court() -> dict:
    return {
        "x": round(CX - COURT_W / 2, 3),
        "y": round(CY - COURT_H / 2, 3),
        "w": round(COURT_W, 3),
        "h": round(COURT_H, 3),
    }


def canvas() -> dict:
    return {"w": CANVAS_W, "h": CANVAS_H}


def layout() -> dict[str, dict]:
    tiles: dict[str, dict] = {}
    for ring in RINGS:
        tiles.update(ring.place())
    return tiles


def build() -> dict:
    return {"canvas": canvas(), "court": court(), "tiles": layout()}


def check(data: dict) -> int:
    tiles = data["tiles"]
    faults = 0

    # 1. Nothing may leave the canvas.
    for sec, t in tiles.items():
        for x, y in corners(t):
            if not (-0.2 <= x <= CANVAS_W + 0.2 and -0.2 <= y <= CANVAS_H + 0.2):
                print(f"  off-canvas: {sec} at ({x:.1f}, {y:.1f})")
                faults += 1
                break

    # 2. No two tiles may overlap.
    keys = list(tiles)
    for i, s1 in enumerate(keys):
        for s2 in keys[i + 1:]:
            if overlap(tiles[s1], tiles[s2]):
                print(f"  overlap: {s1} ~ {s2}")
                faults += 1

    # 3. The court must not touch the courtside strips.
    c = data["court"]
    cl, cr = c["x"], c["x"] + c["w"]
    ct, cb = c["y"], c["y"] + c["h"]
    worst = 1e9
    for sec, t in tiles.items():
        if t["t"] != "floor":
            continue
        for x, y in corners(t):
            inside_x = cl < x < cr
            inside_y = ct < y < cb
            if inside_x and inside_y:
                print(f"  courtside {sec} corner inside the court at ({x:.1f}, {y:.1f})")
                faults += 1
            gap = min(abs(x - cl), abs(x - cr)) if inside_y else (
                min(abs(y - ct), abs(y - cb)) if inside_x else
                math.hypot(min(abs(x - cl), abs(x - cr)), min(abs(y - ct), abs(y - cb))))
            worst = min(worst, gap)
    print(f"  court-to-courtside clearance: {worst:.2f} units")

    # 4. Spacing must be even within a ring.
    for ring in RINGS:
        gaps = []
        secs = ring.sections
        for i, sec in enumerate(secs):
            nxt = secs[(i + 1) % len(secs)]
            t1, t2 = tiles[sec], tiles[nxt]
            c1 = (t1["x"] + t1["w"] / 2, t1["y"] + t1["h"] / 2)
            c2 = (t2["x"] + t2["w"] / 2, t2["y"] + t2["h"] / 2)
            gaps.append(math.dist(c1, c2))
        spread = (max(gaps) - min(gaps)) / (sum(gaps) / len(gaps))
        print(f"  {ring.tier:<6} {len(secs):>2} sections, "
              f"centre spacing {min(gaps):.2f}-{max(gaps):.2f} "
              f"(spread {spread:.1%}), tile {tiles[secs[0]]['w']:.2f} wide")
        if spread > 0.12:
            print(f"    uneven spacing in the {ring.tier} ring")
            faults += 1
    return faults


if __name__ == "__main__":
    data = build()
    print(f"{len(data['tiles'])} sections")
    faults = check(data)
    if "--check" not in sys.argv:
        out = Path(__file__).resolve().parent.parent / "artifact" / "venue.json"
        out.write_text(json.dumps(data, separators=(",", ":")))
        print(f"wrote {out} ({out.stat().st_size} bytes)")
    print("FAULTS:", faults)
    raise SystemExit(1 if faults else 0)
