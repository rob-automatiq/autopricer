# Reading this data without getting it wrong

Everything here was verified against the lake on 2026-09-18. Each item is a way
the data has already misled a working tool, or would have.

## 1. An event is not a row. It is a group of rows.

`mcp_events` carries **one row per POS system** for the same game — suffixes
`-vs` (VividSeats), `-tn` (Ticket Network), `-in` (Indy/Lysted), `-oh`. For
Timberwolves home games this season:

```
88 event rows  ->  36 games
```

Scope every query by **`b2bexchangeeventid`** and read all the rows in the
group. The row's own `id` is what `mcp_sales.event_id` and
`mcp_lysted_*.event_id_with_pos` point at, so a query that picks one row per
game silently drops the sales booked against the others.

**This already cost us.** The retired snapshot collapsed each game to one event
row, and so reported:

| | snapshot | actual (all POS) | lost |
|---|---|---|---|
| sales | 570 | **592** | 22 |
| tickets | 1,434 | **1,491** | 57 |
| gross | $394,598.44 | **$407,182.09** | $12,583.65 |

Sales split by POS, season-wide: `vs` 427, `in` 127, `tn` 21, `oh` 17.

## 2. `status` contradicts itself between rows of the same game

The same game can be `Cancelled` on one POS row and `ACTIVE` on another, and a
`Cancelled` row still carries sales:

- Toronto, 2026-10-25 — `7432907-vs` is `Cancelled`, `8205287-tn` is `ACTIVE`.
- Golden State, 2026-10-28 — `7432835-vs` is `Cancelled` and holds **42 sales**.

Do not filter on `status`. It describes one exchange's view of the listing, not
whether the game is happening.

## 3. Every game's cross-system ids are already in `mcp_events`

`b2bexchangeeventid`, `vsexchangeeventid`, `tmexchangeeventid`,
`sgexchangeeventid`, `tnexchangeeventid`, `ohexchangeeventid`,
`tmdiscoveryeventid`. The B2B one matches the B2B catalog's short ids exactly
(`APMD65Q3` = 2026-10-25 Toronto, `DPYXDNPM` = 2026-10-28 Golden State), so a
game selected in one system maps provably to the same game in the other. There
is no need to match on name or date.

## 4. Gross and OST are different quantities, and both are real

`mcp_sales` carries two order totals. Divide either by `total_qty` for a
per-ticket figure.

| column | what it is |
|---|---|
| `total_sales` | gross — what the buyer paid, including the exchange's fees |
| `total_sales_ost` | Order Sold Total — the broker's side of the same sale. **This is what Uptick displays.** |

A `0` in `total_sales_ost` or `total_cost` means *this POS never sent the
figure*, not zero. Coverage is a POS artifact, not randomness:

| POS | OST populated |
|---|---|
| `in` | 127 / 127 |
| `tn` | 21 / 21 |
| `oh` | 6 / 17 |
| `vs` | 98 / 427 |

The lake documents `total_sales >= total_sales_ost`. **That does not hold.** OST
runs a few per cent *above* gross on Ticketmaster and SeatGeek Full Service
sales and a couple of per cent below elsewhere, with outliers 20–40% out. Carry
both; never derive one from the other. Worth settling with whoever owns the
pipeline.

## 5. There are two listing universes. Never mix them.

**B2B / consignment** — your inventory.

- Live: `B2B MCP` → `search_listings({event_ids: [b2bexchangeeventid]})`.
  Prices are **integer cents**. Carries section, row, quantity, seats,
  stock type, in-hand date.
- In the lake: `mcp_lysted_listings`, joined by
  `event_id_with_pos IN (<the game's event ids>)`. Prices are **dollars**.
  Live means `status IN ('ACTIVE','READY') AND deleted_at IS NULL`; `SOLD` rows
  stay in the table and explain an empty board.
- Sold: `mcp_lysted_sales`, at section/row grain, with `sale_id`,
  `invoice_line_id`, `externalref` (the marketplace ref) and
  `user_invoice_id` (a hash, not a typeable invoice number).

