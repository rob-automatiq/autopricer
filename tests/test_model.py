"""Tests against the committed snapshot.

These lean on real data rather than fixtures, so a few assert on shape and
direction ("the lower bowl indexes above the upper bowl") rather than on exact
numbers, which move whenever the snapshot is refreshed.
"""

import pytest

from autopricer import venue
from autopricer.data import load
from autopricer.model import PricingModel, _isotonic_decreasing
from autopricer.stats import describe, pct


@pytest.fixture(scope="module")
def snap():
    return load()


@pytest.fixture(scope="module")
def model(snap):
    return PricingModel(snap)


# --------------------------------------------------------------- the snapshot
def test_snapshot_loads_cleanly(snap):
    assert len(snap.events) == 35
    assert len(snap.listings) > 9_000
    assert len(snap.sales) > 500
    # The only row the loader should be dropping is the "7th St." parking
    # listing; anything else means a label format changed.
    assert set(snap.dropped) <= {"listing_not_a_seat_section"}
    assert snap.dropped.get("listing_not_a_seat_section", 0) <= 2


def test_every_row_has_a_known_tier(snap):
    for l in snap.listings:
        assert l.tier in (venue.TIER_FLOOR, venue.TIER_LOWER, venue.TIER_UPPER)
    for s in snap.sales:
        assert s.tier in (venue.TIER_FLOOR, venue.TIER_LOWER, venue.TIER_UPPER)


def test_sales_and_listings_share_a_section_vocabulary(snap):
    lsec = {l.section for l in snap.listings}
    ssec = {s.section for s in snap.sales}
    # Normalisation is what makes these overlap; if it regressed the
    # intersection collapses.
    assert len(lsec & ssec) >= 55


def test_zero_cost_is_treated_as_unknown_not_as_full_margin(snap):
    zero = [s for s in snap.sales if s.cost == 0]
    assert zero, "snapshot should contain rows with no captured cost"
    assert all(s.margin is None for s in zero)
    priced = [s for s in snap.sales if s.cost > 0]
    assert all(s.margin == pytest.approx(s.price - s.cost) for s in priced)


# ------------------------------------------------------------------ the model
def test_lower_bowl_is_worth_more_than_upper(model):
    assert model.tier_index["lower"] > model.tier_index["upper"]


def test_courtside_sections_get_a_real_index(model):
    """Floor sections are listed one at a time, so a two-listing minimum used
    to leave them with no index at all and price them at the board median."""
    for sec in ("3", "6", "10"):
        assert model.index_of(sec) > 5.0, sec


def test_centre_court_outranks_a_corner(model):
    assert model.index_of("112") > model.index_of("101")
    assert model.index_of("101") > model.index_of("222")


def test_clearing_ratio_is_below_one(model):
    # Asks sit above clears; a ratio at or above 1 would mean sales printing
    # above the asking board, which would point at a join bug.
    assert 0.4 < model.clear_ratio < 1.0
    for tier, v in model.tier_clear_ratio.items():
        assert 0.4 < v < 1.0, tier


def test_row_curve_is_monotone_non_increasing(model):
    for tier in {t for (t, _) in model.row_curve}:
        nodes = sorted((o, f) for (t, o), f in model.row_curve.items() if t == tier)
        factors = [f for _, f in nodes]
        assert all(
            factors[i] >= factors[i + 1] - 1e-9 for i in range(len(factors) - 1)
        ), f"{tier} row curve rises with depth: {nodes}"


def test_front_rows_beat_back_rows_in_the_lower_bowl(model):
    assert model.row_factor("lower", 1) > model.row_factor("lower", 26)


def test_row_factor_falls_back_to_the_nearest_known_row(model):
    # Row 40 is past anything observed, so it should inherit the deepest node
    # rather than silently returning a neutral 1.0.
    assert model.row_factor("lower", 40) == pytest.approx(
        model.row_factor("lower", 26)
    )


def test_unknown_row_is_neutral(model):
    assert model.row_factor("lower", None) == 1.0
    assert model.row_factor(None, 3) == 1.0


