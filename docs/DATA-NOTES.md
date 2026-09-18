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
1.2M rows, and **every one carries the same `calculated_at`**. It is a snapshot,
not a live feed, so a listing repriced since the pull will disagree with it —
that gap is information, not an error. It is **not** once a day: 13:00 and
16:00 UTC were both observed on 2026-09-18.

The join is `mcp_uptick_pricing.listing_id = mcp_lysted_listings.id` (84 of 106
matched on a sample game). It does **not** join to
`mcp_sync_listings.inventory_id`. Guard it against fan-out — see §16.

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

## 13a. The POS and B2B views of a sale join exactly

**`mcp_sales.id` = `mcp_lysted_sales.user_invoice_id`.** No section/row/date
matching needed. Scope the B2B side to the game as well, and left-join from
`mcp_sales`:

```sql
LEFT JOIN (
  SELECT user_invoice_id, sale_id, invoice_line_id, externalref,
         total_sales, total_sales_ost, saletotal, commission_rate
  FROM mcp_lysted_sales
  WHERE event_id_with_pos IN (<the game's event ids>)
) ls ON ls.user_invoice_id = s.id
```

On the 2026-10-28 game: **53 POS sales, 8 of them also in B2B, and all 8 B2B
sales match a POS sale** — so B2B is a subset and a left join loses nothing.
Every matched row is `pos = 'in'`, which is what you would expect.

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

Across all 8 matched sales on that game, **OST agrees on every one and gross
differs on 4** — three by exactly +1.0% on the B2B side and one by +1.5%:

| section/row | POS gross / tkt | B2B gross / tkt | OST / tkt | commission |
|---|---|---|---|---|
| 138 K | $265.00 | $267.65 (+1.0%) | $275.59 | 4% |
| 209 Q | $125.99 | $127.25 (+1.0%) | $131.02 | 4% |
| 131 V | $603.75 | $609.79 (+1.0%) | $627.88 | 4% |
| 231 J | $200.00 | $203.00 (+1.5%) | $196.00 | 8% |
| 228 V | $90.12 | $90.12 | $93.73 | 4% |
| 111 G | $600.00 | $600.00 | $587.99 | 6% |
| 206 K | $172.91 | $172.91 | $169.45 | 8% |
| 136 R | $265.00 | $265.00 | $259.70 | 6% |

Note also that OST sits **above** gross on some rows and **below** on others
(231 J, 111 G, 206 K, 136 R), so the relationship is not even directional. The
lake's documented `total_sales >= total_sales_ost` fails in both directions.

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

## 14a. The two systems disagree about a listing's quantity — never match on it

Section 235 row U for the 2026-10-28 game is **one** listing,
`mcp_lysted_listings.id = 24276274`:

| | quantity | price |
|---|---|---|
| lake | **10** | $111.63 |
| B2B screen and API | **6** | $118.49 (= 111.63 × 1.0615) |

Match a lake listing to its marketplace counterpart on **row**, then by nearest
price. Keying on row + quantity splits a listing that exists in both into
"lake only" plus "marketplace only", which reads as one listing missing and one
phantom appearing — and the section then looks like it is hiding inventory.

Carry both quantities through to whatever you build. There is no correct single
number, and the gap is now explained rather than merely suspected — see §14c.

## 14c. `shown_quantity` is the B2B number, and it is the only Uptick-side one

`mcp_uptick_pricing` has **no quantity column at all** — its nine columns are
prices, bounds and timestamps. So "what quantity does Uptick see?" has to be
answered from the Sync listing Uptick prices against, joined
`toString(mcp_sync_listings.inventory_id) = toString(mcp_lysted_listings.id)`.
That join is genuine: section and row agree on every matched row, and it reaches
**2,548 of 2,921** Timberwolves lake listings.

Two columns come back and only one of them carries information:

| column | vs. the lake's `quantity` |
|---|---|
| `quantity` | identical on **2,548 of 2,548** — a confirmation, never a discrepancy |
| `shown_quantity` | present on 964, **differs on 957, and is lower on all 957** — never higher |

**`shown_quantity` is what B2B displays.** Checked against the connector for the
2026-10-28 game:

