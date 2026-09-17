-- The current active VividSeats board for Timberwolves 2026-27 home games.
--
-- Of the five prism marketplace tables, only vividseats covers these events
-- (seatgeek, ticketmaster and stubhub return zero rows for them), so it is the
-- single listings source. Its event_id joins mcp_events.vsexchangeeventid.
--
-- `is_active` plus the latest processed_date gives the live board; inactive
-- rows are listings that have since come down. `price` is the per-ticket ask
-- before buyer fees, which is the number a broker sets -- all_in_price_per_ticket
-- runs about 1.31x higher and is what a buyer is quoted.
--
-- The section label is normalised here only to strip the bowl prefix
-- ("Lower Level 112" -> "112"); autopricer.normalize does the same job on both
-- sides at load time, so a change of mind belongs there, not here.
--
-- This query returns ~10k rows. It is grouped into one row per event+section
-- with the listings packed into a single string, which keeps the result small
-- enough to move in one piece; scripts/REFRESH.md shows the unpacking.
--
-- Produces: data/raw/listings.tsv
--   event_date  section  row  price  qty  view_score

WITH ev AS (
  SELECT DISTINCT
    vsexchangeeventid                AS xid,
    toString(date_of_event)          AS event_date
  FROM mcp_events
  WHERE venue LIKE 'Target Center%'
    AND date_of_event BETWEEN '2026-10-01' AND '2027-06-30'
    AND lower(name) LIKE '%timberwolves%'
    AND lower(name) NOT LIKE '%parking%'
    AND lower(name) NOT LIKE '%season tickets%'
    AND lower(name) NOT LIKE '%tbd%'
    AND vsexchangeeventid IS NOT NULL
)
SELECT
  event_date,
  section,
  arrayStringConcat(groupArray(tuple_), ';') AS listings
FROM (
  SELECT
    ev.event_date AS event_date,
    replaceRegexpOne(
      replaceRegexpOne(l.section,
        '^(Lower Level|Upper Level|Club Level|Suite Level)\\s+', ''),
      '^0+', '')                                           AS section,
    concat(
      upper(ifNull(l.row, '?')), ':',
      toString(toInt32(toFloat64OrNull(l.price))), ':',
      toString(ifNull(toInt32OrNull(l.quantity), 0)), ':',
      -- view score carried as an integer tenth to keep the payload compact
      ifNull(toString(toInt32(round(toFloat64OrNull(l.section_view_score) * 10))), '')
    )                                                      AS tuple_,
    toFloat64OrNull(l.price)                               AS px
  FROM mcp_prism_vividseats_event_listings l
  INNER JOIN ev ON l.event_id = ev.xid
  WHERE l.is_active
    AND l.processed_date = (
      SELECT max(processed_date)
      FROM mcp_prism_vividseats_event_listings
      WHERE is_active
    )
    AND toFloat64OrNull(l.price) > 0
  ORDER BY event_date, section, px
)
GROUP BY event_date, section
ORDER BY event_date, section
