-- 12 Is the summer peak a problem? Monthly claims vs the same month last year and vs the public seasonal index
-- Question: claims jumped in July; is that growth, a problem, or just the season?
-- pub_seasonality_uk_2025 = CAA 2025 monthly flights and disruptions (PUBLIC DATA).
-- BigQuery note: LAG(claims, 12) OVER (ORDER BY m) works the same; EXTRACT(MONTH FROM m) is portable.
WITH m AS (
  SELECT date_trunc('month', CAST(created_at AS DATE)) AS m, COUNT(*) AS claims
  FROM claims WHERE claim_id NOT LIKE 'CLD%' AND market <> 'NL'          -- NL opened in April 2026: excluded for like-for-like
  GROUP BY 1
)
SELECT m.m, claims,
       LAG(claims, 1)  OVER (ORDER BY m.m) AS prev_month,
       LAG(claims, 12) OVER (ORDER BY m.m) AS same_month_last_year,
       ROUND(claims / NULLIF(LAG(claims, 12) OVER (ORDER BY m.m), 0) - 1, 3) AS yoy_growth,
       ROUND(s.index_flights, 3) AS caa_flights_index, ROUND(s.index_disrupted, 3) AS caa_disruption_index
FROM m LEFT JOIN pub_seasonality_uk_2025 s ON s.month = EXTRACT(MONTH FROM m.m)
ORDER BY m.m;
