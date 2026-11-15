-- 08 First-response acceptance by (fictional) carrier and month, with the change vs the previous 3 months
-- Question for Legal and Ops: whose answers changed, and since when? A drop is a signal to investigate, not a verdict.
-- Grain: carrier x month of the airline's response. Only claims with a response are counted.
-- BigQuery note: AVG(...) OVER (... ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING) is identical in BigQuery.
WITH m AS (
  SELECT carrier, date_trunc('month', airline_response_at) AS m,
         COUNT(*) AS responses,
         AVG(CASE WHEN first_response = 'accepted' THEN 1.0 ELSE 0 END) AS acceptance
  FROM claims
  WHERE airline_response_at IS NOT NULL AND claim_id NOT LIKE 'CLD%'
  GROUP BY 1, 2
)
SELECT carrier, m, responses, ROUND(acceptance, 3) AS acceptance,
       ROUND(AVG(acceptance) OVER (PARTITION BY carrier ORDER BY m ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING), 3) AS prev_3m,
       ROUND(acceptance - AVG(acceptance) OVER (PARTITION BY carrier ORDER BY m ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING), 3) AS change_pts
FROM m
ORDER BY carrier, m;