# ------------------------------------------------------------- the isotonic fit
def test_isotonic_leaves_a_decreasing_sequence_alone():
    v = [3.0, 2.0, 1.0]
    assert _isotonic_decreasing(v, [1, 1, 1]) == pytest.approx(v)


def test_isotonic_pools_a_violation():
    out = _isotonic_decreasing([1.0, 3.0], [1.0, 1.0])
    assert out == pytest.approx([2.0, 2.0])


def test_isotonic_respects_weights():
    out = _isotonic_decreasing([1.0, 3.0], [3.0, 1.0])
    assert out == pytest.approx([1.5, 1.5])


def test_isotonic_returns_one_factor_per_input():
    vals = [1.0, 5.0, 2.0, 4.0, 3.0]
    out = _isotonic_decreasing(vals, [1.0] * 5)
    assert len(out) == len(vals)
    assert all(out[i] >= out[i + 1] - 1e-9 for i in range(len(out) - 1))


# ------------------------------------------------------------ recommendations
def test_quote_is_internally_consistent(model):
    q = model.recommend("2026-12-25", "112", "C")
    r = q["recommendation"]
    assert r["range_low"] <= r["price"] <= r["range_high"]
    assert r["price"] > 0
    assert r["expected_clear"] > 0
    assert r["confidence"] in ("low", "medium", "high")
    assert r["position"]["of_total"] == r["position"]["listings_in_section"] + 1
    assert 1 <= r["position"]["rank"] <= r["position"]["of_total"]


def test_strategy_ladder_is_ordered(model):
    q = model.recommend("2026-12-25", "112", "C")
    lad = q["recommendation"]["ladder"]
    assert lad["aggressive"] <= lad["balanced"] <= lad["patient"]


def test_strategy_changes_the_price_not_the_ladder(model):
    a = model.recommend("2026-12-25", "112", "C", strategy="aggressive")
    p = model.recommend("2026-12-25", "112", "C", strategy="patient")
    assert a["recommendation"]["ladder"] == p["recommendation"]["ladder"]
    assert a["recommendation"]["price"] <= p["recommendation"]["price"]
    assert a["recommendation"]["price"] == a["recommendation"]["ladder"]["aggressive"]


def test_front_row_quotes_above_back_row(model):
    front = model.recommend("2026-12-25", "112", "C")["recommendation"]["price"]
    back = model.recommend("2026-12-25", "112", "Z")["recommendation"]["price"]
    assert front > back


def test_better_section_quotes_higher(model):
    good = model.recommend("2026-12-25", "112", "M")["recommendation"]["price"]
    poor = model.recommend("2026-12-25", "222", "M")["recommendation"]["price"]
    assert good > poor


def test_marquee_game_quotes_above_a_quiet_one(model):
    xmas = model.recommend("2026-12-25", "112", "M")["recommendation"]["price"]
    quiet = model.recommend("2026-11-17", "112", "M")["recommendation"]["price"]
    assert xmas > quiet


def test_thin_section_is_flagged_and_widened(model):
    q = model.recommend("2026-12-25", "10", "C")
    assert q["comps"]["basis"] == "widened"
    assert q["caveats"], "a widened comp set must say so"
    assert any(not c["same_section"] for c in q["comps"]["closest"])


def test_missing_row_is_flagged_but_still_quotes(model):
    q = model.recommend("2026-12-25", "112", "TBD")
    assert q["recommendation"]["price"] > 0
    assert q["request"]["row_ordinal"] is None
    assert any("no readable depth" in c for c in q["caveats"])


def test_game_with_no_board_still_quotes_from_sales(model, snap):
    """One game in the snapshot has dozens of sales and an empty board. It has
    real signal, so it must quote — from the sales — rather than raise."""
    empty = [e.key for e in snap.events if not snap.listings_for(e.key)]
    assert empty, "snapshot no longer has a game with an empty board"
    for ev in empty:
        assert ev in model.event_level_estimated
        q = model.recommend(ev, "121", "Q")
        r = q["recommendation"]
        assert r["price"] > 0
        assert r["range_low"] <= r["price"] <= r["range_high"]
        assert q["drivers"]["market_ask"] is None
        assert q["drivers"]["board_weight"] == 0
        assert any("no active listings" in c for c in q["caveats"])


