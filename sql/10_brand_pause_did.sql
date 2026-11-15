-- 10 Quasi-experiment: Microsoft Ads brand campaigns paused in France (2026-02-02 to 2026-03-29)
-- Question: are brand ads buying claims we would get anyway through organic search?
-- Outcome: weekly claims arriving through "brand demand" (Microsoft brand + SEO). Treated = FR, control = UK, DE, ES, IT.
-- Difference-in-differences = (FR pause - FR before) - (control pause - control before). Regression version in the notebook.
-- BigQuery note: same SQL; DATE_TRUNC(d, WEEK(MONDAY)).
WITH w AS (
  SELECT date_trunc('week', CAST(created_at AS DATE)) AS wk, market,
         SUM(CASE WHEN traffic_source = 'microsoft_ads' AND campaign_type = 'brand' THEN 1 ELSE 0 END) AS ms_brand_claims,
         SUM(CASE WHEN traffic_source = 'seo' THEN 1 ELSE 0 END) AS seo_claims
  FROM claims
  WHERE claim_id NOT LIKE 'CLD%' AND market IN ('FR', 'UK', 'DE', 'ES', 'IT')
    AND CAST(created_at AS DATE) BETWEEN DATE '2025-11-03' AND DATE '2026-03-29'
  GROUP BY 1, 2
)
SELECT CASE WHEN market = 'FR' THEN 'treated (FR)' ELSE 'control' END AS grp,
       CASE WHEN wk >= DATE '2026-02-02' THEN 'pause' ELSE 'before' END AS period,
       COUNT(DISTINCT wk) AS weeks,
       ROUND(AVG(ms_brand_claims), 1) AS ms_brand_per_week,
       ROUND(AVG(seo_claims), 1) AS seo_per_week,
       ROUND(AVG(ms_brand_claims + seo_claims), 1) AS brand_demand_per_week
FROM w
GROUP BY 1, 2
ORDER BY 1 DESC, 2;
