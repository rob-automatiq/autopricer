"""Diff every payload the standalone page computes against the Python engine.

The standalone build reimplements the aggregations and the quote arithmetic in
JavaScript. That is a second implementation, and the only thing that makes it
trustworthy is checking it against the first one exhaustively rather than
spot-checking a couple of screens.

This loads dist/autopricer.html in Chromium, asks the in-page engine for every
endpoint and every scope -- plus a quote for *every* seat that appears on the
board or in the sales -- and compares each payload field by field with the
Python model in this process. Any mismatch fails the run and prints the path.

    python3 scripts/verify_artifact.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from autopricer import views                      # noqa: E402
from autopricer.server import State                # noqa: E402

CHROME_CANDIDATES = [
    "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
    "/opt/pw-browsers/chromium/chrome-linux/chrome",
]
PAGE = ROOT / "dist" / "preview.html"
BATCH = 400
TOL = 1e-6


def chrome() -> str | None:
    for c in CHROME_CANDIDATES:
        if Path(c).exists():
            return c
    return None


def diff(a, b, path="") -> list[str]:
    """Structural comparison with a float tolerance. Returns difference paths."""
    if isinstance(a, bool) or isinstance(b, bool):
        return [] if a == b else [f"{path}: {a!r} != {b!r}"]
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if a == b:
            return []
        scale = max(1.0, abs(a), abs(b))
        return [] if abs(a - b) <= TOL * scale else [f"{path}: {a!r} != {b!r}"]
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            if k not in a:
                out.append(f"{path}.{k}: missing in python")
            elif k not in b:
                out.append(f"{path}.{k}: missing in page")
            else:
                out += diff(a[k], b[k], f"{path}.{k}")
        return out
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{path}: length {len(a)} != {len(b)}"]
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff(x, y, f"{path}[{i}]")
        return out
    return [] if a == b else [f"{path}: {a!r} != {b!r}"]


def build_expected(st: State) -> tuple[dict, dict]:
    """Every path to check, mapped to what Python says it should return."""
    snap, model = st.snap, st.model
    ok: dict[str, object] = {}
    errs: dict[str, str] = {}

    ok["/api/meta"] = st.meta()
    ok["/api/map"] = views.venue_map(snap)
    ok["/api/model"] = model.summary()
    ok["/api/overview"] = views.event_overview(snap)

    scopes = ["all"] + snap.event_keys()
    for sc in scopes:
        ok[f"/api/sales?event={sc}"] = views.sales_by_section(snap, sc)
        ok[f"/api/listings?event={sc}"] = views.listings_by_section(snap, sc)

    sections = snap.sections()
    for sec in sections:
        ok[f"/api/section/{sec}?event=all"] = views.section_detail(snap, sec, "all")
    # A few games at section grain too, so the per-game path is covered.
    for ev in snap.event_keys()[:4] + snap.event_keys()[-2:]:
        for sec in sections:
            ok[f"/api/section/{sec}?event={ev}"] = views.section_detail(snap, sec, ev)

    # A quote for every seat that exists on either side of the data.
    seats = {(l.event_date, l.section, l.row or "") for l in snap.listings}
    seats |= {(s.event_date, s.section, s.row or "") for s in snap.sales}
    for ev, sec, row in sorted(seats):
        p = f"/api/price?event={ev}&section={sec}&row={row}&qty=2&strategy=balanced"
        ok[p] = model.recommend(ev, sec, row or None, 2, "balanced")

    # Every strategy, and a couple of quantities, on a handful of seats.
    for ev, sec, row in sorted(seats)[:40]:
        for strat in model.p.strategy_names:
            p = f"/api/price?event={ev}&section={sec}&row={row}&qty=3&strategy={strat}"
            ok[p] = model.recommend(ev, sec, row or None, 3, strat)

    # A quote with no row at all.
    p = "/api/price?event=2026-12-25&section=112&row=&qty=2&strategy=balanced"
    ok[p] = model.recommend("2026-12-25", "112", None, 2, "balanced")

    # Error paths must match too, message for message: the UI shows them.
    errs["/api/price?event=1999-01-01&section=112"] = "unknown event '1999-01-01'"
    errs["/api/price?event=2026-12-25&section=999"] = (
        "'999' is not a Target Center seat section")
    errs["/api/price?section=112"] = "event and section are required"
    errs["/api/price?event=2026-12-25"] = "event and section are required"
    errs["/api/price?event=2026-12-25&section=112&qty=abc"] = (
        "qty must be a whole number, got 'abc'")
    errs["/api/price?event=2026-12-25&section=112&strategy=yolo"] = (
        "unknown strategy 'yolo'; expected one of "
        "['aggressive', 'balanced', 'patient']")
    errs["/nope"] = "not found"
    return ok, errs


def main() -> int:
    if not PAGE.exists():
        print("dist/preview.html missing - run scripts/build_artifact.py first")
        return 1
    exe = chrome()
    if exe is None:
        print("no chromium found; cannot verify")
        return 1
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed; cannot verify")
        return 1

    st = State()
    expected_ok, expected_err = build_expected(st)
    print(f"checking {len(expected_ok):,} payloads and "
          f"{len(expected_err)} error paths")

    failures: list[str] = []
    checked = 0

    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=exe)
        pg = b.new_page()
        console: list[str] = []
        pg.on("pageerror", lambda e: console.append(str(e)))
        pg.goto(PAGE.as_uri(), wait_until="load")
        pg.wait_for_function("() => typeof window.AUTOPRICER_LOCAL === 'function'",
                             timeout=30_000)
        if console:
            print("page errors on load:")
            for c in console:
                print("  " + c)
            b.close()
            return 1

        paths = list(expected_ok) + list(expected_err)
        for start in range(0, len(paths), BATCH):
            batch = paths[start:start + BATCH]
            got = pg.evaluate(
                """(paths) => paths.map((p) => {
                     try { return { ok: window.AUTOPRICER_LOCAL(p) }; }
                     catch (e) { return { err: String(e.message) }; }
                   })""",
                batch,
            )
            for path, res in zip(batch, got):
                checked += 1
                if path in expected_err:
                    want = expected_err[path]
                    if "err" not in res:
                        failures.append(f"{path}: expected an error, page returned data")
                    elif res["err"] != want:
                        failures.append(
                            f"{path}: error text\n    python: {want}\n    page:   {res['err']}")
                    continue
                if "err" in res:
                    failures.append(f"{path}: page raised {res['err']!r}")
                    continue
                for d in diff(expected_ok[path], res["ok"])[:6]:
                    failures.append(f"{path}{d}")
            if start and start % (BATCH * 5) == 0:
                print(f"  {start:,}/{len(paths):,} …")
        b.close()

    print(f"compared {checked:,} payloads")
    if failures:
        print(f"\n{len(failures)} MISMATCH(ES):")
        for f in failures[:40]:
            print("  " + f)
        if len(failures) > 40:
            print(f"  … and {len(failures) - 40} more")
        return 1
    print("the standalone page matches the Python engine exactly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