**Retail** — the whole public market. `mcp_prism_vividseats_event_listings` and
its seatgeek / stubhub / ticketmaster / viagogo siblings, keyed on the bare
exchange event id (`7432835`, not `7432835-vs`). Two traps: **every numeric
column is a `String`** (`toFloat64OrNull`, `toUInt32OrNull`), and the table
keeps one snapshot per `processed_date` — the newest partition is the current
board. `price` is the displayed ask; `all_in_price_per_ticket` includes fees and
is the figure comparable to a sale's gross.

Of the five retail boards, only VividSeats had coverage for these games when
last checked.

## 6. Uptick's pricing state is a daily snapshot

`mcp_uptick_pricing` — `push_price`, `cmp`, `floor`, `ceiling`, `group_mode`.
1.2M rows, and **every one carries the same `calculated_at`** (13:00 UTC on the
day checked). It is a once-a-day dump, not a live feed, so a listing repriced
after the dump will disagree with it — that gap is information, not an error.

The join is `mcp_uptick_pricing.listing_id = mcp_lysted_listings.id` (84 of 106
matched on a sample game). It does **not** join to
`mcp_sync_listings.inventory_id`.

## 7. Section labels differ by source

Listings prefix the bowl and zero-pad the floor (`Lower Level 112`, `06`); sales
carry the bare number (`112`, `06`). Canonicalise both to a prefix-free number
with no leading zeros, or the two sides will never meet. `7th St.` is a parking
listing. **Rows `I` and `O` are real rows** at Target Center (sections 207, 215,
227, 228) — do not "fix" them to 1 and 0.

## 8. The bowl is not 101–138

Target Center has **22 lower-bowl sections**: 101, 104, 106, 109, 110, 111, 112,
113, 116, 118, 120, 121, 122, 124, 126, 129, 130, 131, 132, 133, 136, 138. The
other numbers in that range are not seating. Plus 40 upper (201–240) and 10
courtside strips. `artifact/venue.json` holds the positions.

## 9. B2B *transactions* have no seat location

`mcp_b2b_transactions` is order-grain: buyer, seller, `tickets_quantity`,
`total_amount`, `order_source`, `status` — and **no section or row**. Section-level
B2B work has to come from `mcp_lysted_listings` / `mcp_lysted_sales` instead.

## 10. One worked example

Section 209, row Q, Golden State on 2026-10-28 — four legitimate numbers for
one seat:

| figure | value | source |
|---|---|---|
| buyer gross | $125.99 / tkt | `mcp_sales.total_sales / total_qty` |
| Uptick OST | $131.02 / tkt | `mcp_sales.total_sales_ost / total_qty` |
| consignment ask, live | $133.36 | `B2B MCP` listing `ZN236GX2`, 13336 cents |
| consignment sale | $127.25 gross / $131.02 OST | `mcp_lysted_sales` sale `12509213` |

If a tool shows one of these without saying which, it is wrong by omission.

## 11. Two ClickHouse faults that abort a query outright

Both cost a shipped version of this tool. Neither is about your data being
wrong; they are engine and ingest defects you have to write around.

**`deleted_at IS NULL` fails** on ClickHouse 26.4.5 when the same block also
carries an `IN (subquery)` set:

```
Code: 10. DB::Exception: Not found column deleted_at.null: in block
in(__table6.event_id_with_pos, __set_...) ... (NOT_FOUND_COLUMN_IN_BLOCK)
```

It is the null-check, not the column. Select
`ifNull(toString(l.deleted_at), '') AS deleted_at` and test it in the
application instead.

**Selecting `mcp_lysted_listings.seats` aborts the read.** The column is
declared `Nullable(JSON)` but the parquet behind it holds arrays:

```
Code: 117. DB::Exception: Cannot insert data into JSON column: Cannot read
JSON object from JSON element: [1,2,3,4,5,6,7,8,9,10] ... column: seats
(in file/uri internal_mcp/mcp_lysted_listings/0011_part_00.parquet)
(INCORRECT_DATA)
```

