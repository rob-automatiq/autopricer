# Refreshing the snapshot

The app reads a committed snapshot in `data/raw/`, not the lake directly. It
has to: the data lake is reached through the **Datalake MCP server**, which
only an agent session can call — there is no ClickHouse connection string, and
nothing in this repo can open one. So a refresh is a short agent task, and
`autopricer/sql/` holds the exact queries that produced the current files.

Nothing here runs on a schedule. Re-run it when you want the board to be
current; the listings extract is a point-in-time snapshot and goes stale within
a day or two.

## The three files

| File | Rows today | Query |
|---|---|---|
| `data/raw/events.tsv` | 35 | `autopricer/sql/events.sql` |
| `data/raw/sales.tsv` | 568 | `autopricer/sql/sales.sql` |
| `data/raw/listings.tsv` | 10,319 | `autopricer/sql/listings.sql` |

## Steps

1. **Events.** Run `events.sql`. One row per home game. Write
   `event_date, opponent, label, vs_xid, game_type`, deriving `opponent` from
   the event name and setting `game_type` to `preseason`, `cup`, `marquee` or
   `regular`. Games worth marking `marquee`: Christmas Day, and the Boston
   game carrying the Kevin Garnett jersey retirement.

2. **Sales.** Run `sales.sql` and write the columns straight through. It
   returns *two* per-ticket sale figures and they are not interchangeable:
   `price` is the gross the buyer paid including exchange fees, and `net` is
   `total_sales_ost`, the broker's side of the same sale — **the figure Uptick
   displays**. A `0` in either `net` or `cost` means "not captured", which the
   loader treats as unknown rather than as zero.

3. **Listings.** Run `listings.sql`. The result is one row per event+section
   with the listings packed into a `row:price:qty:viewscore10` string, joined
   by `;`. It will be too large to return inline; the MCP server spills a
   result that size to a file and prints the path. Unpack it with:

   ```python
   import json, csv
   src = "<path the MCP server printed>"
   rows = json.loads(json.load(open(src))["result"])

   with open("data/raw/listings.tsv", "w", newline="") as f:
       w = csv.writer(f, delimiter="\t", lineterminator="\n")
       w.writerow(["event_date", "section", "row", "price", "qty", "view_score"])
       for r in rows:
           for t in r["listings"].split(";"):
               row, px, qty, vs = t.split(":")
               vs = round(int(vs) / 10, 1) if vs not in ("", "None") else ""
               w.writerow([r["event_date"], r["section"], row, px, qty, vs])
   ```

4. **Check it.** `python3 -m autopricer summary` prints the row counts and the
   refitted surfaces. Then `python3 -m pytest tests -q`. The row counts in the
   table above are a reference point, not an assertion — they move with the
   market.

## Things that will bite

- **Section labels differ by source.** Listings say `"Lower Level 112"` and
  zero-pad the floor (`"06"`); sales say `"112"` and `"06"`. Both go through
  `autopricer.normalize.section_key`, so leave them as the lake returns them
  and let the loader canonicalise. `"7th St."` is a parking listing and is
  dropped on load, not in SQL.
- **Rows `I` and `O` are real** at Target Center (sections 207, 215, 227, 228).
  Do not "fix" them to `1` and `0`.
- **The listings snapshot and the sales window do not line up.** Listings are
  one day's board; sales span the weeks before it. The clearing ratio the model
  derives from the two therefore mixes the genuine ask-to-clear spread with
  whatever price drift happened over that window. It is a directional
  calibration. Capturing daily listing snapshots over time is what would
  separate the two properly.
- **Gross and net disagree, in both directions.** The lake documents
  `total_sales >= total_sales_ost`, but on this data OST runs about 4% *above*
  gross for Ticketmaster and SeatGeek Full Service sales and about 2% below
  elsewhere, with a few rows 20-40% out. Do not "fix" one from the other; carry
  both.
- **Only VividSeats has coverage.** The seatgeek, ticketmaster and stubhub
  prism tables return zero rows for these events. If that changes, the board
  becomes a union and `listings.sql` needs a source column.
