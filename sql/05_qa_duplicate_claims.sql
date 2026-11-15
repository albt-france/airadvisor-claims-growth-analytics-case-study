-- 05 Data quality: duplicate claims (same customer, route, type and amount, created within 5 minutes)
-- Question: are some claims counted twice? Duplicates inflate claims, revenue forecasts and CAC denominators.
-- Window function LAG compares each claim with the previous claim that has the same key.
-- BigQuery note: TIMESTAMP_DIFF(created_at, prev_created_at, SECOND) replaces date_diff('second', ...).
WITH ordered AS (
  SELECT claim_id, customer_id, route, claim_type, amount_due_eur, created_at,
         LAG(created_at) OVER (PARTITION BY customer_id, route, claim_type, amount_due_eur ORDER BY created_at) AS prev_created_at,
         LAG(claim_id)   OVER (PARTITION BY customer_id, route, claim_type, amount_due_eur ORDER BY created_at) AS prev_claim_id
  FROM claims
)
SELECT CAST(created_at AS DATE) AS d, COUNT(*) AS duplicate_claims,
       MIN(claim_id) AS example_duplicate, MIN(prev_claim_id) AS example_original
FROM ordered
WHERE prev_created_at IS NOT NULL
  AND date_diff('second', prev_created_at, created_at) <= 300
GROUP BY 1
ORDER BY duplicate_claims DESC;
