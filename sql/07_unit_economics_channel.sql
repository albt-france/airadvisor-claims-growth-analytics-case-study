-- 07 Unit economics by channel and country (claims created May-Oct 2025: old enough to be paid)
-- Question: what does a PAID claim cost per channel, and what does it bring back?
-- CAC per submitted claim flatters channels whose claims are weaker; CAC per paid claim does not.
-- BigQuery note: same SQL; partition claims by DATE(created_at) and cluster by market, traffic_source.
WITH c AS (
  SELECT market, traffic_source, COUNT(*) AS claims,
         SUM(CASE WHEN status NOT IN ('awaiting_documents', 'withdrawn', 'rejected_internal') THEN 1 ELSE 0 END) AS valid_claims,
         SUM(CASE WHEN status = 'paid' THEN 1 ELSE 0 END) AS paid_claims,
         SUM(revenue_eur) AS revenue
  FROM claims
  WHERE claim_id NOT LIKE 'CLD%' AND CAST(created_at AS DATE) BETWEEN DATE '2025-05-01' AND DATE '2025-10-31'
  GROUP BY 1, 2
), s AS (
  SELECT country AS market, platform AS traffic_source, SUM(spend_eur) AS spend
  FROM ad_spend WHERE date BETWEEN DATE '2025-05-01' AND DATE '2025-10-31'
  GROUP BY 1, 2
)
SELECT c.market, c.traffic_source, claims, valid_claims, paid_claims, ROUND(revenue, 0) AS revenue_eur,
       ROUND(COALESCE(spend, 0), 0) AS spend_eur,
       ROUND(spend / NULLIF(claims, 0), 1)      AS cac_per_claim,
       ROUND(spend / NULLIF(paid_claims, 0), 1) AS cac_per_paid_claim,
       ROUND(revenue / NULLIF(claims, 0), 1)    AS revenue_per_claim,
       ROUND(revenue / NULLIF(spend, 0), 2)     AS roas
FROM c LEFT JOIN s USING (market, traffic_source)
ORDER BY c.market, revenue_eur DESC;
