-- Canonical event dimension: one row per Timberwolves 2026-27 home game.
--
-- mcp_events is a union of per-POS catalogues, so the same game appears up to
-- four times (pos = 'vs', 'tn', 'in', 'oh') with a different id each. Grouping
-- by date collapses them: no two Timberwolves home games share a date, even
-- the back-to-back Portland pair on 2026-11-16 and 2026-11-17.
--
-- pos_event_ids is what mcp_sales.event_id joins against.
-- vs_xid is the VividSeats exchange id, which the prism listings join against.
--
-- Produces: data/raw/events.tsv
-- (opponent and game_type are derived from `name` by hand when writing the
-- TSV; game_type marks preseason / cup / marquee games.)

SELECT
  toString(date_of_event)                                  AS event_date,
  any(name)                                                AS label,
  groupUniqArray(id)                                       AS pos_event_ids,
  anyIf(vsexchangeeventid,
        vsexchangeeventid IS NOT NULL
        AND vsexchangeeventid != '')                       AS vs_xid,
  groupUniqArray(pos)                                      AS pos_list
FROM mcp_events
WHERE venue LIKE 'Target Center%'
  AND date_of_event BETWEEN '2026-10-01' AND '2027-06-30'
  AND lower(name) LIKE '%timberwolves%'
  -- Parking passes, full-season bundles and placeholder playoff rows are not
  -- single-seat inventory and must not be priced.
  AND lower(name) NOT LIKE '%parking%'
  AND lower(name) NOT LIKE '%season tickets%'
  AND lower(name) NOT LIKE '%tbd%'
GROUP BY date_of_event
ORDER BY date_of_event
