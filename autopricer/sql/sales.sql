-- Realised sales for Timberwolves 2026-27 home games, at section/row grain.
--
-- mcp_sales rows are per-invoice-line and already aggregated by seat block, so
-- total_sales / total_qty is the per-ticket price. Rows from all four POS
-- systems are kept: they are different brokers' sales, not duplicates of each
-- other.
--
-- total_cost is passed through as-is. Roughly half the rows carry 0, which
-- means "this POS did not capture cost", not a free ticket -- the loader
-- treats 0 as unknown rather than as 100% margin.
--
-- Produces: data/raw/sales.tsv
--   event_date  section  row  qty  price  cost  invoice_date  sale_type

WITH tw AS (
  SELECT id, toString(date_of_event) AS event_date
  FROM mcp_events
  WHERE venue LIKE 'Target Center%'
    AND date_of_event BETWEEN '2026-10-01' AND '2027-06-30'
    AND lower(name) LIKE '%timberwolves%'
    AND lower(name) NOT LIKE '%parking%'
    AND lower(name) NOT LIKE '%season tickets%'
    AND lower(name) NOT LIKE '%tbd%'
)
SELECT
  tw.event_date                                            AS event_date,
  ifNull(s.section, '')                                    AS section,
  ifNull(s.row, '')                                        AS row,
  s.total_qty                                              AS qty,
  round(s.total_sales / s.total_qty, 2)                     AS price,
  round(ifNull(s.total_cost, 0) / s.total_qty, 2)           AS cost,
  toString(s.invoice_date)                                 AS invoice_date,
  ifNull(s.type, '')                                       AS sale_type
FROM mcp_sales s
INNER JOIN tw ON s.event_id = tw.id
WHERE s.total_qty > 0
  AND s.total_sales > 0
ORDER BY tw.event_date, s.invoice_date, s.section, s.row
