-- 03 Tracking QA: GA4 claim_submit vs CRM claims, per day and device, with an automatic alert
-- Question: is GA4 still seeing the claims the CRM records? A healthy ratio is stable (about the consent rate).
-- Alert rule: ratio below half of its own trailing 28-day median.
-- BigQuery note: MEDIAN is not a BigQuery aggregate; use PERCENTILE_CONT(ratio, 0.5) OVER (...) instead.
--   Run it as a daily scheduled query that writes to a qa_ table and sends an alert.
WITH ga AS (
  SELECT event_date AS d, device_category, COUNT(DISTINCT ga_session_id) AS ga_submits
  FROM events WHERE event_name = 'claim_submit' GROUP BY 1, 2
), crm AS (
  SELECT CAST(created_at AS DATE) AS d, device_category, COUNT(*) AS crm_claims
  FROM claims WHERE claim_id NOT LIKE 'CLD%' GROUP BY 1, 2
), daily AS (
  SELECT crm.d, crm.device_category, crm_claims, COALESCE(ga_submits, 0) AS ga_submits,
         COALESCE(ga_submits, 0) / NULLIF(crm_claims, 0) AS ratio
  FROM crm LEFT JOIN ga USING (d, device_category)
), scored AS (
  SELECT *, MEDIAN(ratio) OVER (PARTITION BY device_category ORDER BY d
                                ROWS BETWEEN 28 PRECEDING AND 1 PRECEDING) AS ratio_median_28d
  FROM daily
)
SELECT d, device_category, crm_claims, ga_submits, ROUND(ratio, 3) AS ratio, ROUND(ratio_median_28d, 3) AS ratio_median_28d,
       CASE WHEN ratio < 0.5 * ratio_median_28d THEN 'ALERT' ELSE 'ok' END AS status
FROM scored
ORDER BY d, device_category;
