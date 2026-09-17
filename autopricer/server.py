"""Dependency-free HTTP server for the dashboard and the pricing API.

Uses ``http.server`` so the tool runs on a bare Python 3.11 with nothing
installed. The snapshot is small (10k listings) and the model is fitted once at
start-up, so every request is served from memory.
"""

from __future__ import annotations

import json
import mimetypes
import re
import traceback
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import config, views
from .data import Snapshot, load
from .model import PricingModel

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

_SECTION_RE = re.compile(r"^/api/section/([^/]+)/?$")


class State:
    """Snapshot plus fitted model, loaded once."""

    def __init__(self, data_dir: Path | str | None = None) -> None:
        self.snap: Snapshot = load(data_dir) if data_dir else load()
        self.model = PricingModel(self.snap)

    @lru_cache(maxsize=256)
    def sales(self, event: str | None):
        return views.sales_by_section(self.snap, event)

    @lru_cache(maxsize=256)
    def listings(self, event: str | None):
        return views.listings_by_section(self.snap, event)

    @lru_cache(maxsize=512)
    def section(self, section: str, event: str | None):
        return views.section_detail(self.snap, section, event)

    @lru_cache(maxsize=1)
    def overview(self):
        return views.event_overview(self.snap)

    @lru_cache(maxsize=1)
    def vmap(self):
        return views.venue_map(self.snap)

    @lru_cache(maxsize=1)
    def meta(self):
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
        }


class Handler(BaseHTTPRequestHandler):
    state: State
    server_version = "autopricer"

    # --- plumbing ---------------------------------------------------------
    def log_message(self, fmt: str, *args) -> None:  # quieter default log
        if self.path.startswith("/api/"):
            super().log_message(fmt, *args)

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, payload, code: int = 200) -> None:
        self._send(
            code,
            json.dumps(payload, default=str).encode(),
            "application/json; charset=utf-8",
        )

    def _error(self, code: int, msg: str) -> None:
        self._json({"error": msg}, code)

    # --- routing ----------------------------------------------------------
    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        try:
            self._route()
        except ValueError as exc:               # bad user input
            self._error(400, str(exc))
        except FileNotFoundError:
            self._error(404, "not found")
        except Exception:                       # pragma: no cover - last resort
            traceback.print_exc()
            self._error(500, "internal error")

    def _route(self) -> None:
        url = urlparse(self.path)
        path = url.path
        q = parse_qs(url.query)
        one = lambda k, d=None: (q.get(k) or [d])[0]  # noqa: E731
        st = self.state

        if path in ("/", "/index.html"):
            return self._static("index.html")
        if path.startswith("/static/"):
            return self._static(path[len("/static/"):])

        if path == "/api/meta":
            return self._json(st.meta())
        if path == "/api/overview":
            return self._json(st.overview())
        if path == "/api/map":
            return self._json(st.vmap())
        if path == "/api/model":
            return self._json(st.model.summary())
        if path == "/api/sales":
            return self._json(st.sales(one("event")))
        if path == "/api/listings":
            return self._json(st.listings(one("event")))

        m = _SECTION_RE.match(path)
        if m:
            return self._json(st.section(unquote(m.group(1)), one("event")))

        if path == "/api/price":
            event, section = one("event"), one("section")
            if not event or not section:
                raise ValueError("event and section are required")
            qty_raw = one("qty", "2")
            try:
                qty = max(1, int(qty_raw))
            except ValueError:
                raise ValueError(f"qty must be a whole number, got {qty_raw!r}")
            return self._json(
                st.model.recommend(
                    event=event,
                    section=section,
                    row=one("row") or None,
                    qty=qty,
                    strategy=one("strategy") or None,
                )
            )

        raise FileNotFoundError(path)

    def _static(self, rel: str) -> None:
        target = (WEB_DIR / rel).resolve()
        if not str(target).startswith(str(WEB_DIR.resolve())) or not target.is_file():
            raise FileNotFoundError(rel)
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        self._send(200, target.read_bytes(), ctype)


def serve(host: str = "127.0.0.1", port: int = 8765,
          data_dir: Path | str | None = None) -> None:
    Handler.state = State(data_dir)
    meta = Handler.state.meta()
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(
        f"autopricer  {meta['team']} {meta['season']} @ {meta['venue']}\n"
        f"  {meta['counts']['events']} games | "
        f"{meta['counts']['listings']:,} live listings | "
        f"{meta['counts']['sales']:,} sales\n"
        f"  http://{host}:{port}/"
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()
