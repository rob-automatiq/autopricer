"""Build a single self-contained autopricer page.

Inlines the dashboard's CSS and JS, the snapshot TSVs verbatim, and the three
surfaces the Python model fitted. The result needs no server: web/engine.js
computes the same payloads in-page, and web/app.js is used unchanged, so the
UI has exactly one implementation.

    python3 scripts/build_artifact.py        # -> dist/autopricer.html

Verify it with scripts/verify_artifact.py, which diffs every payload the page
produces against the live Python API.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from autopricer import views                      # noqa: E402
from autopricer.config import PARAMS              # noqa: E402
from autopricer.data import DATA_DIR, load        # noqa: E402
from autopricer.model import PricingModel          # noqa: E402
from autopricer.server import State                # noqa: E402

WEB = ROOT / "web"
DIST = ROOT / "dist"


def bundle() -> dict:
    """Everything the page needs, with the hard statistics precomputed."""
    st = State()
    snap, model = st.snap, st.model

    # Row support is keyed by (tier, ordinal) in Python; nest it for JS.
    row_support: dict[str, dict[int, int]] = {}
    for (tier, ordinal), n in model.row_support.items():
        row_support.setdefault(tier, {})[ordinal] = n

    row_curve: dict[str, dict[int, float]] = {}
    for (tier, ordinal), f in model.row_curve.items():
        row_curve.setdefault(tier, {})[ordinal] = f

    return {
        "built": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        # The page must agree with the server on "today" or every
        # days_to_event would differ.
        "today": dt.date.today().isoformat(),
        "events_tsv": (DATA_DIR / "events.tsv").read_text(),
        "sales_tsv": (DATA_DIR / "sales.tsv").read_text(),
        "listings_tsv": (DATA_DIR / "listings.tsv").read_text(),
        "meta": st.meta(),
        "map": views.venue_map(snap),
        "model": model.summary(),
        "surfaces": {
            "event_level": model.event_level,
            "event_level_estimated": sorted(model.event_level_estimated),
            "section_index": model.section_index,
            "section_index_support": model.section_index_support,
            "tier_index": model.tier_index,
            "row_curve": row_curve,
            "row_support": row_support,
            "clear_ratio": model.clear_ratio,
            "tier_clear_ratio": model.tier_clear_ratio,
        },
        "params": {
            "min_comps": PARAMS.min_comps,
            "neighbour_index_tol": PARAMS.neighbour_index_tol,
            "widen_target": PARAMS.widen_target,
            "comp_blend_k": PARAMS.comp_blend_k,
            "sale_blend_k": PARAMS.sale_blend_k,
            "max_comp_percentile": PARAMS.max_comp_percentile,
            "strategies": [list(s) for s in PARAMS.strategies],
            "default_strategy": PARAMS.default_strategy,
        },
    }


#: Gallery name for the published page. A name, not a summary.
ARTIFACT_TITLE = "Timberwolves Ticket Pricer"

#: Minimal stand-in for the skeleton the Artifact platform injects at publish
#: time, so dist/preview.html renders over file:// exactly as the published
#: page will. Kept in step with the documented skeleton: charset and viewport
#: with viewport-fit=cover, safe-area padding on :root, zero body margin, and
#: the two element resets.
PREVIEW_SKELETON = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<style>
  :root {{ color-scheme: light;
    padding-top: env(safe-area-inset-top, 0px);
    padding-bottom: env(safe-area-inset-bottom, 0px); }}
  body {{ margin: 0; font: 14px system-ui, sans-serif; background: #fafaf9; }}
  img {{ max-width: 100%; }}
  [hidden] {{ display: none !important; }}
</style>
</head>
<body>
{content}
</body>
</html>
"""


def _extract(html: str) -> tuple[str, str]:
    """Pull the <style> block and the body's inner HTML out of index.html."""
    style = re.search(r"<style>.*?</style>", html, re.S)
    if not style:
        raise SystemExit("no <style> block found in index.html")
    body = re.search(r"<body[^>]*>(.*)</body>", html, re.S)
    if not body:
        raise SystemExit("no <body> found in index.html")
    return style.group(0), body.group(1).strip()


def build() -> tuple[Path, Path]:
    html = (WEB / "index.html").read_text()
    app_js = (WEB / "app.js").read_text()
    engine_js = (WEB / "engine.js").read_text()
    data = bundle()

    style, body = _extract(html)

    # </script> inside embedded JSON would close the tag early.
    payload = json.dumps(data, separators=(",", ":"), default=str) \
        .replace("</", "<\\/")
    inline = (
        "<script>window.AUTOPRICER_BUNDLE=" + payload + ";</script>\n"
        "<script>\n" + engine_js + "\n</script>\n"
        "<script>\n" + app_js + "\n</script>"
    )

    content, n = re.subn(
        r'<script src="/static/app\.js"></script>', lambda _: inline, body)
    if n != 1:
        raise SystemExit("could not find the app.js script tag in index.html")

    # The Artifact platform supplies <html>, <head> and <body>, so the
    # published file carries only a title, the styles and the content. Its
    # head already has charset and viewport, and the favicon comes from the
    # publish call, so index.html's own copies of those are dropped here.
    artifact = (
        f"<title>{ARTIFACT_TITLE}</title>\n"
        f"<!-- built {data['built']} from the snapshot in data/raw/ -->\n"
        f"{style}\n{content}\n"
    )

    DIST.mkdir(exist_ok=True)
    art = DIST / "artifact.html"
    art.write_text(artifact)
    # Verified over file:// through the same skeleton the platform injects, so
    # what gets checked is what gets published.
    prev = DIST / "preview.html"
    prev.write_text(PREVIEW_SKELETON.format(content=artifact))
    return art, prev


if __name__ == "__main__":
    art, prev = build()
    snap = load()
    kb = art.stat().st_size / 1024
    print(f"{art.relative_to(ROOT)}   {kb:,.0f} KB   (publish this)")
    print(f"{prev.relative_to(ROOT)}    wrapped for local file:// checks")
    print(f"  title: {ARTIFACT_TITLE!r}")
    print(f"  {len(snap.events)} games | {len(snap.listings):,} listings "
          f"| {len(snap.sales):,} sales")
    # Word-boundary match, so <header> is not mistaken for <head>.
    banned = re.search(
        r"<\s*/?\s*(!doctype|html|head|body)\b", art.read_text(), re.I)
    if banned:
        raise SystemExit(
            f"artifact.html must not contain {banned.group(0)!r} - the platform "
            "supplies the skeleton")
    if kb > 15_000:
        raise SystemExit("over the 16MB artifact limit")
