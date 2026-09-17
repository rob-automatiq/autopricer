"""Loading the snapshot extracted from the data lake.

The pricing app has no ClickHouse credentials of its own -- the lake is reached
through the Datalake MCP server, which only an agent session can call. So the
extracts in ``data/raw/`` are a committed snapshot, and ``autopricer/sql/``
holds the exact queries that produced them. See ``scripts/REFRESH.md``.
"""

from __future__ import annotations

import csv
import datetime as dt
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from . import venue
from .normalize import row_key, row_ordinal, section_key

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"


def _f(v: str | None) -> float | None:
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _i(v: str | None) -> int | None:
    f = _f(v)
    return int(f) if f is not None else None


def _date(v: str | None) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(v).strip())
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class Event:
    event_date: dt.date
    opponent: str
    label: str
    vs_xid: str
    game_type: str

    @property
    def key(self) -> str:
        return self.event_date.isoformat()


@dataclass(frozen=True)
class Listing:
    """One active ask on the VividSeats board as of the snapshot date."""

    event_date: str
    section: str
    row: str | None
    row_ord: int | None
    price: float
    qty: int
    view_score: float | None
    tier: str


@dataclass(frozen=True)
class Sale:
    """One realised sale, priced per ticket."""

    event_date: str
    section: str
    row: str | None
    row_ord: int | None
    qty: int
    price: float
    cost: float
    invoice_date: dt.date | None
    sale_type: str
    tier: str

    @property
    def gross(self) -> float:
        return self.price * self.qty

    @property
    def margin(self) -> float | None:
        """Per-ticket margin, or ``None`` when cost was not recorded.

        A recorded cost of exactly 0 means "not captured by this POS", not a
        free ticket -- roughly half the rows are like that -- so it is treated
        as unknown rather than as 100% margin.
        """
        if self.cost <= 0:
            return None
        return self.price - self.cost


@dataclass
class Snapshot:
    events: list[Event]
    listings: list[Listing]
    sales: list[Sale]
    dropped: dict[str, int] = field(default_factory=dict)

    # --- indices, built once on load -------------------------------------
    _by_event: dict[str, list[Listing]] = field(default_factory=dict, repr=False)
    _by_event_section: dict[tuple, list[Listing]] = field(default_factory=dict, repr=False)
    _sales_by_event: dict[str, list[Sale]] = field(default_factory=dict, repr=False)
    _sales_by_event_section: dict[tuple, list[Sale]] = field(default_factory=dict, repr=False)
    _sales_by_section: dict[str, list[Sale]] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        by_event = defaultdict(list)
        by_es = defaultdict(list)
        for l in self.listings:
            by_event[l.event_date].append(l)
            by_es[(l.event_date, l.section)].append(l)
        self._by_event = dict(by_event)
        self._by_event_section = dict(by_es)

        s_ev, s_es, s_sec = defaultdict(list), defaultdict(list), defaultdict(list)
        for s in self.sales:
            s_ev[s.event_date].append(s)
            s_es[(s.event_date, s.section)].append(s)
            s_sec[s.section].append(s)
        self._sales_by_event = dict(s_ev)
        self._sales_by_event_section = dict(s_es)
        self._sales_by_section = dict(s_sec)

    # --- accessors --------------------------------------------------------
    def event(self, key: str) -> Event | None:
        return next((e for e in self.events if e.key == key), None)

    def event_keys(self) -> list[str]:
        return [e.key for e in self.events]

    def listings_for(self, event: str, section: str | None = None) -> list[Listing]:
        if section is None:
            return self._by_event.get(event, [])
        return self._by_event_section.get((event, section), [])

    def sales_for(self, event: str | None = None, section: str | None = None) -> list[Sale]:
        if event is None and section is None:
            return self.sales
        if event is None:
            return self._sales_by_section.get(section, [])  # type: ignore[arg-type]
        if section is None:
            return self._sales_by_event.get(event, [])
        return self._sales_by_event_section.get((event, section), [])

    def sections(self) -> list[str]:
        """Every section appearing on either side, in bowl order."""
        seen = {l.section for l in self.listings} | {s.section for s in self.sales}
        return sorted(seen, key=lambda s: int(s))


def load(data_dir: Path | str = DATA_DIR) -> Snapshot:
    data_dir = Path(data_dir)
    dropped: dict[str, int] = defaultdict(int)

    events: list[Event] = []
    with open(data_dir / "events.tsv", newline="") as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            d = _date(r["event_date"])
            if d is None:
                dropped["event_bad_date"] += 1
                continue
            events.append(
                Event(
                    event_date=d,
                    opponent=r["opponent"].strip(),
                    label=r["label"].strip(),
                    vs_xid=r["vs_xid"].strip(),
                    game_type=r["game_type"].strip(),
                )
            )
    events.sort(key=lambda e: e.event_date)

    listings: list[Listing] = []
    with open(data_dir / "listings.tsv", newline="") as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            sec = section_key(r["section"])
            price = _f(r["price"])
            t = venue.tier(sec)
            if sec is None or t is None:
                dropped["listing_not_a_seat_section"] += 1
                continue
            if price is None or price <= 0:
                dropped["listing_bad_price"] += 1
                continue
            listings.append(
                Listing(
                    event_date=r["event_date"],
                    section=sec,
                    row=row_key(r["row"]),
                    row_ord=row_ordinal(r["row"]),
                    price=price,
                    qty=_i(r["qty"]) or 0,
                    view_score=_f(r["view_score"]),
                    tier=t,
                )
            )

    sales: list[Sale] = []
    with open(data_dir / "sales.tsv", newline="") as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            sec = section_key(r["section"])
            price = _f(r["price"])
            qty = _i(r["qty"])
            t = venue.tier(sec)
            if sec is None or t is None:
                dropped["sale_not_a_seat_section"] += 1
                continue
            if not price or not qty or price <= 0 or qty <= 0:
                dropped["sale_bad_price_or_qty"] += 1
                continue
            sales.append(
                Sale(
                    event_date=r["event_date"],
                    section=sec,
                    row=row_key(r["row"]),
                    row_ord=row_ordinal(r["row"]),
                    qty=qty,
                    price=price,
                    cost=_f(r["cost"]) or 0.0,
                    invoice_date=_date(r["invoice_date"]),
                    sale_type=(r["sale_type"] or "").strip() or "Unspecified",
                    tier=t,
                )
            )

    known = {e.key for e in events}
    listings = [l for l in listings if l.event_date in known]
    sales = [s for s in sales if s.event_date in known]

    return Snapshot(events=events, listings=listings, sales=sales, dropped=dict(dropped))
