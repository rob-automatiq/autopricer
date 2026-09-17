"""FastAPI application: the JSON pricing API plus the dashboard it serves.

One implementation of the engine, reached over HTTP. The routes are thin --
parse the query string, hand it to the model, return the payload -- because
everything interesting lives in ``model.py`` and ``views.py`` and is covered
by tests there.

Two deliberate departures from FastAPI's defaults:

* **Errors keep the shape the dashboard reads.** Every failure is
  ``{"error": "<sentence>"}``; the front end shows that sentence to whoever
  typed the bad input, so a 422 full of Pydantic's nested ``loc``/``msg``
  objects would be a regression. ``qty`` is therefore taken as a string and
  parsed here rather than declared as ``int``.
* **Dates are stringified on the way out.** The payloads carry
  ``datetime.date`` (invoice dates), so the encoder passes ``default=str``,
  matching what the dashboard has always received.
"""

from __future__ import annotations

import json
import logging
import traceback
from typing import Any

from fastapi import APIRouter, FastAPI, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import config
from .settings import Settings
from .state import AppState

log = logging.getLogger("autopricer")


class LooseJSONResponse(JSONResponse):
    """``json.dumps(..., default=str)`` -- dates become ISO strings."""

    def render(self, content: Any) -> bytes:
        return json.dumps(content, default=str).encode("utf-8")


def _err(code: int, msg: str) -> LooseJSONResponse:
    return LooseJSONResponse({"error": msg}, status_code=code)


api = APIRouter(prefix="/api")


def _state(request: Request) -> AppState:
    return request.app.state.autopricer


@api.get("/meta")
def meta(request: Request):
    return _state(request).fit.meta()


@api.get("/overview")
def overview(request: Request):
    return _state(request).fit.overview()


@api.get("/map")
def venue_map(request: Request):
    return _state(request).fit.venue_map()


@api.get("/model")
def model_summary(request: Request):
    return _state(request).fit.model_summary()


@api.get("/sales")
def sales(request: Request, event: str | None = None):
    return _state(request).fit.sales(event)


@api.get("/listings")
def listings(request: Request, event: str | None = None):
    return _state(request).fit.listings(event)


@api.get("/section/{section}")
def section_detail(request: Request, section: str, event: str | None = None):
    return _state(request).fit.section(section, event)


@api.get("/price")
def price(
    request: Request,
    event: str | None = None,
    section: str | None = None,
    row: str | None = None,
    qty: str = "2",
    strategy: str | None = None,
):
    if not event or not section:
        raise ValueError("event and section are required")
    try:
        n = max(1, int(qty))
    except ValueError:
        raise ValueError(f"qty must be a whole number, got {qty!r}") from None
    return _state(request).fit.model.recommend(
        event=event, section=section, row=row or None,
        qty=n, strategy=strategy or None,
    )


@api.post("/reload")
def reload_snapshot(request: Request,
                    x_autopricer_token: str | None = Header(default=None)):
    """Re-read the snapshot from disk and refit, without a restart.

    Off unless ``AUTOPRICER_RELOAD_TOKEN`` is set: it is the one route that
    changes what the app serves, so it is not left open by default.
    """
    settings: Settings = request.app.state.settings
    if not settings.reload_token:
        return _err(503, "reload is not enabled; set AUTOPRICER_RELOAD_TOKEN")
    if x_autopricer_token != settings.reload_token:
        return _err(403, "bad or missing X-Autopricer-Token")
    status = _state(request).reload()
    log.info("snapshot reloaded: generation %s", status["generation"])
    return {"reloaded": True, "snapshot": status}


def create_app(settings: Settings | None = None,
               state: AppState | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    app = FastAPI(
        title="autopricer",
        summary=f"Ticket pricing for {config.TEAM} {config.SEASON} home games "
                f"at {config.VENUE}.",
        version=settings.build or "dev",
        default_response_class=LooseJSONResponse,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.settings = settings
    # Fitting happens here rather than in a lifespan hook so that a snapshot
    # the model cannot fit fails the process immediately, instead of starting
    # a server that answers every request with a 500.
    app.state.autopricer = state or AppState(settings.data_dir)

    app.add_middleware(GZipMiddleware, minimum_size=settings.gzip_min_size)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_methods=["GET", "POST"],
            allow_headers=["X-Autopricer-Token"],
        )

    # --- errors, in the shape the dashboard reads -------------------------
    @app.exception_handler(ValueError)
    def _bad_request(request: Request, exc: ValueError):
        return _err(400, str(exc))

    @app.exception_handler(FileNotFoundError)
    def _missing(request: Request, exc: FileNotFoundError):
        return _err(404, "not found")

    @app.exception_handler(404)
    def _not_found(request: Request, exc: Exception):
        return _err(404, "not found")

    @app.exception_handler(Exception)
    def _boom(request: Request, exc: Exception):  # pragma: no cover
        traceback.print_exc()
        return _err(500, "internal error")

    # --- the dashboard ----------------------------------------------------
    index = settings.web_dir / "index.html"

    @app.get("/health", include_in_schema=False)
    def health(request: Request):
        return {"ok": True, "snapshot": _state(request).fit.status()}

    @app.get("/", include_in_schema=False)
    @app.get("/index.html", include_in_schema=False)
    def dashboard() -> Response:
        return FileResponse(index, media_type="text/html; charset=utf-8",
                            headers={"Cache-Control": "no-store"})

    app.include_router(api)
    if settings.web_dir.is_dir():
        app.mount("/static", StaticFiles(directory=settings.web_dir),
                  name="static")
    return app
