# Sources, licences and collection dates (PUBLIC DATA)

All public data was collected on 2026-11-15 with `src/download_data.py` (one request at a time, pauses between requests, no login, no scraping of reviews). Raw files stay in `data/raw/` (not in git); small derived tables are in `data/public/`.

## AirAdvisor (facts it publishes)
| Fact | Value as stated by AirAdvisor | Where | Read on |
|---|---|---|---|
| Success fee, flight compensation (pre-trial, VAT included) | 30% | https://airadvisor.com/en/pricelist | 2026-11-15 |
| Fee if legal action with external lawyers | 50% | https://airadvisor.com/en/pricelist | 2026-11-15 |
| Fee, baggage and reimbursement claims | 40% | https://airadvisor.com/en (fees section) | 2026-11-15 |
| Cases handled | 830,000 | https://airadvisor.com/en | 2026-11-15 |
| Rating | 4.5/5 on 28,876 Reviews.io reviews (the job posting says 29,000+) | https://airadvisor.com/en | 2026-11-15 |
| Coverage | UK, EU, USA, Canada, international | https://airadvisor.com/en | 2026-11-15 |
| Other claims on the pricing page | 98% success rate, 9+ years, 14-day cooling-off period, no win no fee | https://airadvisor.com/en/pricelist | 2026-11-15 |
| Company profile (posting) | 221 countries, 21 languages, team in 18 countries, patented baggage process, annual subscription coming | LinkedIn job posting 4488987406 | 2026-11-15 |

Pages were opened by hand in a browser (automated requests are refused). Reviews were not collected.

## Rules (official texts)
| Rule | Content used | Source |
|---|---|---|
| EU261 (Regulation (EC) No 261/2004) | Art. 7: €250 (≤1,500 km), €400 (intra-Community >1,500 km and other 1,500-3,500 km), €600 (other); Art. 7(2) 50% reduction; Art. 3 scope; Art. 5(3) extraordinary circumstances | https://eur-lex.europa.eu/eli/reg/2004/261/oj (EUR-Lex was partly unavailable on 2026-11-15; amounts cross-checked on Your Europe) |
| EU261 delay right | "arrived at your final destination with a delay of 3 hours or more" → compensation unless extraordinary circumstances (CJEU case law, Sturgeon C-402/07) | https://europa.eu/youreurope/citizens/travel/passenger-rights/air/index_en.htm (last checked 21/09/2026) |
| UK261 | £220 (<1,500 km), £350 (1,500-3,500 km), £520 (>3,500 km; £260 if 3-4 h late) | https://www.caa.co.uk/air-passengers/travel-problems-and-rights/flight-delays-and-cancellations/delays/ |
| Canada APPR | Large airlines CAD 400 / 700 / 1,000 (3-6 h / 6-9 h / 9 h+); small airlines CAD 125 / 250 / 500; delay within the airline's control and not required for safety | https://protection-passager-passenger.otc-cta.gc.ca/en/refunds-and-compensation/flight-delays-cancellations-rebooking-refunds-compensation (modified 2026-02-26) |
| US DOT | Refund (not compensation) for cancellations and significant delays: 3 h+ domestic, 6 h+ international | https://www.transportation.gov/individuals/aviation-consumer-protection/refunds |
| Montreal Convention | Baggage limit 1,519 SDR per passenger, effective 28 December 2024 | https://otc-cta.gc.ca/eng/limits-liability-passengers-and-goods (modified 2024-12-27) |
| SDR value | 1 SDR = US$1.347190 (13 Nov 2026); EUR value derived via the IMF USD/EUR rate ≈ €1.22 | https://www.imf.org/external/np/fin/data/rms_sdrv.aspx |

## Aviation data
| Dataset | Use | Licence |
|---|---|---|
| Eurostat `avia_par_<country>`, 2024, passengers carried, departures, airport pairs (29 countries; Czechia has no pair table → national total from `avia_paoc`) | passengers by route and distance band | Eurostat re-use policy (free re-use with attribution) |
| Eurostat `avia_paoc` 2019-2024 | national totals, growth 2019-2024 | same |
| UK CAA punctuality statistics 2025 (annual "full analysis arrival departure" + 12 monthly files) | share of flights 181+ min late and cancelled, by UK airport and partner country; monthly seasonality | Open Government Licence v3.0 |
| UK CAA airport data 2025, tables 12.1 and 12.2 | UK passengers by route | Open Government Licence v3.0 |
| US BTS On-Time Performance, Jan-Dec 2025 (7.0M flights; only an aggregate carrier x route x month is kept) | benchmark of 3h+ delays, 3-4 h share, carrier-caused share of delay minutes | US public domain |
| OurAirports airports.csv / countries.csv | airport coordinates → great-circle distances | Public domain |
| ECB reference rate GBP/EUR, 2025 annual average (0.8568) | UK261 amounts in EUR | ECB, free re-use with attribution |

## Competitors (published fees only)
| Company | Published fee | Source | Read on |
|---|---|---|---|
| AirHelp | 35% service fee incl. VAT; +15% legal action fee; subscriptions: AirHelp+ ($22.99 per trip to $249.99/yr) and TravelPass ($49-$799/yr, 3/6/9 trips, fee 15%/10%/0%) | https://www.airhelp.com/en/price-list/ | 2026-11-15 |
| Flightright | "usually 20 to 30%" plus VAT, +14% solicitor's surcharge if applicable | https://www.flightright.com/costs | 2026-11-15 |

## Not used
Google Trends: `src/collect_trends.py` is included, but it could not run on this machine (local Python library blocked), so no Trends data is used. Seasonality comes from the CAA monthly files instead. Eurocontrol state punctuality has no simple bulk download: UK-to-country CAA routes are used as the punctuality proxy per country.