| section/row | lake `quantity` | `shown_quantity` | B2B API |
|---|---|---|---|
| 235 / U | 10 | **6** | `YN483L85` → **6** |
| 215 / S | 11 | **6** | `GDLKM34R` → **6** |
| 235 / E | 3 | null | `7472JDZ7` → **3** |

So the marketplace quantity is `coalesce(shown_quantity, quantity)`. A listing
holding ten tickets and offering six is a broker withholding display quantity —
a normal state, not a sync fault. That distinction is the whole reason the lake
quantity is worth flagging: a flagged row with a matching `shown_quantity` is
explained, and one without is not.

Note that `sync_qty` being always equal to the lake makes an "Uptick quantity"
column a cross-check rather than a finder. Do not reach for
`mcp_uptick_pricing.listing_id = mcp_sync_listings.inventory_id` expecting a
quantity to fall out of the pricing table itself; it will not.

## 14b. Two `mcp_sales` columns carry no information

Across all Timberwolves home games (608 sales):

**`if_brokergenius` restates `type`.** It is not an independent flag:

| `type` | `if_brokergenius` | sales |
|---|---|---|
| `Manual` | false | 419 |
| `Full Service` | true | 95 |
| `License` | true | 11 |
| null | null | 82 |

One-to-one, no exceptions. Show one of them, not both.

**`processor` is `SeatScouts` on 596 of 608** — `Other` on 10, null on 2. Not
quite constant, so do not assert it is, but it does not earn a column.

**A null `type` is not missing data.** It means the sale was booked against a
`Sync:` account rather than an `Uptick:` one, so it never went through Uptick
or the consignment marketplace: all 82 null-`type` rows are `Sync:` accounts,
and every `Uptick:` account row has a value. Those rows have no B2B side
either. The account prefix is the thing to read.

### What `type` actually means

Per the column's own documentation, it is **who set the price** — four
different things, not degrees of one:

| value | meaning | sales |
|---|---|---|
| `License` | priced by **Uptick**, the auto-pricing product | 11 |
| `Full Service` | priced by **Automatiq's Full Service Pricing team** — a person at Automatiq, not the engine | 95 |
| `Manual` | the broker set the price themselves, no Uptick involvement | 419 |
| null | a `Sync:` sale; Sync delivers tickets and does not price them, so there is no attribution | 82 |

`type` is constant within an account except on **`Uptick:2203`** — the umbrella
account Lysted sub-broker sales roll up to — which carries all three. Every
other account has exactly one value, so a mixed account is a roll-up, not dirty
data.

### `anchor` only means something on Uptick-priced sales

The column documents itself as the competitor feed Uptick priced against, and
"only relevant for Uptick-priced sales". The data agrees, emphatically: on
`Manual` sales it is `Other` on **all 420**. It varies only on the two
Uptick-priced types (`Full Service`: 56 `Other` / 39 `Automatiq Feed`;
`License`: 5 / 6). Show it for those two and leave it blank elsewhere, or it is
a column of one repeated word.

`last_touched_email` is populated on 106 of 608 — sparse but real when present,
and null on every `Sync:` row.

## 15. B2B's event list disagrees with B2B's own listing view

For 2026-10-28, B2B's event-list row reports **157 listings, 606 tickets,
$72.90 get-in, $291.21 ATP**. No source reproduces that, including B2B itself:

| source | listings | tickets | get-in | ATP (ticket-weighted) |
|---|---|---|---|---|
| **B2B event list** | **157** | **606** | **$72.90** | **$291.21** |
| B2B listings page | 112 | — | — | — |
| `search_listings` (the API) | 112 | — | $89.35 | — |
| `mcp_sync_listings`, broadcast to B2B | 136 | 596 | $72.00 | $500.02 |
| `mcp_sync_listings`, all | 148 | 639 | $72.00 | $482.39 |
| `mcp_sync_listings`, zone rows only | 101 | 470 | $72.00 | $557.29 |
| `mcp_sync_listings`, seated only | 47 | 169 | $85.04 | $274.08 |
| `mcp_lysted_listings`, all | 106 | 687 | $85.87 | $177.57 |
| `mcp_lysted_listings`, on sale | 98 | 666 | $85.87 | $173.74 |

