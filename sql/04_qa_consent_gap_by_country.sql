-- 04 Tracking QA: weekly GA4 coverage of CRM claims by country (consent gap)
-- Question: did measured conversions fall because of real demand or because fewer visitors accept analytics cookies?
-- If GA4 falls while the CRM does not, the loss is in measurement (Consent Mode), not in the business.
-- BigQuery note: DATE_TRUNC(d, WEEK(MONDAY)) in BigQuery vs date_trunc('week', d) in DuckDB.
WITH ga AS (
  SELECT date_trunc('week', event_date) AS wk, country, COUNT(DISTINCT ga_session_id) AS ga_submits
  FROM events WHERE event_name = 'claim_submit' AND device_category <> 'mobile'   -- mobile excluded: tag break, see 03
  GROUP BY 1, 2
), crm AS (
  SELECT date_trunc('week', CAST(created_at AS DATE)) AS wk, market AS country, COUNT(*) AS crm_claims
  FROM claims WHERE claim_id NOT LIKE 'CLD%' AND device_category <> 'mobile'
  GROUP BY 1, 2
)
SELECT crm.wk, crm.country, crm_claims, COALESCE(ga_submits, 0) AS ga_submits,
       ROUND(COALESCE(ga_submits, 0) / NULLIF(crm_claims, 0), 3) AS ga_coverage
FROM crm LEFT JOIN ga USING (wk, country)
ORDER BY crm.country, crm.wk;
