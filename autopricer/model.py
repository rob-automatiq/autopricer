"""The pricing engine.

Three things are estimated from the snapshot, in order:

1. **A section index.** Within one game, each section's median ask is divided
   by that game's overall median ask. Taking the median of those ratios across
   all 35 games gives a section's standing quality, with the game-to-game
   swing in demand divided out. Section 112 lands near 3x the board median,
   section 222 near 0.45x.

2. **A row curve.** Each ask is divided by the median ask of its own
   (game, section) cell, which removes both the game and the section and
   leaves the row. Pooling those ratios by tier and row depth gives the price
   gradient from row A to row Z.

3. **A clearing ratio.** Every realised sale is compared with the current
   median ask in the same game and section. The median of that ratio -- about
   0.75 on this snapshot -- is how far below the asking board seats actually
   trade.

A recommendation then combines the live board in the target section (adjusted
to the target row) with the index model, and floors the result at what
comparable seats actually clear for.

One honest caveat, surfaced in the API as ``caveats``: the listing snapshot is
a single day's board, while the sales span several weeks before it. The
clearing ratio therefore mixes a genuine ask-to-clear spread with whatever
price drift happened over that window. It is a directional calibration, not a
clean instantaneous measurement.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from . import venue
from .config import PARAMS, ModelParams
from .data import Listing, Sale, Snapshot
from .normalize import row_ordinal
from .stats import clamp, describe, median, pct


def _isotonic_decreasing(
    values: list[float], weights: list[float]
) -> list[float]:
    """Pool-adjacent-violators fit of a non-increasing sequence.

    Repeatedly finds a pair where the sequence rises, replaces both with their
    weight-averaged value, and repeats until the sequence is non-increasing.
    This is the weighted least-squares solution under a monotone constraint.
    """
    blocks = [[v, w] for v, w in zip(values, weights)]  # [mean, weight]
    i = 0
    while i < len(blocks) - 1:
        if blocks[i][0] < blocks[i + 1][0] - 1e-12:
            v0, w0 = blocks[i]
            v1, w1 = blocks[i + 1]
            total = w0 + w1
            merged = [(v0 * w0 + v1 * w1) / total if total else v0, total]
            blocks[i : i + 2] = [merged]
            # Merging can break monotonicity with the block before it.
            if i > 0:
                i -= 1
        else:
            i += 1

    out: list[float] = []
    # Re-expand blocks back over the original positions.
    idx = 0
    for mean, weight in blocks:
        span = 0
        acc = 0.0
        while idx + span < len(weights) and acc < weight - 1e-9:
            acc += weights[idx + span]
            span += 1
        out.extend([mean] * max(span, 1))
        idx += max(span, 1)
    return out[: len(values)]


def _weighted_median(values: list[float], weights: list[float]) -> float | None:
    if not values:
        return None
    pairs = sorted(zip(values, weights))
    total = sum(weights)
    if total <= 0:
        return median(values)
    acc = 0.0
    for v, w in pairs:
        acc += w
        if acc >= total / 2:
            return v
    return pairs[-1][0]


@dataclass
class Comp:
    """A listing re-priced as if it were the seat being quoted."""

    price: float          # adjusted to the target row (and section, if widened)
    raw_price: float      # what it is actually listed at
    section: str
    row: str | None
    qty: int
    same_section: bool

    def as_dict(self) -> dict:
        return {
            "adjusted": round(self.price, 2),
            "listed": round(self.raw_price, 2),
            "section": self.section,
            "row": self.row,
            "qty": self.qty,
            "same_section": self.same_section,
        }


class PricingModel:
    def __init__(self, snap: Snapshot, params: ModelParams = PARAMS) -> None:
        self.snap = snap
        self.p = params
        self._build()

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        snap, p = self.snap, self.p

        # (1) Event level: the median ask across a game's whole board.
        self.event_level: dict[str, float] = {}
        for ev in snap.event_keys():
            prices = [l.price for l in snap.listings_for(ev)]
            lvl = median(prices)
            if lvl:
                self.event_level[ev] = lvl

        # Cell medians, reused by the surfaces below. Two versions: a strict
        # one for the row curve and clearing ratio, and a permissive one for
        # the section index (see ``min_index_cell_listings``).
        self._cell_median: dict[tuple, float] = {}
        self._cell_median_loose: dict[tuple, float] = {}
        cells = defaultdict(list)
        for l in snap.listings:
            cells[(l.event_date, l.section)].append(l.price)
        for key, prices in cells.items():
            med = median(prices)
            if med is None:
                continue
            if len(prices) >= p.min_index_cell_listings:
                self._cell_median_loose[key] = med
            if len(prices) >= p.min_cell_listings:
                self._cell_median[key] = med

        # (2) Section index: median across games of (cell median / event level).
        ratios: dict[str, list[float]] = defaultdict(list)
        for (ev, sec), cell_med in self._cell_median_loose.items():
            lvl = self.event_level.get(ev)
            if lvl:
                ratios[sec].append(cell_med / lvl)

        self.section_index: dict[str, float] = {}
        self.section_index_support: dict[str, int] = {}
        tier_pool: dict[str, list[float]] = defaultdict(list)
        for sec, rs in ratios.items():
            self.section_index_support[sec] = len(rs)
            if len(rs) >= p.min_index_cells:
                idx = median(rs)
                self.section_index[sec] = idx  # type: ignore[assignment]
                t = venue.tier(sec)
                if t:
                    tier_pool[t].append(idx)  # type: ignore[arg-type]

        # Thin sections fall back to their tier's typical index.
        self.tier_index: dict[str, float] = {
            t: median(v) for t, v in tier_pool.items() if v  # type: ignore[misc]
        }
        for sec, rs in ratios.items():
            if sec not in self.section_index:
                t = venue.tier(sec)
                fallback = self.tier_index.get(t or "", None)
                self.section_index[sec] = fallback if fallback else (median(rs) or 1.0)

        # (3) Row curve: ask / own-cell median, pooled by (tier, row depth).
        node: dict[tuple, list[float]] = defaultdict(list)
        for l in snap.listings:
            if l.row_ord is None:
                continue
            cell_med = self._cell_median.get((l.event_date, l.section))
            if not cell_med:
                continue
            node[(l.tier, l.row_ord)].append(l.price / cell_med)

        self._row_raw = {k: v for k, v in node.items()}
        self.row_curve: dict[tuple, float] = {}
        self.row_support: dict[tuple, int] = {}
        w = p.row_smooth_window
        for t in {t for (t, _) in node}:
            ords = sorted(o for (tt, o) in node if tt == t)
            fitted: list[tuple[int, float, float]] = []  # (ordinal, factor, weight)
            for o in ords:
                pooled: list[float] = []
                for d in range(-w, w + 1):
                    pooled.extend(node.get((t, o + d), []))
                self.row_support[(t, o)] = len(node.get((t, o), []))
                if len(pooled) < p.min_row_sample:
                    continue
                raw = median(pooled)
                if not raw:
                    continue
                # Shrink toward neutral by sample size before anything else, so
                # thin nodes cannot drive the curve.
                n_eff = len(pooled)
                shrunk = (n_eff * raw + p.row_shrink_k * 1.0) / (n_eff + p.row_shrink_k)
                fitted.append((o, shrunk, float(n_eff)))

            if not fitted:
                continue
            if p.row_monotone:
                factors = _isotonic_decreasing(
                    [f for _, f, _ in fitted], [wt for _, _, wt in fitted]
                )
            else:
                factors = [f for _, f, _ in fitted]

            # Re-centre so the typical seat in a tier sits at 1.0. The section
            # index is built from cell *medians*, so the row curve has to be
            # neutral at the median row or the two would double-count.
            weights = [wt for _, _, wt in fitted]
            centre = _weighted_median(factors, weights) or 1.0
            for (o, _, _), f in zip(fitted, factors):
                self.row_curve[(t, o)] = clamp(f / centre, *p.row_factor_bounds)

        # (4) Clearing ratio: realised sale vs current median ask, same cell.
        self._clear_samples: list[float] = []
        tier_clear: dict[str, list[float]] = defaultdict(list)
        for s in snap.sales:
            cell_med = self._cell_median.get((s.event_date, s.section))
            if not cell_med:
                continue
            r = s.price / cell_med
            # Guard against label collisions and data errors producing absurd
            # ratios; 0.1x-4x still admits everything economically plausible.
            if 0.1 <= r <= 4.0:
                self._clear_samples.append(r)
                tier_clear[s.tier].append(r)
        self.clear_ratio: float = median(self._clear_samples) or 0.75
        self.tier_clear_ratio: dict[str, float] = {
            t: median(v) for t, v in tier_clear.items() if len(v) >= 8  # type: ignore[misc]
        }

        # (5) Games with no live board at all. One game in the current snapshot
        # (Philadelphia, 2027-03-13) has 45 recorded sales and zero active
        # listings, so there is real signal but nothing to anchor the index
        # model to. Recover a level by inverting the pricing identity on those
        # sales: price = level x index x row_factor x clearing_ratio, so
        # level = price / (index x row_factor x clearing_ratio). Runs last
        # because it needs all three surfaces above.
        self.event_level_estimated: set[str] = set()
        fallback_level = median(list(self.event_level.values()))
        for ev in snap.event_keys():
            if ev in self.event_level:
                continue
            implied = []
            for s in snap.sales_for(ev):
                denom = (
                    self.clearing_ratio_for(s.tier)
                    * self.index_of(s.section)
                    * self.row_factor(s.tier, s.row_ord)
                )
                if denom > 0:
                    implied.append(s.price / denom)
            lvl = median(implied) if implied else fallback_level
            if lvl:
                self.event_level[ev] = lvl
                self.event_level_estimated.add(ev)

    # -------------------------------------------------------------- accessors
    def row_factor(self, tier: str | None, row_ord: int | None) -> float:
        """Price multiplier for a row depth, relative to its section median."""
        if tier is None or row_ord is None:
            return 1.0
        f = self.row_curve.get((tier, row_ord))
        if f is not None:
            return f
        # Nearest node with support, so an unseen row still gets a sensible
        # gradient instead of silently collapsing to the section median.
        known = sorted(o for (t, o) in self.row_curve if t == tier)
        if not known:
            return 1.0
        nearest = min(known, key=lambda o: abs(o - row_ord))
        return self.row_curve[(tier, nearest)]

    def index_of(self, section: str) -> float:
        if section in self.section_index:
            return self.section_index[section]
        t = venue.tier(section)
        return self.tier_index.get(t or "", 1.0)

    def clearing_ratio_for(self, tier: str | None) -> float:
        if tier and tier in self.tier_clear_ratio:
            return self.tier_clear_ratio[tier]
        return self.clear_ratio

    # ------------------------------------------------------------- comp build
    def _comp_set(
        self, event: str, section: str, target_ord: int | None
    ) -> tuple[list[Comp], str, list[str]]:
        """Row-adjusted asks comparable to the requested seat."""
        tier = venue.tier(section)
        rf_target = self.row_factor(tier, target_ord)
        notes: list[str] = []

        def adjust(l: Listing, section_scale: float = 1.0) -> Comp:
            rf_l = self.row_factor(l.tier, l.row_ord)
            adj = l.price * section_scale * (rf_target / rf_l if rf_l else 1.0)
            return Comp(
                price=adj,
                raw_price=l.price,
                section=l.section,
                row=l.row,
                qty=l.qty,
                same_section=(l.section == section),
            )

        direct = self.snap.listings_for(event, section)
        comps = [adjust(l) for l in direct]
        if len(comps) >= self.p.min_comps:
            return comps, "section", notes

        # Widen to same-tier sections of similar standing quality, scaling each
        # ask by the ratio of section indices.
        idx_target = self.index_of(section)
        neighbours: list[tuple[float, str]] = []
        for sec in self.snap.sections():
            if sec == section or venue.tier(sec) != tier:
                continue
            idx = self.index_of(sec)
            if not idx or not idx_target:
                continue
            rel = abs(idx - idx_target) / idx_target
            if rel <= self.p.neighbour_index_tol:
                neighbours.append((rel, sec))
        neighbours.sort()

        for _, sec in neighbours:
            if len(comps) >= self.p.widen_target:
                break
            scale = idx_target / self.index_of(sec)
            comps.extend(adjust(l, scale) for l in self.snap.listings_for(event, sec))

        if len(direct) < self.p.min_comps:
            used = sorted({c.section for c in comps if not c.same_section})
            if used:
                notes.append(
                    f"Only {len(direct)} live listing(s) in section {section}; "
                    f"comps widened to {len(used)} similar section(s) "
                    f"({', '.join(used)}), price-scaled by section index."
                )
            else:
                notes.append(
                    f"Only {len(direct)} live listing(s) in section {section} and no "
                    "comparable sections on the board; leaning on the index model."
                )
        return comps, ("section" if len(direct) >= self.p.min_comps else "widened"), notes

    def _sale_comps(
        self, event: str, section: str, target_ord: int | None
    ) -> tuple[list[float], str, int]:
        """Realised sale prices normalised to the target seat and game.

        Tried in order: this game and section, then the same section at other
        games (scaled by the ratio of game levels), then the same tier (scaled
        by game level and section index).
        """
        tier = venue.tier(section)
        rf_target = self.row_factor(tier, target_ord)
        lvl_target = self.event_level.get(event)

        def row_adj(s: Sale) -> float:
            rf_s = self.row_factor(s.tier, s.row_ord)
            return rf_target / rf_s if rf_s else 1.0

        same = self.snap.sales_for(event, section)
        if same:
            return [s.price * row_adj(s) for s in same], "event_section", len(same)

        if lvl_target:
            across = self.snap.sales_for(section=section)
            out = []
            for s in across:
                lvl = self.event_level.get(s.event_date)
                if lvl:
                    out.append(s.price * row_adj(s) * (lvl_target / lvl))
            if out:
                return out, "section_all_games", len(out)

            idx_target = self.index_of(section)
            out = []
            for s in self.snap.sales:
                if s.tier != tier:
                    continue
                lvl = self.event_level.get(s.event_date)
                idx_s = self.index_of(s.section)
                if lvl and idx_s:
                    out.append(
                        s.price * row_adj(s) * (lvl_target / lvl) * (idx_target / idx_s)
                    )
            if out:
                return out, "tier_all_games", len(out)

        return [], "none", 0

    # ------------------------------------------------------------- the quote
    def recommend(
        self,
        event: str,
        section: str,
        row: str | None = None,
        qty: int = 2,
        strategy: str | None = None,
    ) -> dict:
        strategy = strategy or self.p.default_strategy
        name, target_pct, floor_at_clear = self.p.strategy(strategy)

        ev = self.snap.event(event)
        if ev is None:
            raise ValueError(f"unknown event {event!r}")
        tier = venue.tier(section)
        if tier is None:
            raise ValueError(f"{section!r} is not a Target Center seat section")

        target_ord = row_ordinal(row)
        rf_target = self.row_factor(tier, target_ord)
        idx = self.index_of(section)
        lvl = self.event_level.get(event)

        caveats: list[str] = []
        if event in self.event_level_estimated:
            caveats.append(
                "This game has no active listings in the snapshot, so there is no "
                "board to price against. The quote is built from realised sales "
                "for comparable seats and the game level implied by them — treat "
                "it as a starting point, not a market read."
            )
        if row and target_ord is None:
            caveats.append(
                f"Row {row!r} has no readable depth, so the quote is for the "
                "section as a whole with no row adjustment."
            )

        comps, basis, notes = self._comp_set(event, section, target_ord)
        caveats.extend(notes)
        adj = sorted(c.price for c in comps)
        direct = self.snap.listings_for(event, section)

        # Two independent estimates of the right ask, then shrink between them.
        market_ask = median(adj)
        model_ask = (lvl * idx * rf_target) if lvl else None
        n = len(adj)
        if market_ask is not None and model_ask is not None:
            w = n / (n + self.p.comp_blend_k)
            blended_ask = w * market_ask + (1 - w) * model_ask
        else:
            blended_ask = market_ask if market_ask is not None else model_ask
            w = 1.0 if market_ask is not None else 0.0
        if blended_ask is None:
            raise ValueError(
                f"no listings at all for {event}; cannot price against an empty board"
            )

        # Expected clearing price: realised comparable sales, shrunk toward the
        # ask-derived estimate.
        clear_ratio = self.clearing_ratio_for(tier)
        clear_from_asks = blended_ask * clear_ratio
        sale_vals, sale_basis, n_sales = self._sale_comps(event, section, target_ord)
        sale_med = median(sale_vals)
        if sale_med is not None:
            ws = n_sales / (n_sales + self.p.sale_blend_k)
            expected_clear = ws * sale_med + (1 - ws) * clear_from_asks
        else:
            ws = 0.0
            expected_clear = clear_from_asks

        # Price each strategy through the same rule, so the quoted band is
        # exactly the aggressive-to-patient spread and always contains the
        # recommendation.
        ceiling = pct(adj, self.p.max_comp_percentile)

        def price_at(target_pct: float, floor_at_clear: bool) -> float:
            t = pct(adj, target_pct)
            if t is None:
                t = blended_ask
            if floor_at_clear:
                t = max(t, expected_clear)
            if ceiling is not None:
                # Never priced off the back of the board -- except that we also
                # never knowingly recommend listing below the clearing price.
                t = min(t, max(ceiling, expected_clear))
            return round(t, 2)

        ladder = {
            s_name: price_at(s_pct, s_floor)
            for s_name, s_pct, s_floor in self.p.strategies
        }
        price = ladder[name]
        band_lo = min(ladder.values())
        band_hi = max(ladder.values())

        if ceiling is not None and price > ceiling + 0.01:
            caveats.append(
                f"The recommendation sits above the {int(self.p.max_comp_percentile * 100)}th "
                f"percentile of comparable asks (${ceiling:,.2f}) because comparable seats "
                f"have been clearing higher (${expected_clear:,.2f}). Expect a slower sale."
            )

        # Where this lands among what a buyer actually sees in the section.
        listed = sorted(l.price for l in direct)
        cheaper = sum(1 for x in listed if x < price)

        if len(direct) >= 8 and n_sales >= 3:
            confidence = "high"
        elif len(direct) >= self.p.min_comps or n_sales >= 3:
            confidence = "medium"
        else:
            confidence = "low"

        days_out = (ev.event_date - dt.date.today()).days

        return {
            "request": {
                "event": event,
                "event_label": ev.label,
                "opponent": ev.opponent,
                "game_type": ev.game_type,
                "days_to_event": days_out,
                "section": section,
                "row": row,
                "row_ordinal": target_ord,
                "tier": tier,
                "qty": qty,
                "strategy": name,
            },
            "recommendation": {
                "price": price,
                "range_low": round(band_lo, 2) if band_lo is not None else None,
                "range_high": round(band_hi, 2) if band_hi is not None else None,
                "expected_clear": round(expected_clear, 2),
                "confidence": confidence,
                "ladder": ladder,
                "position": {
                    "cheaper_in_section": cheaper,
                    "listings_in_section": len(listed),
                    # Rank once this listing joins the board, so the
                    # denominator counts it too.
                    "rank": cheaper + 1,
                    "of_total": len(listed) + 1,
                },
            },
            "drivers": {
                "event_ask_level": round(lvl, 2) if lvl else None,
                "section_index": round(idx, 4),
                "section_index_support_games": self.section_index_support.get(section, 0),
                "row_factor": round(rf_target, 4),
                "row_factor_support": self.row_support.get((tier, target_ord or -1), 0),
                "market_ask": round(market_ask, 2) if market_ask is not None else None,
                "model_ask": round(model_ask, 2) if model_ask is not None else None,
                "blended_ask": round(blended_ask, 2),
                "board_weight": round(w, 3),
                "clearing_ratio": round(clear_ratio, 4),
                "sale_comp_basis": sale_basis,
                "sale_comp_count": n_sales,
                "sale_comp_median": round(sale_med, 2) if sale_med is not None else None,
                "sale_weight": round(ws, 3),
            },
            "comps": {
                "basis": basis,
                "adjusted": describe(adj),
                "listed_in_section": describe(listed),
                "closest": [
                    c.as_dict()
                    for c in sorted(comps, key=lambda c: abs(c.price - price))[:12]
                ],
            },
            "sales_used": [
                {
                    "event": s.event_date,
                    "section": s.section,
                    "row": s.row,
                    "qty": s.qty,
                    "price": round(s.price, 2),
                    "net": round(s.net, 2) if s.net is not None else None,
                    "marketplace": s.marketplace,
                    "invoice_date": s.invoice_date.isoformat() if s.invoice_date else None,
                }
                for s in self._sales_detail(event, section, sale_basis)[:12]
            ],
            "caveats": caveats,
        }

    def _sales_detail(self, event: str, section: str, basis: str) -> list[Sale]:
        if basis == "event_section":
            return self.snap.sales_for(event, section)
        if basis == "section_all_games":
            return sorted(
                self.snap.sales_for(section=section),
                key=lambda s: s.invoice_date or dt.date.min,
                reverse=True,
            )
        if basis == "tier_all_games":
            tier = venue.tier(section)
            return sorted(
                (s for s in self.snap.sales if s.tier == tier),
                key=lambda s: s.invoice_date or dt.date.min,
                reverse=True,
            )
        return []

    # ------------------------------------------------------------ diagnostics
    def summary(self) -> dict:
        """What the fitted model looks like, for the /api/model endpoint."""
        rows: dict[str, list[dict]] = {}
        for (tier, o), f in sorted(self.row_curve.items()):
            rows.setdefault(tier, []).append(
                {"row_ordinal": o, "factor": round(f, 4),
                 "n": self.row_support.get((tier, o), 0)}
            )
        return {
            "clearing_ratio": round(self.clear_ratio, 4),
            "clearing_ratio_samples": len(self._clear_samples),
            "clearing_ratio_by_tier": {
                t: round(v, 4) for t, v in self.tier_clear_ratio.items()
            },
            "tier_index": {t: round(v, 4) for t, v in self.tier_index.items()},
            "section_index": {
                s: {
                    "index": round(v, 4),
                    "games": self.section_index_support.get(s, 0),
                    "tier": venue.tier(s),
                }
                for s, v in sorted(self.section_index.items(), key=lambda kv: -kv[1])
            },
            "row_curve": rows,
            "event_ask_level": {
                k: round(v, 2) for k, v in sorted(self.event_level.items())
            },
            "event_level_estimated": sorted(self.event_level_estimated),
        }
