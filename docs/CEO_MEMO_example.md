# Memo to the CEO (example)

**From:** Business Insights · **Date:** 16 November 2026 · **Data:** public aviation data + a SIMULATED claim funnel (methods demo, not AirAdvisor figures)

## Recommendation
**Fix the mobile `claim_submit` tag before reading any funnel test. Stop Microsoft brand search and run the same pause on Google brand. Put the next local-growth euro into the Netherlands. Launch the subscription at €49 a year.**

## Three proofs
1. **The mobile tag is broken, the business is not.** Since the 15 September release, GA4 records no mobile claim submissions while the CRM keeps receiving them: 4,814 claims are invisible to GA4 and to every funnel report built on it. The daily GA4/CRM check flagged it on day one. Until it is fixed, any test that uses GA4 conversions on mobile is unreadable.
2. **Brand ads mostly buy claims we already have.** When Microsoft brand campaigns were paused in France for 8 weeks, total brand-search claims did not fall more than in the other countries (difference-in-differences +1.8 claims/week, 95% CI -5.0 to +8.6, versus 9.9 claims/week the ads were credited with). That spend (about €29K a year in the simulation) can stop now; Google brand (€86K) deserves the same test before any cut.
3. **The Netherlands is the next market after the big four.** Public data (Eurostat, UK CAA) puts a theoretical ceiling of about €4.0bn a year on EU261/UK261 compensation from European departures. After eligibility, claim rates and agency share, the obtainable revenue ranks the UK, Germany, France and Spain first, then the Netherlands. That order does not change under any of the sensitivity tests.

## Also on the radar
- **Fee-display test:** the "B wins by 9.6%" result is an artefact. Variant B lost low-intent mobile users before they were logged (sample ratio mismatch, p < 0.001). On the server assignment log the effect is -1.6% (not significant). Do not ship on this result.
- **Carrier H:** first-response acceptance fell from 63% to 30% since May, while 64% of its escalated rejections are still won. Legal should escalate this carrier faster and prepare a standard evidence pack.
- **Subscription pilot:** subscribers fly about 7 trips a year against 4 for everyone offered (self-selection). €49 keeps a margin for 9 in 10 subscribers; €29 only works with a cap on trips.

## Risks
- The market model multiplies public disruption data by assumptions (claim rate, agency share, obtainable share). The ranking is robust; the euro amounts are a range (€5M to €18M SOM).
- The ceiling is a maximum: flights disrupted by extraordinary circumstances (weather, air traffic control, security) owe nothing.
- The pause test ran in one country for 8 weeks: confirm it in a second market before cutting all brand spend.

## Next step (this week)
Engineering ships the tag fix and server-side `claim_submit`; I re-run the funnel and the fee test on CRM outcomes, and start the brand pause in Germany.