def test_estimated_level_is_in_a_plausible_range(model, snap):
    """The implied level should land inside the spread of the games that do
    have a board, not orders of magnitude away."""
    observed = [v for k, v in model.event_level.items()
                if k not in model.event_level_estimated]
    lo, hi = min(observed), max(observed)
    for ev in model.event_level_estimated:
        assert lo * 0.5 <= model.event_level[ev] <= hi * 2.0, ev


def test_rejects_bad_input(model):
    with pytest.raises(ValueError, match="unknown event"):
        model.recommend("1999-01-01", "112", "C")
    with pytest.raises(ValueError, match="not a Target Center seat section"):
        model.recommend("2026-12-25", "7th St.", "C")
    with pytest.raises(ValueError, match="unknown strategy"):
        model.recommend("2026-12-25", "112", "C", strategy="yolo")


def test_every_real_seat_quotes_without_error(model, snap):
    """Sweep every (game, section, row) that actually exists on the board."""
    seen = {(l.event_date, l.section, l.row) for l in snap.listings}
    assert len(seen) > 5_000
    for event, section, row in seen:
        q = model.recommend(event, section, row)
        r = q["recommendation"]
        assert r["price"] > 0, (event, section, row)
        assert r["range_low"] <= r["price"] <= r["range_high"], (event, section, row)
        assert r["expected_clear"] > 0, (event, section, row)


def test_every_sold_seat_quotes_without_error(model, snap):
    """Sales reach sections and rows that have no live listing at all."""
    seen = {(s.event_date, s.section, s.row) for s in snap.sales}
    for event, section, row in seen:
        r = model.recommend(event, section, row)["recommendation"]
        assert r["price"] > 0, (event, section, row)
        assert r["range_low"] <= r["price"] <= r["range_high"], (event, section, row)


# ------------------------------------------------------------------ the layout
def test_layout_covers_both_bowls_and_only_observed_floor(snap):
    lay = venue.layout(floor_sections=snap.sections())
    assert {"101", "138", "201", "240"} <= set(lay)
    floor = {s for s, v in lay.items() if v["tier"] == "floor"}
    assert floor == {"3", "6", "10"}, (
        "the floor ring should only draw sections the data actually has, "
        "since its real numbering is unknown"
    )


def test_layout_spaces_neighbours_evenly(snap):
    """Equal-angle spacing bunched tiles where the ellipse is flattest and made
    neighbouring lower-bowl labels overlap; equal arc length fixes that."""
    lay = venue.layout(floor_sections=snap.sections())
    gaps = []
    for a, b in zip(venue.LOWER_BOWL, venue.LOWER_BOWL[1:]):
        pa, pb = lay[str(a)], lay[str(b)]
        gaps.append(((pa["x"] - pb["x"]) ** 2 + (pa["y"] - pb["y"]) ** 2) ** 0.5)
    assert max(gaps) / min(gaps) < 1.15, f"uneven tile spacing: {gaps}"


def test_layout_stays_on_canvas(snap):
    for sec, p in venue.layout(floor_sections=snap.sections()).items():
        assert 0 < p["x"] < 100, sec
        assert 0 < p["y"] < 100, sec


# ------------------------------------------------------------------- the stats
def test_pct_interpolates():
    xs = [10, 20, 30, 40]
    assert pct(xs, 0) == 10
    assert pct(xs, 1) == 40
    assert pct(xs, 0.5) == pytest.approx(25)


def test_pct_handles_thin_and_empty_samples():
    assert pct([], 0.5) is None
    assert pct([7], 0.5) == 7
    assert pct([7], 0.1) == 7


def test_describe_on_empty():
    d = describe([])
    assert d["n"] == 0
    assert d["median"] is None
