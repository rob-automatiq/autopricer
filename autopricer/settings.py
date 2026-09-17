"""Runtime configuration, read from the environment.

Separate from ``config.py`` on purpose: that file holds *modelling* choices
which belong in version control and should only change with an argument
attached. This file holds *deployment* choices -- where to bind, where the
snapshot lives, who may reload it -- which change per environment and must
never be baked into the image.

Everything is optional and the defaults are the ones that make
``python3 -m autopricer serve`` work on a laptop. The container overrides
``AUTOPRICER_HOST`` so it listens on all interfaces inside its namespace.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .data import DATA_DIR

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

ENV_PREFIX = "AUTOPRICER_"


@dataclass(frozen=True)
class Settings:
    #: Interface to bind. ``127.0.0.1`` on a laptop; the container sets
    #: ``0.0.0.0`` because it is already isolated by its network namespace and
    #: nothing would reach it otherwise.
    host: str = "127.0.0.1"
    port: int = 8765
    #: Where the committed snapshot lives. A bind mount can point this at a
    #: freshly extracted one without rebuilding the image.
    data_dir: Path = DATA_DIR
    web_dir: Path = WEB_DIR
    #: Browsers that may call the API cross-origin. Empty means same-origin
    #: only, which is what serving the dashboard from this app implies.
    cors_origins: tuple[str, ...] = ()
    #: Shared secret for ``POST /api/reload``. Unset disables the endpoint --
    #: refitting is cheap but not free, so it is not left open by default.
    reload_token: str | None = None
    log_level: str = "info"
    #: Compress responses above this size. The listings payload is ~1 MB of
    #: JSON and compresses about 9:1.
    gzip_min_size: int = 1024
    #: Set by the image build so a running container can say what it is.
    build: str = ""

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        env = dict(os.environ if env is None else env)
        get = lambda k: env.get(ENV_PREFIX + k) or None  # noqa: E731

        origins = get("CORS_ORIGINS")
        port = get("PORT")
        gz = get("GZIP_MIN_SIZE")
        data = get("DATA_DIR")
        web = get("WEB_DIR")

        return cls(
            host=get("HOST") or cls.host,
            port=int(port) if port else cls.port,
            data_dir=Path(data) if data else cls.data_dir,
            web_dir=Path(web) if web else cls.web_dir,
            cors_origins=tuple(
                o.strip() for o in origins.split(",") if o.strip()
            ) if origins else (),
            reload_token=get("RELOAD_TOKEN"),
            log_level=(get("LOG_LEVEL") or cls.log_level).lower(),
            gzip_min_size=int(gz) if gz else cls.gzip_min_size,
            build=get("BUILD") or "",
        )
