"""Running the app: uvicorn in front of the FastAPI application.

``python3 -m autopricer serve`` and the container run the same application
object; this module only decides how the process is supervised.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from .settings import Settings


def _banner(settings: Settings, meta: dict) -> str:
    c = meta["counts"]
    return (
        f"autopricer  {meta['team']} {meta['season']} @ {meta['venue']}\n"
        f"  {c['events']} games | {c['listings']:,} live listings | "
        f"{c['sales']:,} sales\n"
        f"  http://{settings.host}:{settings.port}/"
    )


def serve(host: str | None = None, port: int | None = None,
          data_dir: Path | str | None = None, reload: bool = False,
          settings: Settings | None = None) -> None:
    import uvicorn

    settings = settings or Settings.from_env()
    overrides = {}
    if host:
        overrides["host"] = host
    if port:
        overrides["port"] = port
    if data_dir:
        overrides["data_dir"] = Path(data_dir)
    if overrides:
        settings = replace(settings, **overrides)

    if reload:
        # Autoreload re-imports the app in a child process, so it has to be
        # named rather than handed over as an object.
        uvicorn.run(
            "autopricer.asgi:app", host=settings.host, port=settings.port,
            reload=True, reload_dirs=["autopricer", "web"],
            log_level=settings.log_level,
        )
        return

    from .api import create_app

    app = create_app(settings)
    print(_banner(settings, app.state.autopricer.fit.meta()), flush=True)
    uvicorn.run(app, host=settings.host, port=settings.port,
                log_level=settings.log_level, access_log=True)
