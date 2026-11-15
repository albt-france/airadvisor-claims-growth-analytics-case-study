-- 13 Monthly KPI scorecard (definitions in docs/KPI_DICTIONARY.md)
-- One row per month: the shared numbers every team reads. Acceptance and revenue per claim lag: only mature months are final.
-- BigQuery note: build it as a view on the partitioned tables; Looker Studio reads the view directly.
WITH ga AS (
  SELECT date_trunc('month', event_date) AS m,
         COUNT(DISTINCT CASE WHEN event_name = 'session_start' THEN ga_session_id END) AS ga_sessions,
         COUNT(DISTINCT CASE WHEN event_name = 'eligibility_check' THEN ga_session_id END) AS ga_checks
  FROM events GROUP BY 1
), crm AS (
  SELECT date_trunc('month', CAST(created_at AS DATE)) AS m, COUNT(*) AS claims,
         AVG(amount_due_eur) AS avg_claim_value,
         SUM(CASE WHEN first_response = 'accepted' THEN 1 ELSE 0 END) * 1.0
           / NULLIF(SUM(CASE WHEN first_response IS NOT NULL THEN 1 ELSE 0 END), 0) AS first_response_acceptance,
         SUM(revenue_eur) AS revenue_to_date
  FROM claims WHERE claim_id NOT LIKE 'CLD%' GROUP BY 1
), sp AS (
  SELECT date_trunc('month', date) AS m, SUM(spend_eur) AS spend FROM ad_spend GROUP BY 1
), paid AS (
  SELECT date_trunc('month', CAST(created_at AS DATE)) AS m, COUNT(*) AS paid_channel_claims
  FROM claims WHERE claim_id NOT LIKE 'CLD%' AND traffic_source IN ('google_ads', 'meta_ads', 'microsoft_ads') GROUP BY 1
)
SELECT crm.m, ga_sessions, claims,
       ROUND(ga_checks / NULLIF(ga_sessions, 0), 3) AS check_rate,
       ROUND(avg_claim_value, 0) AS avg_claim_value_eur,
       ROUND(first_response_acceptance, 3) AS first_response_acceptance,
       ROUND(revenue_to_date / NULLIF(claims, 0), 1) AS revenue_per_claim_to_date,
       ROUND(spend / NULLIF(paid_channel_claims, 0), 1) AS paid_cac_per_claim,
       ROUND(spend, 0) AS spend_eur
FROM crm LEFT JOIN ga USING (m) LEFT JOIN sp USING (m) LEFT JOIN paid USING (m)
ORDER BY crm.m;
