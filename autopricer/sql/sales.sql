-- Realised sales for Timberwolves 2026-27 home games, at section/row grain.
--
-- mcp_sales rows are per-invoice-line and already aggregated by seat block, so
-- dividing by total_qty gives a per-ticket figure.
--
-- TWO sale totals come back and they are not the same number:
--   total_sales      gross -- what the buyer paid, including exchange fees
--   total_sales_ost  Order Sold Total -- the broker's side of the same sale.
--                    THIS IS WHAT UPTICK DISPLAYS.
-- On this data they disagree by a few per cent in both directions, and OST is
-- 0 on 59% of rows, so the model prices off gross and carries OST alongside
-- for reconciliation. See the README. Rows from all four POS
-- systems are kept: they are different brokers' sales, not duplicates of each
-- other.
--
-- total_cost is passed through as-is. Roughly half the rows carry 0, which
-- means "this POS did not capture cost", not a free ticket -- the loader
-- treats 0 as unknown rather than as 100% margin.
--
-- Produces: data/raw/sales.tsv
--   event_date  section  row  qty  price  net  cost  invoice_date  sale_type
--   marketplace

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
  round(ifNull(s.total_sales_ost, 0) / s.total_qty, 2)      AS net,
  round(ifNull(s.total_cost, 0) / s.total_qty, 2)           AS cost,
  toString(s.invoice_date)                                 AS invoice_date,
  ifNull(s.type, '')                                       AS sale_type,
  ifNull(s.ms_company_name, '')                            AS marketplace
FROM mcp_sales s
INNER JOIN tw ON s.event_id = tw.id
WHERE s.total_qty > 0
  AND s.total_sales > 0
ORDER BY tw.event_date, s.invoice_date, s.section, s.row
