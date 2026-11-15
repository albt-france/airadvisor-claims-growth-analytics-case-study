-- 11 Fee-display A/B test (2026-06-01 to 2026-07-12): sample ratio check before reading any result
-- Question: did each variant receive the 50/50 split the server assigned? If not, the raw comparison is biased.
-- Compares GA4 exposures (logged in the browser) with server assignments, by device.
-- BigQuery note: the variant is an event parameter in GA4: (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'variant').
WITH ga AS (
  SELECT device_category, experiment_variant AS variant, COUNT(DISTINCT ga_session_id) AS ga_exposures
  FROM events WHERE event_name = 'experiment_exposure' GROUP BY 1, 2
), srv AS (
  SELECT device_category, variant, COUNT(*) AS server_assignments
  FROM experiment_assignments GROUP BY 1, 2
)
SELECT srv.device_category, srv.variant, server_assignments, ga_exposures,
       ROUND(ga_exposures * 1.0 / SUM(ga_exposures) OVER (PARTITION BY srv.device_category), 4) AS ga_share,
       ROUND(server_assignments * 1.0 / SUM(server_assignments) OVER (PARTITION BY srv.device_category), 4) AS server_share
FROM srv JOIN ga USING (device_category, variant)
ORDER BY srv.device_category, srv.variant;
