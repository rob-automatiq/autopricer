"""The snapshot and the fitted model, held as one swappable bundle.

Loading the snapshot and fitting the three surfaces takes a moment and the
result is immutable, so it happens once at start-up and every request is then
answered from memory.

The shape here exists for what comes next. A ``Fit`` is a frozen bundle --
snapshot, model, and the derived views memoised against *that* bundle -- and
``AppState.reload()`` builds a whole new one and swaps the reference in a
single assignment. So a refresh can never serve a half-updated answer (sales
from the new snapshot against a model fitted on the old one), requests already
in flight keep the bundle they started with, and the memo table is discarded
with the bundle rather than having to be invalidated key by key. That is the
seam a live data-lake refresh, a scheduled re-extract, or a what-if overlay
plugs into.
"""

from __future__ import annotations

import datetime as dt
import time
from pathlib import Path
from threading import Lock
from typing import Any, Callable

from . import config, views
from .data import DATA_DIR, Snapshot, load
from .model import PricingModel


class Fit:
    """One consistent (snapshot, model) pair and the views derived from it."""

    def __init__(self, snap: Snapshot, model: PricingModel, generation: int,
                 source: Path, fit_seconds: float) -> None:
        self.snap = snap
        self.model = model
        self.generation = generation
        self.source = source
        self.fit_seconds = fit_seconds
        self.loaded_at = dt.datetime.now(dt.timezone.utc)
        self._memo: dict[Any, Any] = {}
        self._lock = Lock()

    # Views are pure functions of an immutable snapshot, so a racing duplicate
    # computation is wasted work and nothing worse -- cheaper than holding a
    # lock across the whole build.
    def _cached(self, key: Any, build: Callable[[], Any]) -> Any:
        try:
            return self._memo[key]
        except KeyError:
            pass
        value = build()
        with self._lock:
            return self._memo.setdefault(key, value)

    # --- the dashboard payloads ------------------------------------------
    def sales(self, event: str | None):
        return self._cached(("sales", event),
                            lambda: views.sales_by_section(self.snap, event))

    def listings(self, event: str | None):
        return self._cached(("listings", event),
                            lambda: views.listings_by_section(self.snap, event))

    def section(self, section: str, event: str | None):
        return self._cached(
            ("section", section, event),
            lambda: views.section_detail(self.snap, section, event),
        )

    def overview(self):
        return self._cached("overview", lambda: views.event_overview(self.snap))

    def venue_map(self):
        return self._cached("map", lambda: views.venue_map(self.snap))

    def model_summary(self):
        return self._cached("model", self.model.summary)

    def meta(self):
        return self._cached("meta", self._build_meta)

    def _build_meta(self) -> dict:
        p = self.model.p
        return {
            "venue": config.VENUE,
            "team": config.TEAM,
            "season": config.SEASON,
            "events": [
                {
                    "key": e.key,
                    "label": e.label,
                    "opponent": e.opponent,
                    "game_type": e.game_type,
                }
                for e in self.snap.events
            ],
            "sections": self.snap.sections(),
            "strategies": p.strategy_names,
            "default_strategy": p.default_strategy,
            "counts": {
                "events": len(self.snap.events),
                "listings": len(self.snap.listings),
                "sales": len(self.snap.sales),
            },
            "dropped_on_load": self.snap.dropped,
            "clearing_ratio": round(self.model.clear_ratio, 4),
            "snapshot": self.status(),
        }

    def status(self) -> dict:
        return {
            "generation": self.generation,
            "loaded_at": self.loaded_at.isoformat(timespec="seconds"),
            "fit_seconds": round(self.fit_seconds, 3),
            "source": str(self.source),
            "events": len(self.snap.events),
            "listings": len(self.snap.listings),
            "sales": len(self.snap.sales),
        }


class AppState:
    """Holds the current :class:`Fit` and knows how to replace it."""

    def __init__(self, data_dir: Path | str | None = None) -> None:
        self.data_dir = Path(data_dir) if data_dir else DATA_DIR
        self._fit: Fit | None = None
        self._generation = 0
        self._swap = Lock()
        self.reload()

    @property
    def fit(self) -> Fit:
        fit = self._fit
        if fit is None:  # pragma: no cover - constructor always loads one
            raise RuntimeError("state has not been loaded")
        return fit

    def reload(self) -> dict:
        """Re-read the snapshot from disk, refit, and swap it in.

        Builds the replacement before touching the live reference, so a bad
        snapshot on disk raises and leaves the running app serving the good
        one.
        """
        started = time.perf_counter()
        snap = load(self.data_dir)
        model = PricingModel(snap)
        elapsed = time.perf_counter() - started
        with self._swap:
            self._generation += 1
            self._fit = Fit(snap, model, self._generation, self.data_dir, elapsed)
        return self.fit.status()
