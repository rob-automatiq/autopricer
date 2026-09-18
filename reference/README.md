# reference

Not part of the tool. Nothing here runs in the artifact, and nothing here is on
a path the page can reach.

## `venue_geometry.py`

Generates `artifact/venue.json` — the bowl positions the page draws. Kept
executable because the geometry is derived rather than transcribed, and
regenerating beats hand-editing coordinates.

```bash
python3 reference/venue_geometry.py            # writes artifact/venue.json
python3 reference/venue_geometry.py --check     # geometry report, writes nothing
```

The one fact the layout rests on: **all three rings are numbered clockwise from
due east**, in plain numeric order — 22 lower-bowl sections (the arena does not
have 101-138), 40 upper, 10 courtside strips.

Each ring is laid on a **superellipse** (a rounded rectangle, which is the shape
an arena bowl is) with sections spaced by **equal arc length**, so the gap
between neighbours is the same on a straight run as through a corner. Tile width
is reduced by the local turn: rectangles on a curving path converge on their
inner edge, by `depth × dθ / 2` around a bend, and a single fixed width is what
wedged the corner tiles together in the first version.

`--check` is the thing to trust, not the eye. It fails on any tile leaving the
canvas, any overlapping pair (separating-axis, because an axis-aligned test
overstates a rotated tile by up to 40%), a courtside strip touching the court,
or a ring whose centre spacing varies by more than 12%. It currently reports
zero faults, 1.66 units of court clearance, and spacing spread under 4.5%.

An earlier version placed tiles on an octagon and snapped corner tiles to 45°,
which produced diamonds wedged between squares with collisions at the bends.
There are no corners to special-case in this approach.
