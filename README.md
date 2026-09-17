# autopricer

Ticket pricing for **Minnesota Timberwolves 2026-27 home games at Target
Center**. Three things:

1. **Sales** — where tickets sold, on a bowl map, by section, row and day.
2. **Listings** — the live ask board across sections.
3. **Price a ticket** — give it a section and row, get a recommended list
   price with the full reasoning behind it.

```bash
docker compose up --build -d           # dashboard at http://127.0.0.1:8765
docker compose logs -f autopricer
```

Or straight from a checkout:

```bash
pip install -r requirements-dev.txt
python3 -m autopricer serve            # dashboard at http://127.0.0.1:8765
python3 -m autopricer serve --reload    # restart on edits
python3 -m autopricer price 2026-12-25 112 C
python3 -m autopricer summary          # what the model learned
python3 -m autopricer events           # board and sales depth per game
python3 -m pytest tests -q
```

FastAPI and uvicorn, and nothing else at runtime — Python 3.11, no front-end
build step, no database. The container and the CLI run the same application
object (`autopricer.asgi:app`), so there is one code path to reason about.

### Configuration

All optional, all `AUTOPRICER_`-prefixed, read once at start-up
(`autopricer/settings.py`). Deployment settings only — the modelling constants
live in `autopricer/config.py` and belong in version control.

| variable | default | |
|---|---|---|
| `AUTOPRICER_HOST` | `127.0.0.1` | the container sets `0.0.0.0` |
| `AUTOPRICER_PORT` | `8765` | |
| `AUTOPRICER_DATA_DIR` | `data/raw` | point it at a re-extracted snapshot |
| `AUTOPRICER_CORS_ORIGINS` | none | comma-separated; same-origin otherwise |
| `AUTOPRICER_RELOAD_TOKEN` | unset | unset disables `POST /api/reload` |
| `AUTOPRICER_LOG_LEVEL` | `info` | |

The snapshot is baked into the image *and* `data/raw` is a bind mount, so a
refresh is: re-extract on the host, then

```bash
curl -X POST -H "X-Autopricer-Token: $AUTOPRICER_RELOAD_TOKEN" \
  http://127.0.0.1:8765/api/reload
```

No rebuild and no restart. The reload loads and refits into a *new* bundle and
swaps it in one assignment (`autopricer/state.py`), so a request can never be
answered from a half-updated state, and a snapshot that fails to load leaves
the running app serving the good one.

## The data

A committed snapshot in `data/raw/`, pulled from Automatiq's data lake:

| | rows | source |
|---|---|---|
| `events.tsv` | 35 games | `mcp_events` |
| `sales.tsv` | 568 sales | `mcp_sales` (all four POS systems) |
| `listings.tsv` | 10,319 asks | `mcp_prism_vividseats_event_listings` |

The lake is only reachable through the Datalake MCP server, which an agent
session calls — there is no connection string the app could use. So the
snapshot is committed, `autopricer/sql/` holds the exact queries that produced
it, and **[`scripts/REFRESH.md`](scripts/REFRESH.md)** is the procedure for
re-pulling it. `python3 -m autopricer refresh` prints that file.

Of the five marketplace tables in the lake, only VividSeats has coverage for
these games — seatgeek, ticketmaster and stubhub all return zero rows — so the
board is VividSeats only.

### Joining the two sides

The listings and sales sides label the same seat differently, and getting this
wrong silently produces an empty comp set rather than an error:

- listings prefix the bowl and zero-pad the floor: `"Lower Level 112"`, `"06"`
- sales carry the bare number: `"112"`, `"06"`

`autopricer/normalize.py` reduces both to a section number with no prefix and
no leading zeros. Two things worth knowing: `"7th St."` is a parking listing
and is dropped, and **rows `I` and `O` are real rows** at Target Center
(sections 207, 215, 227, 228) — the alphabet is not skipped the way it is at
some venues.

## How a price is worked out

Three surfaces are fitted from the snapshot. All are medians, so a single silly
ask cannot move them.

**1. A section quality index.** Within one game, each section's median ask is
divided by that game's overall median ask; the index is the median of those
ratios across all 35 games, which divides out game-to-game demand. Centre-court
lower bowl lands at ×2.4–2.9, upper corners at ×0.37, courtside at ×8–12.

**2. A row curve.** Each ask is divided by the median ask of its own
(game, section) cell — removing both the game and the section, leaving the row.
Ratios are pooled by tier and row depth, shrunk toward neutral by sample size,
then fitted so a row is never worth less than one behind it (pool-adjacent
violators). Lower bowl runs ×1.35 at row A to ×0.97 at row Z; the upper bowl is
much flatter, ×1.08 to ×1.00, which is the shape you would expect.

**3. A clearing ratio.** Every realised sale is compared with the current median
ask in the same game and section. The median of that ratio is **×0.735** — how
far below the asking board seats actually trade. It splits by tier: ×0.70 lower,
×0.78 upper, so upper-deck asks sit closer to their clears.

A quote then:

- builds a **comp set** from live asks in the target section, each re-priced to
  the target row. If the section has fewer than three, it widens to same-tier
  sections whose index is within 18%, scaling by the ratio of indices, and says
  so in `caveats`.
- takes two independent estimates of the right ask — the **comp median** and
  the **index model** (`game level × section index × row factor`) — and shrinks
  between them by `n/(n+5)`, so a two-listing section leans on the model and a
  forty-listing section does not.
- estimates an **expected clearing price** from realised comparable sales
  (same game and section, else the same section across games scaled by game
  level, else the tier), shrunk against `blended ask × clearing ratio`.