`toString()` does not help — the failure is in reading the part, so the whole
query dies. Do not select the column. Seat numbers are available cleanly from
`B2B MCP.search_listings` (`"5-10"`). Worth fixing at the ingest: the declared
type and the stored data disagree. `mcp_lysted_listings.tags` is also
`Nullable(JSON)` and presumably carries the same risk.

## 12. Retail section labels are prefixed, and the obvious filter is inverted

`mcp_prism_*_event_listings.section` stores the **prefixed** label
(`Upper Level 209`), not the bare number. Normalise the column, do not build
candidate labels:

```sql
AND replaceRegexpOne(
      replaceRegexpOne(ifNull(p.section, ''),
        '(?i)^(lower|upper|club|suite|main|balcony|mezzanine)[ ]+(level|lvl)[ ]+', ''),
      '^0+', '') = '209'
```

Writing `'209' IN (p.section, ...)` asks whether the literal `'209'` equals
`'Upper Level 209'`, which is always false — an empty panel that looks like
"this section has no asks".

## 13. `mcp_sales` and `mcp_lysted_sales` disagree on gross for the same sale

Section 209, row Q, 2026-10-28, qty 2, invoiced 2026-09-16 — one sale, two
tables:

| table | gross total | gross / tkt | OST total |
|---|---|---|---|
| `mcp_sales` | 251.98 | $125.99 | 262.04 |
| `mcp_lysted_sales` | 254.4998 | $127.25 | 262.04 |

OST agrees to the cent; gross differs by **1%**. Both are loaded from the same
trade, so at least one is derived rather than recorded. Show whichever you use
with its table named, and do not average them.

The full chain for that seat, which is the cleanest worked example in this data:
**listed at $125.99** (`mcp_lysted_listings` 24487368) → **sold $125.99 gross /
$131.02 OST** per `mcp_sales` → **$127.25 gross / $131.02 OST** per
`mcp_lysted_sales`. The live board still shows a 10-seat row Q listing at
$124.95, with Uptick's push price $124.95, comp $99.99, floor $119, ceiling $895.

## 14. One B2B listing has three prices, and none of them is "the" price

For the 2026-10-28 Golden State game, two listings read straight off the B2B
screen against both data paths:

| listing | B2B screen | `mcp_lysted_listings.price` | `search_listings` |
|---|---|---|---|
| 138 row K ×2 | **$273.41** | $265.00 | $281.62 |
| 138 row 3 ×3 | **$900.65** | $850.00 | $927.67 |

Two relationships, only one of which is derivable:

- **Connector = screen × 1.03, exactly.** Inverting it reproduces the screen
  figure to the cent on both cases, with the division floored:
  `floor(28162 / 1.03) = 27341` → $273.41, and
  `floor(92767 / 1.03) = 90065` → $900.65. Use the connector price ÷ 1.03 when
  you need the number a person is looking at.
- **Screen ÷ lake price is a per-listing markup** — 3.2% on one of those rows
  and 6.0% on the other, 4.7% on section 101's rows. It is not a constant and
  it is **not derivable** from the lake:
  `mcp_sync_markups_and_exchange_fees` carries only `median_markup` and
  `median_exchange_fee` per (sync_id, exchange) and is mostly NULL. So show the
  markup, do not try to compute the screen figure from the lake.

The lake price is the broker's own list price, and it equals
`mcp_uptick_pricing.push_price` wherever the autopricer is driving the listing —
which is the useful thing about it, and a reason to keep it on screen rather
than hide it behind the marketplace figure.

**Counts disagree too.** The B2B screen reports **112 listings** for that game;
`mcp_lysted_listings` holds **106** (98 `ACTIVE`/`READY`, 8 `SOLD`, 0 deleted)
across 46 sections; `search_listings` returns about 110. Show all three counts
rather than picking one.

## Result-size limit

The Datalake MCP spills a large answer to a file and returns the path instead of
the rows. Keep queries narrow (one game, one section, a `LIMIT`) and treat a
payload that is not JSON as "too large", not as data.
