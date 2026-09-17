"""Aggregations backing the dashboard.

Kept apart from ``model.py``: nothing here feeds a recommendation, it only
answers "what happened" and "what is on sale right now".
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict

from . import venue
from .data import Snapshot
from .stats import describe, median


def _event_filter(snap: Snapshot, event: str | None) -> str | None:
    """Resolve the ``event`` query scope, rejecting a date with no home game.

    ``None``, ``""`` and ``"all"`` all mean every game. Anything else has to
    name a real one: an unrecognised date used to come back as a payload with
    nothing in it, which reads like a game with no board rather than a typo.
    """
    if event in (None, "", "all"):
        return None
    snap.require_event(event)  # type: ignore[arg-type]
    return event


def event_overview(snap: Snapshot) -> list[dict]:
    """One row per home game: board depth, ask level, and what has sold."""
    today = dt.date.today()
    out = []
    for ev in snap.events:
        listings = snap.listings_for(ev.key)
        sales = snap.sales_for(ev.key)
        asks = [l.price for l in listings]
        out.append(
            {
                "event": ev.key,
                "label": ev.label,
                "opponent": ev.opponent,
                "game_type": ev.game_type,
                "days_to_event": (ev.event_date - today).days,
                "listings": len(listings),
                "tickets_listed": sum(l.qty for l in listings),
                "sections_listed": len({l.section for l in listings}),
                "ask_median": round(median(asks), 2) if asks else None,
                "ask_min": round(min(asks), 2) if asks else None,
                "sales": len(sales),
                "tickets_sold": sum(s.qty for s in sales),
                "gross": round(sum(s.gross for s in sales), 2),
                "avg_sale_price": (
                    round(sum(s.gross for s in sales) / sum(s.qty for s in sales), 2)
                    if sales
                    else None
                ),
            }
        )
    return out


def sales_by_section(snap: Snapshot, event: str | None = None) -> dict:
    """Feature 1: where the sales happened."""
    event = _event_filter(snap, event)
    sales = snap.sales_for(event) if event else snap.sales

    by_sec = defaultdict(list)
    for s in sales:
        by_sec[s.section].append(s)

    sections = []
    for sec, rows in by_sec.items():
        qty = sum(r.qty for r in rows)
        gross = sum(r.gross for r in rows)
        margins = [r.margin * r.qty for r in rows if r.margin is not None]
        cost_known_qty = sum(r.qty for r in rows if r.margin is not None)
        sections.append(
            {
                "section": sec,
                "tier": venue.tier(sec),
                "sales": len(rows),
                "tickets_sold": qty,
                "gross": round(gross, 2),
                "avg_price": round(gross / qty, 2) if qty else None,
                "price": describe([r.price for r in rows]),
                # The broker's side of the same sales, which is what Uptick
                # reports. Absent on most rows, so it is summarised separately
                # rather than mixed into the gross figures.
                "net": describe([r.net for r in rows if r.net is not None]),
                "margin_total": round(sum(margins), 2) if margins else None,
                "margin_per_ticket": (
                    round(sum(margins) / cost_known_qty, 2) if cost_known_qty else None
                ),
                "rows_sold": sorted({r.row for r in rows if r.row}),
            }
        )
    sections.sort(key=lambda d: -d["tickets_sold"])

    by_row = defaultdict(lambda: {"tickets": 0, "gross": 0.0, "sales": 0})
    for s in sales:
        if s.row:
            b = by_row[s.row]
            b["tickets"] += s.qty
            b["gross"] += s.gross
            b["sales"] += 1

    by_day = defaultdict(lambda: {"tickets": 0, "gross": 0.0, "sales": 0})
    for s in sales:
        if s.invoice_date:
            b = by_day[s.invoice_date.isoformat()]
            b["tickets"] += s.qty
            b["gross"] += s.gross
            b["sales"] += 1

    by_marketplace = defaultdict(lambda: {"tickets": 0, "gross": 0.0, "sales": 0})
    for s in sales:
        b = by_marketplace[s.marketplace]
        b["tickets"] += s.qty
        b["gross"] += s.gross
        b["sales"] += 1

    by_type = defaultdict(lambda: {"tickets": 0, "gross": 0.0, "sales": 0})
    for s in sales:
        b = by_type[s.sale_type]
        b["tickets"] += s.qty
        b["gross"] += s.gross
        b["sales"] += 1

    total_qty = sum(s.qty for s in sales)
    return {
        "scope": event or "all",
        "totals": {
            "sales": len(sales),
            "tickets_sold": total_qty,
            "gross": round(sum(s.gross for s in sales), 2),
            "avg_price": (
                round(sum(s.gross for s in sales) / total_qty, 2) if total_qty else None
            ),
            "sections_with_sales": len(by_sec),
            "net_reported": sum(1 for s in sales if s.net is not None),
        },
        "sections": sections,
        "by_row": [
            {"row": r, **{k: (round(v, 2) if isinstance(v, float) else v)
                          for k, v in b.items()}}
            for r, b in sorted(by_row.items())
        ],
        "by_day": [
            {"date": d, **{k: (round(v, 2) if isinstance(v, float) else v)
                           for k, v in b.items()}}
            for d, b in sorted(by_day.items())
        ],
        "by_marketplace": [
            {"marketplace": m, **{k: (round(v, 2) if isinstance(v, float) else v)
                                  for k, v in b.items()}}
            for m, b in sorted(by_marketplace.items(), key=lambda kv: -kv[1]["tickets"])
        ],
        "by_type": [
            {"type": t, **{k: (round(v, 2) if isinstance(v, float) else v)
                           for k, v in b.items()}}
            for t, b in sorted(by_type.items(), key=lambda kv: -kv[1]["tickets"])
        ],
    }


def listings_by_section(snap: Snapshot, event: str | None = None) -> dict:
    """Feature 2: the live board across sections."""
    event = _event_filter(snap, event)
    listings = snap.listings_for(event) if event else snap.listings

    by_sec = defaultdict(list)
    for l in listings:
        by_sec[l.section].append(l)

    sections = []
    for sec, rows in by_sec.items():
        prices = [r.price for r in rows]
        vs = [r.view_score for r in rows if r.view_score is not None]
        sections.append(
            {
                "section": sec,
                "tier": venue.tier(sec),
                "listings": len(rows),
                "tickets_available": sum(r.qty for r in rows),
                "price": describe(prices),
                "get_in": round(min(prices), 2),
                "view_score": round(sum(vs) / len(vs), 2) if vs else None,
                "rows_listed": sorted({r.row for r in rows if r.row}),
            }
        )
    sections.sort(key=lambda d: -(d["price"]["median"] or 0))

    all_prices = [l.price for l in listings]
    # Log-spaced buckets: asks run from $10 to several thousand, so linear bins
    # would put almost everything in the first bar.
    edges = [0, 50, 100, 150, 200, 300, 400, 600, 900, 1500, 3000, 10 ** 9]
    hist = []
    for i in range(len(edges) - 1):
        lo, hi = edges[i], edges[i + 1]
        n = sum(1 for x in all_prices if lo <= x < hi)
        hist.append(
            {"low": lo, "high": None if hi >= 10 ** 9 else hi, "count": n}
        )

    return {
        "scope": event or "all",
        "totals": {
            "listings": len(listings),
            "tickets_available": sum(l.qty for l in listings),
            "sections_listed": len(by_sec),
            "price": describe(all_prices),
            "get_in": round(min(all_prices), 2) if all_prices else None,
        },
        "sections": sections,
        "histogram": hist,
    }


def section_detail(snap: Snapshot, section: str, event: str | None = None) -> dict:
    """Row-by-row board and sale history for one section."""
    tier = venue.require_tier(section)
    event = _event_filter(snap, event)
    listings = [
        l for l in (snap.listings_for(event, section) if event
                    else [x for x in snap.listings if x.section == section])
    ]
    sales = (
        snap.sales_for(event, section) if event
        else snap.sales_for(section=section)
    )

    by_row = defaultdict(lambda: {"listings": [], "sales": [], "net": []})
    for l in listings:
        by_row[l.row or "?"]["listings"].append(l.price)
    for s in sales:
        if s.net is not None:
            by_row[s.row or "?"]["net"].append(s.net)
    for s in sales:
        by_row[s.row or "?"]["sales"].append(s.price)

    rows = []
    for row, b in by_row.items():
        rows.append(
            {
                "row": row,
                "row_ordinal": next(
                    (l.row_ord for l in listings if (l.row or "?") == row), None
                ),
                "ask": describe(b["listings"]),
                "sold": describe(b["sales"]),
                "net": describe(b["net"]),
            }
        )
    rows.sort(key=lambda r: (r["row_ordinal"] is None, r["row_ordinal"] or 0, r["row"]))

    return {
        "section": section,
        "tier": tier,
        "scope": event or "all",
        "ask": describe([l.price for l in listings]),
        "sold": describe([s.price for s in sales]),
        "rows": rows,
    }


def venue_map(snap: Snapshot) -> dict:
    """Static geometry plus the section list, for drawing the bowl."""
    present = snap.sections()
    return {
        "layout": venue.layout(),
        "court": venue.court(),
        "canvas": venue.canvas(),
        "sections_present": present,
    }