The API and the listings page agree with each other (112) and disagree with the
event row, so the gap is **inside B2B**, not in the lake or in how it is
queried.

The likely cause is **zone listings**. Every row `search_listings` returns
carries `zone: false`, while `mcp_sync_listings` holds **101 zone rows** for
this event whose get-in is **$72.00** — within 1.25% of the event row's $72.90,
and cheap zone inventory is exactly what would pull a get-in down while the API
withholds it. Worth confirming with whoever owns that aggregate.

Two things to get right when computing these yourself:

- **ATP is ticket-weighted**: `sum(price * quantity) / sum(quantity)`. The plain
  mean of listing prices is a different and usually higher number
  ($237.83 vs $177.57 on the Lysted rows), so quoting the wrong one looks like
  a data problem when it is an arithmetic choice.
- **Exclude zero prices from a get-in.** `mcp_lysted_listings` carries
  `price = 0` rows; `min(price)` over them returns $0.00 and reads as the
  cheapest seat in the arena.

`mcp_sync_listing_broadcasts` is how you tell what went to B2B: it carries
`b2b_count` per `(company_id, exchange_pos_id)`, joinable to
`mcp_sync_listings.exchange_pos_id`.

## Result-size limit

The Datalake MCP spills a large answer to a file and returns the path instead of
the rows. Keep queries narrow (one game, one section, a `LIMIT`) and treat a
payload that is not JSON as "too large", not as data.

## 16. The four listing prices, and what Uptick's bounds mean

One ticket, four prices, cheapest first — each from a different place in the
chain, so they are not versions of one number:

| column | source | what it is |
|---|---|---|
| Uptick push | `mcp_uptick_pricing.push_price` | what the autopricer decided, **after** clamping to floor/ceiling |
| Lake list | `mcp_lysted_listings.price` | what the lake records the broker listing at |
| B2B shows | `search_listings` ÷ 1.03 | the figure on the B2B screen |
| B2B connector | `search_listings.price` | what the API returns, 3% above the screen |

Push and lake list agree wherever the autopricer is driving the listing — that
is Uptick writing the price the lake then records. The step from lake list to
B2B is the marketplace's per-listing markup (§14), which happens **outside
Uptick**: a B2B price above the floor is the marketplace's doing, not the
autopricer's.

### `cmp`, floor and ceiling

Per the columns' own documentation:

- **`cmp`** is the **Calculated Market Price** — Uptick's live estimate of what
  the seat is worth, computed **ignoring** the floor and ceiling.
- **`floor`** / **`ceiling`** are the bounds configured for the listing.
  A ceiling of **0 means unset**, so treat it as null rather than as $0.
- **`push_price`** is `cmp` clamped into those bounds.

That makes two states worth separating, which a plain "is push at the floor"
test conflates:

| state | reading |
|---|---|
| push > floor | the autopricer is free; push tracks `cmp` |
| push == floor **and** `cmp` < floor | **the floor is binding** — Uptick wanted to go lower and was stopped |
| push == floor and `cmp` >= floor | it merely sits on the floor |

Worked example, section 101 row T on 2026-10-28: `cmp` **$196.83**, floor
**$210.00**, push **$210.00**, displayed on B2B at **$225.16**. The floor held
it $13 above Uptick's own market estimate, and the marketplace markup then put
the visible price $28 above that. Section 124 row K is the extreme version:
floor **$1,625.48** against a `cmp` of **$246.33**.

### Guard the pricing join

`mcp_uptick_pricing`'s grain is **`(listing_id, account_id)`** with a
`component_type_id`, and its docs say `listing_id` is not unique on its own. It
is 1:1 for the games checked (84 of 84 listings with exactly one row), but a
group or split pricing component would fan a listing table out silently.
Collapse it per listing — `argMax(..., calculated_at)` — and carry `count()`
through so a fan-out is visible instead of duplicating rows.

`calculated_at` also moves during the day (13:00 and 16:00 UTC observed on the
same date), so it is not strictly a once-daily dump; it is still a snapshot, and
every row in one pull shares its timestamp.
