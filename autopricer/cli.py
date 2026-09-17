"""Command line entry point: ``python3 -m autopricer <command>``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import config, views
from .data import load
from .model import PricingModel

REFRESH_DOC = Path(__file__).resolve().parent.parent / "scripts" / "REFRESH.md"


def cmd_serve(args) -> int:
    from .server import serve

    serve(host=args.host, port=args.port)
    return 0


def cmd_price(args) -> int:
    snap = load()
    m = PricingModel(snap)
    q = m.recommend(
        event=args.event, section=args.section, row=args.row,
        qty=args.qty, strategy=args.strategy,
    )
    if args.json:
        print(json.dumps(q, indent=2, default=str))
        return 0

    r, d, rq = q["recommendation"], q["drivers"], q["request"]
    pos = r["position"]
    print(f"\n  {rq['event_label']}  ({rq['days_to_event']} days out)")
    print(f"  Section {rq['section']}"
          + (f", row {rq['row']}" if rq["row"] else "")
          + f"  x{rq['qty']}   [{rq['tier']} bowl]\n")
    print(f"  LIST AT   ${r['price']:,.2f} / ticket        ({rq['strategy']}, "
          f"{r['confidence']} confidence)")
    print(f"  Expected to clear around ${r['expected_clear']:,.2f}")
    print(f"  Would be {pos['rank']} cheapest of {pos['of_total']} in the section\n")
    print("  Strategy ladder")
    for k, v in r["ladder"].items():
        mark = "*" if k == rq["strategy"] else " "
        print(f"    {mark} {k:<11} ${v:,.2f}")
    print("\n  How it was built")
    print(f"    game median ask       ${d['event_ask_level']:,.2f}")
    print(f"    x section index       x{d['section_index']:.2f} "
          f"({d['section_index_support_games']} games of support)")
    print(f"    x row factor          x{d['row_factor']:.2f}")
    print(f"    = index model ask     ${d['model_ask']:,.2f}")
    mk = d["market_ask"]
    print(f"    live board median     "
          + (f"${mk:,.2f}" if mk is not None else "—")
          + f"  ({q['comps']['adjusted']['n']} comps, {q['comps']['basis']})")
    print(f"    = blended ask         ${d['blended_ask']:,.2f} "
          f"(board weight {d['board_weight']:.0%})")
    sm = d["sale_comp_median"]
    print(f"    comparable sales      "
          + (f"${sm:,.2f}" if sm is not None else "—")
          + f"  ({d['sale_comp_basis']}, n={d['sale_comp_count']})")
    print(f"    x clearing ratio      x{d['clearing_ratio']:.2f}")
    if q["caveats"]:
        print("\n  Caveats")
        for c in q["caveats"]:
            print(f"    ! {c}")
    print()
    return 0


def cmd_summary(args) -> int:
    snap = load()
    m = PricingModel(snap)
    if args.json:
        print(json.dumps(m.summary(), indent=2, default=str))
        return 0
    s = m.summary()
    print(f"\n  {config.TEAM} {config.SEASON} @ {config.VENUE}")
    print(f"  {len(snap.events)} games | {len(snap.listings):,} live listings "
          f"| {len(snap.sales):,} sales")
    if snap.dropped:
        print(f"  dropped on load: {snap.dropped}")
    print(f"\n  clearing ratio  x{s['clearing_ratio']:.3f} "
          f"(n={s['clearing_ratio_samples']})")
    for t, v in s["clearing_ratio_by_tier"].items():
        print(f"      {t:<8} x{v:.3f}")
    print("\n  section index, top 10")
    for sec, v in list(s["section_index"].items())[:10]:
        print(f"      {sec:<5} x{v['index']:<6.2f} {v['tier']:<6} "
              f"{v['games']} games")
    print()
    return 0


def cmd_events(args) -> int:
    snap = load()
    rows = views.event_overview(snap)
    print(f"\n  {'date':<11} {'opponent':<24} {'days':>5} {'listings':>9} "
          f"{'median ask':>11} {'sold':>6} {'gross':>10}")
    print("  " + "-" * 82)
    for r in rows:
        print(f"  {r['event']:<11} {r['opponent'][:24]:<24} {r['days_to_event']:>5} "
              f"{r['listings']:>9,} "
              + (f"{r['ask_median']:>11,.0f}" if r["ask_median"] else f"{'—':>11}")
              + f" {r['tickets_sold']:>6,} {r['gross']:>10,.0f}")
    print()
    return 0


def cmd_refresh(args) -> int:
    if REFRESH_DOC.exists():
        print(REFRESH_DOC.read_text())
    else:  # pragma: no cover
        print("scripts/REFRESH.md is missing.", file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="autopricer",
        description=f"Ticket pricing for {config.TEAM} {config.SEASON} "
                    f"home games at {config.VENUE}.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="run the dashboard and API")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.set_defaults(func=cmd_serve)

    s = sub.add_parser("price", help="quote one ticket")
    s.add_argument("event", help="game date, e.g. 2026-12-25")
    s.add_argument("section", help="section number, e.g. 112")
    s.add_argument("row", nargs="?", default=None, help="row, e.g. C")
    s.add_argument("--qty", type=int, default=2)
    s.add_argument("--strategy", default=None,
                   choices=config.PARAMS.strategy_names)
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_price)

    s = sub.add_parser("summary", help="show what the model learned")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_summary)

    s = sub.add_parser("events", help="list the games with board and sales depth")
    s.set_defaults(func=cmd_events)

    s = sub.add_parser("refresh", help="how to re-extract the snapshot")
    s.set_defaults(func=cmd_refresh)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
