-- 09 Customer cohorts: cumulative revenue per customer by months since the first claim (commission LTV)
-- Question: how much is a new claimant worth over time, including repeat claims?
-- Revenue is booked on paid_at (cash view). Young cohorts are incomplete: compare cohorts at the same age only.
-- BigQuery note: DATE_DIFF(paid_month, cohort_month, MONTH) replaces date_diff('month', ...).
WITH firsts AS (
  SELECT customer_id, date_trunc('month', MIN(created_at)) AS cohort
  FROM claims WHERE claim_id NOT LIKE 'CLD%' GROUP BY 1
), rev AS (
  SELECT c.customer_id, f.cohort, date_diff('month', f.cohort, date_trunc('month', c.paid_at)) AS age, c.revenue_eur
  FROM claims c JOIN firsts f USING (customer_id)
  WHERE c.paid_at IS NOT NULL AND c.claim_id NOT LIKE 'CLD%'
), sizes AS (SELECT cohort, COUNT(*) AS customers FROM firsts GROUP BY 1),
grid AS (SELECT cohort, age, SUM(revenue_eur) AS revenue FROM rev GROUP BY 1, 2)
SELECT g.cohort, s.customers, g.age,
       ROUND(SUM(g.revenue) OVER (PARTITION BY g.cohort ORDER BY g.age) / s.customers, 2) AS cum_revenue_per_customer
FROM grid g JOIN sizes s USING (cohort)
ORDER BY g.cohort, g.age;
