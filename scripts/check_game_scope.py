"""The bug this fixes: a quote showing a different game than the page scope."""
from playwright.sync_api import sync_playwright
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
errs = []
with sync_playwright() as pw:
    b = pw.chromium.launch(executable_path=CHROME)
    pg = b.new_page(viewport={"width": 1280, "height": 1000})
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto("file:///home/user/autopricer/dist/preview.html", wait_until="load")
    pg.wait_for_timeout(900)

    # There must be exactly one game selector on the page.
    n = pg.locator("select").count()
    assert n == 1, f"expected 1 game selector, found {n}"

    pg.click("#tab-price"); pg.wait_for_timeout(400)
    # "All games" must not be selectable while pricing, and the scope must have
    # fallen forward to a real game.
    assert pg.eval_on_selector("#gamesel option[value=all]", "o => o.disabled"), \
        "'all games' still selectable on the price tab"
    assert pg.input_value("#gamesel") != "all", "scope still 'all' on the price tab"

    # The reported case: section 236 row P on the Oct 28 Warriors game.
    pg.select_option("#gamesel", "2026-10-28")
    pg.fill("#p-section", "236"); pg.fill("#p-row", "P")
    pg.wait_for_timeout(900)
    txt = pg.inner_text("#quote")
    assert "Golden State Warriors" in txt, "quote is not for the selected game"
    assert "$79" in txt, f"unexpected quote for Oct 28 / 236 / P"
    print("Oct 28 quote names the right game and reads $79")

    # Switching the one selector must move the quote with it.
    pg.select_option("#gamesel", "2026-10-14"); pg.wait_for_timeout(900)
    txt = pg.inner_text("#quote")
    assert "Detroit Pistons" in txt and "$41" in txt, "quote did not follow the selector"
    print("switching the selector moves the quote (preseason reads $41)")

    ov = pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert ov <= 1, f"{ov}px horizontal overflow"
    b.close()
print("\n".join(errs) if errs else "no page errors")
