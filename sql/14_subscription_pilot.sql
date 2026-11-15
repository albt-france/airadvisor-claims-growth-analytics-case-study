-- 14 Annual subscription pilot (UK + DE, June-October 2026): take-up and early churn signals by price tier
-- Question: which price converts, who subscribes (frequent flyers?), and how many already plan not to renew?
-- BigQuery note: same SQL; CAST(subscribed AS INT64) if you prefer AVG over a boolean.
SELECT tier, price_eur, COUNT(*) AS offers,
       SUM(CASE WHEN subscribed THEN 1 ELSE 0 END) AS subscribers,
       ROUND(AVG(CASE WHEN subscribed THEN 1.0 ELSE 0 END), 4) AS take_up,
       ROUND(AVG(declared_trips_per_year), 2) AS trips_all_offered,
       ROUND(AVG(CASE WHEN subscribed THEN declared_trips_per_year END), 2) AS trips_subscribers,
       ROUND(AVG(CASE WHEN subscribed THEN CASE WHEN cooling_off_cancelled THEN 1.0 ELSE 0 END END), 3) AS cooling_off_rate,
       ROUND(AVG(CASE WHEN subscribed AND NOT cooling_off_cancelled THEN CASE WHEN auto_renew_off_at IS NOT NULL THEN 1.0 ELSE 0 END END), 3) AS renewal_off_rate,
       SUM(covered_claims) AS covered_claims
FROM subscriptions_test
GROUP BY tier, price_eur
ORDER BY price_eur;
