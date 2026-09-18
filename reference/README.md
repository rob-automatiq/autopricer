# reference

Not part of the tool. Nothing here runs in the artifact, and nothing here is on
a path the page can reach.

## `venue_geometry.py`

Generates `artifact/venue.json` — the bowl positions the page draws. It is the
one piece of the retired Python worth keeping executable, because the geometry
is derived rather than transcribed, and regenerating it beats hand-editing
coordinates.

```bash
python3 - <<'PY'
import json, sys
sys.path.insert(0, "reference")
import venue_geometry as v
out = {
    "canvas": v.canvas(),
    "court": v.court(),
    "tiles": {k: {"x": round(t["x"], 2), "y": round(t["y"], 2),
                  "w": round(t["w"], 2), "h": round(t["h"], 2),
                  "a": round(t["angle"], 1), "t": t["tier"]}
              for k, t in v.layout().items()},
}
open("artifact/venue.json", "w").write(json.dumps(out, separators=(",", ":")))
print(len(out["tiles"]), "sections")
PY
```

Edges are derived from section counts so that each edge is exactly
`count × spacing` long — that proportionality is what keeps the spacing even
across the 45° corners, and tiles are capped at 0.7071 × spacing so a corner
tile cannot clip its flat-edge neighbours. 22 lower-bowl sections, 40 upper, 10
courtside strips.
