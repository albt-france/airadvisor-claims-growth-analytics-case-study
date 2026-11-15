# Assumptions

## Market model (`src/build_public.py`, PUBLIC DATA + assumptions)
| Step | Value (central, low-high) | Why |
|---|---|---|
| Disruption share per country | CAA 2025: share of flights 181+ min late (of operated) + cancelled (of planned) on routes between the UK and that country, shrunk toward the European mean with a weight of 3,000 flights | only public source with 3h+ delay bands by partner country; small countries have few flights |
| Passengers on cancelled flights | carried passengers x p_cancel / (1 - p_cancel) | carried passengers exclude cancelled flights |
| Long-haul 3-4 h delays | amount halved for 46% of 3h+ long-haul delays (BTS 2025 share of 3h+ delays that are 3-4 h) | EU261 Art. 7(2)(c) as applied by the courts; CAA £260 rule |
| Share within the airline's control | 55% (40-70%) | BTS 2025: carrier-caused minutes are 39% of 3h+ delay minutes, a lower bound (part of the "late aircraft" category is also the carrier's) |
| Claim rate | 35% (20-50%) | share of eligible passengers who claim at all; no official statistic |
| Agency share | 45% (30-60%) | share of claims filed through agencies rather than directly |
| Airline payout rate on agency claims | 85% (75-95%) | agencies pre-screen claims |
| Fee | 30% (25-35%) | AirAdvisor's published fee (low/high bracket competitors' published fees) |
| Obtainable share | 12% (6-20%) | share of the agency market one player can win |
| Variable cost | 30% of revenue | ops + legal; gives break-even CAC and break-even ROAS 1.43 |
| UK departures | half of CAA terminal passengers per route | CAA counts both directions |
| Czechia | national total / 2 x European average per passenger | no Eurostat airport-pair table |

The theoretical ceiling assumes every disruption is the airline's responsibility and every passenger claims. It is a maximum, not money owed.

## Simulation (`src/simulate.py`, SIMULATED, seed 42, 1 May 2025 - 31 Oct 2026)
- 6 markets (UK, DE, FR, ES, IT, NL; NL opens on 1 April 2026 = month 12), 4 claim types, 3 devices, 9 source/campaign pairs over 6 sources.
- Volumes scaled down (about 1M sessions, 90K claims). Seasonality = CAA 2025 monthly flights x half of the monthly disruption swing; +1.2% growth a month; random strike/storm days.
- Funnel rates by device and source (check 27-60%, eligible 52-66%, start 51-60%, submit 57-70%, signed 86%). Meta and organic social bring weaker cases (validation 76-80% vs 88%).
- Routes are sampled from real Eurostat airport pairs of each market, so distances and EU261/UK261 bands are realistic. Carriers are fictional ("Carrier A-L").
- Lifecycle: sent 2-10 days after submission, airline answer 20-75 days later, 62% of rejections escalated, 74% won in 120-300 days, payment 10-40 days after acceptance. Fee 30% (flight), 40% (baggage), 50% (won in court).
- Ad platforms: CPC by campaign type; reported conversions = CRM claims x 1.12 (Google), 2.05 (Meta), 1.18 (Microsoft).
- Subscription pilot (UK + DE, from 1 June 2026): three tiers at €29 / €49 / €79 a year, random tier per offer; take-up falls with price and rises with declared trips; covered claims use 2 flights per trip x 1.3% eligible disruption per flight.

## The 8 planted events (answer key: `data/_hidden_truth.csv`, read only by the last step of `src/analysis.py`)
1. Mobile `claim_submit` stops on 15 Sep 2026. 2. German consent banner on 16 Feb 2026 (consent 63% → 47%). 3. Platforms over-report conversions. 4. Microsoft brand paused in France 2 Feb - 29 Mar 2026, 88% of its sessions come back through SEO. 5. Fee-display A/B test (1 Jun - 12 Jul 2026) with 14% of low-intent mobile B users not logged; true effect about zero. 6. Carrier H first-response acceptance 62% → 30% from May 2026. 7. Summer peak = normal seasonality. 8. 186 duplicated claims on 20 Jan 2026.

## Subscription pricing (`src/analysis.py`)
- Eligible disruption per flight = public disrupted share (1.37%) x 55% airline control = 0.75%; average amount €335 (public model).
- Baggage: 6 mishandled bags per 1,000 passenger-flights, 40% lead to a valid claim, €450 average (assumptions).
- Cost of a covered claim: €35 handling; with full cannibalisation, plus the commission the customer would have paid anyway (30% / 40%). Margin uses the midpoint (50% cannibalisation) and 3% payment fees.
- Churn: share of subscribers who turned auto-renew off, annualised with a constant hazard. The pilot is 2-5 months old, so renewal is a projection.
