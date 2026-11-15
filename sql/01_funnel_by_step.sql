-- 01 Funnel by step and device (GA4 events, consented sessions only)
-- Question: where do visitors drop between landing and signing the claim documents?
-- Grain: one row per device. A session counts once per step (COUNT DISTINCT ga_session_id).
-- BigQuery note: in the raw GA4 export the session id sits in event_params; flatten it with
--   (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id'), and filter the
--   date-sharded tables with _TABLE_SUFFIX BETWEEN '20250501' AND '20261031' to limit bytes scanned.
WITH steps AS (
  SELECT device_category,
         COUNT(DISTINCT CASE WHEN event_name = 'session_start'     THEN ga_session_id END) AS sessions,
         COUNT(DISTINCT CASE WHEN event_name = 'eligibility_check' THEN ga_session_id END) AS checks,
         COUNT(DISTINCT CASE WHEN event_name = 'claim_start'       THEN ga_session_id END) AS starts,
         COUNT(DISTINCT CASE WHEN event_name = 'claim_submit'      THEN ga_session_id END) AS submits,
         COUNT(DISTINCT CASE WHEN event_name = 'document_signed'   THEN ga_session_id END) AS signed
  FROM events
  WHERE event_date < DATE '2026-09-15'          -- before the mobile tag break (see 03)
  GROUP BY device_category
)
SELECT device_category, sessions, checks, starts, submits, signed,
       ROUND(checks  / NULLIF(sessions, 0), 4) AS check_rate,
       ROUND(starts  / NULLIF(checks, 0), 4)   AS start_rate,
       ROUND(submits / NULLIF(starts, 0), 4)   AS submit_rate,
       ROUND(signed  / NULLIF(submits, 0), 4)  AS sign_rate,
       ROUND(submits / NULLIF(sessions, 0), 4) AS session_to_submit
FROM steps
ORDER BY sessions DESC;
