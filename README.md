# autopricer

A section-level desk for **Minnesota Timberwolves home games at Target Center**:
pick a game and a section, and see what sold, what is listed on the B2B
consignment board, what Uptick's autopricer has decided, and what the retail
board is asking — with every identifier needed to go and check the same record
in Uptick or in B2B.

**The tool is one published artifact:**
[`artifact/section-desk.html`](artifact/section-desk.html) →
<https://claude.ai/artifact/EK3pXX5fxdDjqNszvsXRoG>

## One code path

There is no server, no container, no snapshot, and no second implementation of
anything. The page runs in the browser and reads the lake directly:

```
artifact/section-desk.html
   │
   ├── claude.use("mcp") ──► Datalake MCP · DataLakeInternalQuery   (ClickHouse SQL)
   └── claude.use("mcp") ──► B2B MCP      · search_listings         (live board)
```

Calls run with **the viewer's own connector credentials** — the page never sees
a token, and there is nothing to deploy or keep running. SQL is the only
backend, and it lives in the page next to the table it fills.

Every figure on the page is fetched when you pick a section. Nothing is baked
in except the bowl geometry (`artifact/venue.json`), which is positions only.

### What it shows, per section

| panel | source | what it is for |
|---|---|---|
| Same seat, three prices | all | why the numbers legitimately differ |
| Sales | `mcp_sales`, all four POS systems | gross **and** OST per ticket, plus the keys to find the sale in Uptick |
| Consignment board, now | `B2B MCP` + `mcp_lysted_listings` | the same board reached two independent ways, compared row by row |
| Consignment sold | `mcp_lysted_sales` | sale / line / marketplace refs, commission, both totals |
| Autopricer state | `mcp_uptick_pricing` | push price, comp, floor, ceiling per listing |
| VividSeats board | `mcp_prism_vividseats_event_listings` | the public ask board, for context |

## Before you trust any of it

**Read [`docs/DATA-NOTES.md`](docs/DATA-NOTES.md).** It is short, and every item
in it is a way this data has already misled a working tool — the event grain
that is one row per POS (88 rows for 36 games), the `status` column that
contradicts itself between those rows, the two sale totals that are both real,
the two listing universes that must never be mixed, and the Uptick pricing table
that looks live but is a daily dump.

The headline: the retired snapshot-based version of this tool under-reported the
season by **22 sales, 57 tickets and $12,583.65**, because it collapsed each game
to a single event row.

## Layout

```
artifact/
  section-desk.html    the tool
  venue.json           bowl geometry, generated once (positions only)
docs/
  DATA-NOTES.md        how to read this data without getting it wrong
  PRICING-MODEL.md     the retired recommendation engine, as a spec
reference/
  venue_geometry.py    regenerates venue.json; not part of the tool
```

## History

Through commit `246cc8e` this was a Python package: a FastAPI app in a
container, serving a dashboard off a committed TSV snapshot, plus a JavaScript
mirror of the pricing model so the page could be published standalone. Two
implementations of one model drift — it cost 78 one-cent rounding disagreements
to learn that — and a snapshot goes stale and hides its own gaps.

The requirement that settled it: the tool has to be an artifact, and it has to
read the lake live. Only browser JavaScript can be both. So the Python is gone;
`git show 246cc8e` has all of it if a piece is ever wanted back.

The pricing recommendation engine went with it. It was not duplicated
functionality — it existed only in Python — but it has no place to live in this
architecture yet. [`docs/PRICING-MODEL.md`](docs/PRICING-MODEL.md) describes what
it did and what it learned, so it can be rebuilt as SQL or as page code when it
is wanted.
