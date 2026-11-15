# KPI dictionary: one definition per number

Every dashboard, report and test reads these definitions. A KPI changes only through this file (pull request, reviewed by the owner).
Tables: `events` (GA4 export), `claims` (CRM), `ad_spend` (ad platforms), `subscriptions_test`. SQL is DuckDB, written to port to BigQuery (see `sql/`).
Example values come from the SIMULATED dataset; they are not AirAdvisor figures.

| # | KPI | Definition | Formula (SQL) | Source of truth | Owner | Pitfalls |
|---|---|---|---|---|---|---|
| 1 | **Sessions** | Visits with analytics consent | `COUNT(DISTINCT ga_session_id) WHERE event_name='session_start'` | GA4 | Marketing analytics | Only consented visitors: compare trends, not levels, across countries with different consent rates |
| 2 | **Eligibility check rate** | Share of sessions that run the compensation checker | `checks / sessions` | GA4 | Product | Bots and internal traffic inflate sessions: filter them in GA4 first |
| 3 | **Claim start rate** | Share of checks that start a claim form | `starts / checks` | GA4 | Product | Depends on how many checks are eligible: segment by claim type |
| 4 | **Claim submit rate** | Share of started claims that are submitted | `submits / starts` | GA4 (trend), CRM (level) | Product | Read GA4 only after the daily GA4/CRM QA check (`sql/03`) passes |
| 5 | **Submitted claims** | Claims recorded in the CRM, duplicates removed | `COUNT(*) FROM claims WHERE claim_id NOT LIKE 'CLD%'` (in production: dedup rule of `sql/05`) | CRM | Data owner | Never use GA4 `claim_submit` as the business count: consent and tag breaks hide claims |
| 6 | **Signed rate** | Share of submitted claims with documents signed (power of attorney / assignment) | `SUM(document_signed) / COUNT(*)` | CRM | Ops | Unsigned claims cannot be sent: they are not revenue |
| 7 | **Validation rate** | Share of signed claims that pass internal checks and are sent to the airline | `sent / signed` | CRM | Legal & Ops | Falls when traffic quality falls (e.g. social campaigns) |
| 8 | **First-response acceptance rate** | Share of airline first answers that accept the claim | `accepted / (accepted + rejected)` by month of response | CRM | Legal | Use the month of the **response**, not of the claim; small carriers: show the sample size |
| 9 | **Success rate (final)** | Share of sent claims finally paid (after escalation) | `paid / sent`, cohort by creation month | CRM | Legal | Right-censored: a cohort is final only 12-18 months later. Compare cohorts at the same age |
| 10 | **Average claim value** | Compensation due per claim (all passengers) | `AVG(amount_due_eur)` | CRM | Finance | Mixes 1-4 passengers and distance bands: also report per passenger |
| 11 | **Revenue per claim** | Fees earned per submitted claim, mature cohorts | `SUM(revenue_eur) / COUNT(*)` for claims 12+ months old | CRM | Finance | Recent months look worse only because they are not paid yet |
| 12 | **Revenue per visitor (RPV)** | Expected revenue per consented session | `submitted claims x revenue per claim / sessions` | GA4 + CRM | Marketing analytics | Use consent-adjusted sessions when comparing countries |
| 13 | **CAC (paid)** | Ad spend per claim from paid channels | `SUM(spend) / COUNT(claims from paid channels)` | Ad platforms + CRM | Marketing | Never divide by platform-reported conversions (they over-count, `sql/06`). Also show CAC per **paid** claim |
| 14 | **Incremental CAC** | Spend per claim that would not have happened without the ad | `CAC / incrementality` (incrementality from a test or quasi-experiment) | Tests | Marketing analytics | Brand search usually has low incrementality: measure it before scaling |
| 15 | **ROAS** | Revenue earned per euro of spend | `revenue of claims from the channel / spend` | CRM + ad platforms | Marketing | Break-even ROAS = 1 / (1 - variable cost share), 1.43 with a 30% variable cost |
| 16 | **Commission LTV (12 months)** | Revenue per new customer over 12 months, repeat claims included | cohort query `sql/09` | CRM | Finance | Booked on payment date: young cohorts are incomplete |
| 17 | **Repeat-claim rate** | Share of customers who file a second claim | `customers with 2+ claims / customers` (12-month window) | CRM | CRM team | Needs a stable customer id across claims |
| 18 | **Subscription take-up** | Share of offers that convert to a subscription | `subscribers / offers` per tier | Subscriptions | Product | Different offer channels (post-claim vs website) have different intent |
| 19 | **Subscription churn** | Share of subscribers who do not renew | annual; early signal = auto-renew turned off | Subscriptions | Product | Pilot is younger than a year: projected churn is an assumption, flagged as such |

## Rules
- **One source per KPI.** GA4 is for behaviour and trends; the CRM is for claims and money; ad platforms are for spend only.
- **Mature vs to-date.** Any KPI that depends on airline answers or payments is shown with its cohort age.
- **Change control.** A new or changed definition = a pull request on this file + the SQL view, with the owner's approval.
