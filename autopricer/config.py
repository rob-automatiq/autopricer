"""Tunable parameters for the pricing model.

Every number here is a modelling choice, not a fact from the lake. They are
gathered in one place so they can be argued about and changed without reading
the engine.
"""

from __future__ import annotations

from dataclasses import dataclass

VENUE = "Target Center"
TEAM = "Minnesota Timberwolves"
SEASON = "2026-27"


@dataclass(frozen=True)
class ModelParams:
    # --- building the section / row surfaces -----------------------------
    #: Listings needed in one (event, section) cell before it contributes to
    #: the row curve or the clearing ratio. A one-listing cell has a median
    #: equal to its only ask, so every row ratio in it would be exactly 1.0 --
    #: that is a degenerate observation and would bias the curve to neutral.
    min_cell_listings: int = 2
    #: The section index tolerates one-listing cells: a single ask is still an
    #: ask, and the index is a median across up to 35 games. Requiring two
    #: would silently drop the courtside sections, which are usually listed
    #: one at a time, and leave them with no index at all.
    min_index_cell_listings: int = 1
    #: Cells needed before a section gets its own index rather than inheriting
    #: its tier's median.
    min_index_cells: int = 3
    #: Listings needed at a (tier, row) node before its factor is trusted.
    min_row_sample: int = 8
    #: Half-width, in rows, of the smoothing window on the row curve.
    row_smooth_window: int = 1
    #: Shrinkage toward 1.0 for a row node, so a node backed by 5 asks barely
    #: moves off neutral while one backed by 500 is taken at face value.
    row_shrink_k: float = 25.0
    #: Enforce that a row is worth no less than a row behind it. Within one
    #: bowl tier, closer to the floor is better -- a raw median that says
    #: otherwise is sampling noise, not a price signal.
    row_monotone: bool = True
    #: How far a row factor is allowed to stray from 1.0, to stop a thin node
    #: with one silly ask from distorting a recommendation.
    row_factor_bounds: tuple[float, float] = (0.45, 2.60)

    # --- assembling a comp set -------------------------------------------
    #: Direct comps below which the comp set is widened to neighbouring
    #: sections of similar quality.
    min_comps: int = 3
    #: A neighbouring section is comparable when its section index is within
    #: this fraction of the target's.
    neighbour_index_tol: float = 0.18
    #: Comps to aim for once widening.
    widen_target: int = 12

    # --- blending ---------------------------------------------------------
    #: Shrinkage constant: the observed board gets weight n/(n+k) against the
    #: index model, so a two-listing section leans on the model and a
    #: forty-listing section does not.
    comp_blend_k: float = 5.0
    #: Same idea for blending realised sales against the ask-derived estimate.
    sale_blend_k: float = 3.0

    # --- strategies -------------------------------------------------------
    #: Percentile of the row-adjusted comp set each strategy aims for, and
    #: whether the result is floored at the expected clearing price.
    strategies: tuple = (
        ("aggressive", 0.10, False),
        ("balanced", 0.35, True),
        ("patient", 0.65, True),
    )
    default_strategy: str = "balanced"
    #: A recommendation is never pushed above this percentile of the comp set;
    #: above it the listing is invisible behind cheaper identical seats.
    max_comp_percentile: float = 0.85

    def strategy(self, name: str) -> tuple[str, float, bool]:
        for s in self.strategies:
            if s[0] == name:
                return s
        raise ValueError(
            f"unknown strategy {name!r}; expected one of "
            f"{[s[0] for s in self.strategies]}"
        )

    @property
    def strategy_names(self) -> list[str]:
        return [s[0] for s in self.strategies]


PARAMS = ModelParams()
