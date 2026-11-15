-- 02 Submit rate by country x traffic source (GA4) next to the CRM, summer 2026 (before the tag break)
-- Question: which segments turn visitors into submitted claims, and does GA4 still cover the CRM in each segment?
-- BigQuery note: identical SQL works on a flattened GA4 view; GROUP BY ROLLUP(country, traffic_source) adds totals.
WITH ga AS (
  SELECT country, traffic_source,
         COUNT(DISTINCT CASE WHEN event_name = 'session_start' THEN ga_session_id END) AS ga_sessions,
         COUNT(DISTINCT CASE WHEN event_name = 'claim_submit'  THEN ga_session_id END) AS ga_submits
  FROM events
  WHERE event_date BETWEEN DATE '2026-06-01' AND DATE '2026-08-31'
  GROUP BY country, traffic_source
), crm AS (
  SELECT market AS country, traffic_source, COUNT(*) AS crm_claims
  FROM claims
  WHERE claim_id NOT LIKE 'CLD%'                          -- known duplicates excluded (see 05)
    AND CAST(created_at AS DATE) BETWEEN DATE '2026-06-01' AND DATE '2026-08-31'
  GROUP BY market, traffic_source
)
SELECT ga.country, ga.traffic_source, ga_sessions, ga_submits, crm_claims,
       ROUND(ga_submits / NULLIF(ga_sessions, 0), 4) AS ga_submit_rate,
       ROUND(ga_submits / NULLIF(crm_claims, 0), 3)  AS ga_coverage_of_crm,   -- ~ consent rate when tracking is healthy
       RANK() OVER (PARTITION BY ga.country ORDER BY ga_submits / NULLIF(ga_sessions, 0) DESC) AS rank_in_country
FROM ga JOIN crm USING (country, traffic_source)
ORDER BY ga.country, rank_in_country;
