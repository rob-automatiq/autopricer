"""Browser check: a quote must always be for the game the page is scoped to.

The bug this pins: the quote card once had its own game selector, so the page
header said one game and the price was for another.

Runs against a live server -- the app started in-process by default, or
whatever ``--base-url`` points at, which is how to check a running container:

    python3 scripts/check_game_scope.py
    python3 scripts/check_game_scope.py --base-url http://127.0.0.1:8765
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

# Run from anywhere: python3 puts scripts/ on the path, not the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def chrome_path() -> str | None:
    """The pre-installed Chromium, if there is one.

    Its directory carries the build number, which moves with the pinned
    playwright release, so it is discovered rather than hard-coded. ``None``
    leaves the choice to playwright's own resolution.
    """
    root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers"))
    found = sorted(root.glob("chromium-*/chrome-linux/chrome"))
    return str(found[-1]) if found else None


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve_in_thread(port: int) -> None:
    """Start the real app on a background thread and wait for /health."""
    import uvicorn

    from autopricer.api import create_app
    from autopricer.settings import Settings

    app = create_app(Settings(host="127.0.0.1", port=port))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                           log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            urlopen(f"http://127.0.0.1:{port}/health", timeout=1).read()
            return
        except (URLError, OSError):
            time.sleep(0.2)
    raise SystemExit("the server did not come up")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default=None,
                    help="check a server that is already running")
    args = ap.parse_args()

    base = args.base_url
    if base is None:
        port = free_port()
        serve_in_thread(port)
        base = f"http://127.0.0.1:{port}"
    base = base.rstrip("/")

    errs: list[str] = []
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=chrome_path())
        pg = b.new_page(viewport={"width": 1280, "height": 1000})
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(base + "/", wait_until="load")
        pg.wait_for_timeout(900)

        # There must be exactly one game selector on the page.
        n = pg.locator("select").count()
        assert n == 1, f"expected 1 game selector, found {n}"

        pg.click("#tab-price")
        pg.wait_for_timeout(400)
        # "All games" must not be selectable while pricing, and the scope must
        # have fallen forward to a real game.
        assert pg.eval_on_selector("#gamesel option[value=all]", "o => o.disabled"), \
            "'all games' still selectable on the price tab"
        assert pg.input_value("#gamesel") != "all", "scope still 'all' on the price tab"

        # The reported case: section 236 row P on the Oct 28 Warriors game.
        pg.select_option("#gamesel", "2026-10-28")
        pg.fill("#p-section", "236")
        pg.fill("#p-row", "P")
        pg.wait_for_timeout(900)
        txt = pg.inner_text("#quote")
        assert "Golden State Warriors" in txt, "quote is not for the selected game"
        assert "$79" in txt, "unexpected quote for Oct 28 / 236 / P"
        print("Oct 28 quote names the right game and reads $79")

        # Switching the one selector must move the quote with it.
        pg.select_option("#gamesel", "2026-10-14")
        pg.wait_for_timeout(900)
        txt = pg.inner_text("#quote")
        assert "Detroit Pistons" in txt and "$41" in txt, \
            "quote did not follow the selector"
        print("switching the selector moves the quote (preseason reads $41)")

        ov = pg.evaluate(
            "document.documentElement.scrollWidth"
            " - document.documentElement.clientWidth"
        )
        assert ov <= 1, f"{ov}px horizontal overflow"
        b.close()

    print("\n".join(errs) if errs else "no page errors")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
