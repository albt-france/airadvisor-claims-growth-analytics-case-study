-- 06 Attribution check: conversions reported by each ad platform vs claims recorded in the CRM (last click, UTM)
-- Question: can we add up platform conversions? No: each platform credits itself (view-through, own window).
-- BigQuery note: platform tables come from the Google Ads / Meta / Microsoft Ads transfers (Data Transfer Service
--   or a connector); join on date and a cleaned campaign key, never on campaign names typed by hand.
WITH plat AS (
  SELECT date_trunc('month', date) AS m, platform, SUM(spend_eur) AS spend, SUM(platform_conversions) AS reported
  FROM ad_spend GROUP BY 1, 2
), crm AS (
  SELECT date_trunc('month', CAST(created_at AS DATE)) AS m, traffic_source AS platform, COUNT(*) AS crm_claims
  FROM claims WHERE claim_id NOT LIKE 'CLD%' AND traffic_source IN ('google_ads', 'meta_ads', 'microsoft_ads')
  GROUP BY 1, 2
)
SELECT plat.m, plat.platform, ROUND(spend, 0) AS spend_eur, reported, crm_claims,
       ROUND(reported / NULLIF(crm_claims, 0), 2) AS over_reporting_factor,
       SUM(reported)   OVER (PARTITION BY plat.m) AS all_platforms_reported,
       SUM(crm_claims) OVER (PARTITION BY plat.m) AS all_paid_crm_claims
FROM plat JOIN crm USING (m, platform)
ORDER BY plat.m, plat.platform;