- picks a **position on the board**: the 10th percentile of the comp set for
  `aggressive`, the 35th for `balanced`, the 65th for `patient`. The two
  patient strategies are floored at the expected clearing price, and all three
  are capped at the 85th percentile of comps unless the clearing price is
  higher — a listing priced past the back of the board is invisible behind
  cheaper identical seats.

Every number above is returned in the response under `drivers`, so a quote can
be audited rather than taken on faith. The modelling constants all live in
`autopricer/config.py`.

## Known limitations

- **The clearing ratio conflates two things.** Listings are a single day's
  board; the sales span the weeks before it. So ×0.735 mixes the genuine
  ask-to-clear spread with whatever price drift happened over that window.
  It is a directional calibration, not a clean measurement. Capturing daily
  listing snapshots over time is what would separate the two — the lake keeps
  historical `processed_date` partitions, so this is a matter of extracting
  them, not of new instrumentation.
- **Asks are not sales.** The comp set says what people are *asking*, and most
  listings never sell. The clearing ratio is the only correction applied.
- **Gross vs net — this tool and Uptick quote different numbers for the same
  sale.** `mcp_sales` carries two totals. `total_sales` is the gross the buyer
  paid, including the exchange's fees; `total_sales_ost` (Order Sold Total) is
  the broker's side of the same sale, and **that is the figure Uptick shows**.
  For section 209 row Q against Golden State on 2026-10-28 they are $125.99 and
  $131.02 per ticket.
  The model prices off **gross**, for two reasons: OST is absent on 59% of the
  snapshot's sales, and gross is the buyer-facing side of the trade, which is
  the side an ask sits on. Both figures now travel through to the UI, so a
  quote can be reconciled against Uptick rather than quietly disagreeing.
  Worth knowing before trusting either: the lake documents
  `total_sales >= total_sales_ost`, but on this data OST runs about **4% above**
  gross for Ticketmaster and SeatGeek Full Service sales and about 2% below
  elsewhere, with a handful of rows 20–40% out. At least one of the two columns
  is not doing what its documentation says, which is worth settling with
  whoever owns the pipeline.
- **One game has no board.** Philadelphia (2027-03-13) has 45 sales and zero
  active listings. Its game level is recovered by inverting the pricing
  identity on those sales, and every quote for it carries a caveat.
- **The bowl map is transcribed, not generated.** Section centres in
  `autopricer/venue.py` are read off Target Center's published seat map and
  stored in that image's pixel space, with the arena edge each section sits on
  so the tile lies flat along it. Worth knowing: the lower bowl is **not**
  101-138 — the arena has 22 lower-bowl sections and the other sixteen numbers
  in that range are not seating, which is why an earlier generated ring drew
  sixteen sections that do not exist. Courtside is drawn only for the sections
  the feed carries, and their placement against the map's `CS1`-`CS10` labels
  is inferred from the numbering (it moves a tile, never a price). Club, suite,
  table and theatre-box inventory is absent from the VividSeats feed, so it is
  not drawn.
- **No time-to-event decay.** Every quote is for the board as it stands today.
  Because each game's level is measured from its own current board, that is
  handled implicitly for pricing now, but the tool cannot answer "what should
  this be worth in three weeks".
- **Sales are Automatiq's, asks are the whole market.** The 568 sales are what
  flowed through Uptick/Sync/Lysted, not every sale at Target Center, so the
  clearing evidence is thinner in sections our brokers do not hold.

## Layout

```
autopricer/
  config.py      modelling constants, all in one place
  normalize.py   section/row canonicalisation across the two sources
  venue.py       Target Center tiers and the schematic bowl geometry
  data.py        snapshot loading and indices
  stats.py       percentiles, medians (no numpy)
  model.py       the three surfaces and the pricing engine
  views.py       dashboard aggregations
  state.py       the (snapshot, model) bundle and how it is replaced
  api.py         FastAPI app: the JSON API and the dashboard it serves
  asgi.py        `uvicorn autopricer.asgi:app` -- what the container runs
  server.py      uvicorn in front of it, for `serve`
  settings.py    deployment configuration from the environment
  cli.py         serve / price / summary / events / refresh
  sql/           the extract queries, versioned
web/             dashboard (vanilla JS, hand-built SVG)
data/raw/        the committed snapshot
scripts/         REFRESH.md, check_game_scope.py
Dockerfile       python:3.11-slim, non-root, read-only, healthchecked
compose.yaml     port on loopback, snapshot bind-mounted
```

### API

| endpoint | returns |
|---|---|
| `GET /api/meta` | games, sections, strategies, counts |
| `GET /api/overview` | per-game board and sales depth |
| `GET /api/sales?event=` | sales by section, row, day, type |
| `GET /api/listings?event=` | the board by section, plus a price histogram |
| `GET /api/section/<sec>?event=` | one section's rows, ask vs sold |
| `GET /api/map` | bowl geometry |
| `GET /api/model` | the fitted surfaces |
| `GET /api/price?event=&section=&row=&qty=&strategy=` | a quote |
| `GET /health` | liveness, plus which snapshot is loaded |
| `POST /api/reload` | re-read the snapshot and refit (needs the token) |

`event` accepts a game date or `all`. Interactive docs are at `/api/docs`.

Bad input comes back as `400 {"error": "<sentence>"}` — `unknown event
'1999-01-01'`, `'999' is not a Target Center seat section` — because the
dashboard shows that sentence to whoever typed it. `tests/test_api.py` pins
each one.
