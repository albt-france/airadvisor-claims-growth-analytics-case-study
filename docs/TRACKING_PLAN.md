# Tracking plan: claim funnel (GTM + GA4 + Consent Mode v2)

Goal: every funnel step is measured once, with the same parameters, on every device, and can be reconciled with the CRM every day.
Server-side truth stays in the CRM. GA4 measures behaviour of consented users and is checked against the CRM (`sql/03`, `sql/04`).

## Data layer convention
All pushes use `event` + flat parameters. Values are lower_snake_case. No personal data (no name, e-mail, booking reference, IBAN) is ever pushed.

```js
window.dataLayer = window.dataLayer || [];
dataLayer.push({
  event: 'claim_submit',
  claim_id_hash: 'sha256 of the CRM claim id',   // joins GA4 to the CRM without personal data
  claim_type: 'delay',                           // delay | cancellation | denied_boarding | baggage
  regulation: 'eu261',                           // eu261 | uk261 | appr | montreal | other
  distance_band: 'medium',                       // short | medium | long
  passengers: 2,
  market: 'de',
  value: 150,                                    // expected fee in EUR (amount x fee x historical success rate)
  currency: 'EUR'
});
```

## Events

| Event | When it fires (GTM trigger) | Parameters | GA4 key event | Without consent (Consent Mode v2) | QA test (acceptance) |
|---|---|---|---|---|---|
| `page_view` | GA4 config tag, History Change trigger for the single-page form | page_location, page_type | no | cookieless ping (advanced mode) or nothing (basic mode) | Tag Assistant: one page_view per route change, not two |
| `eligibility_check` | Custom Event `eligibility_check`, pushed when the checker returns a result | claim_type, result (eligible / not_eligible / unknown), regulation, distance_band, market | no | as above | Run the checker on an eligible and a not-eligible flight: one event each, correct `result` |
| `experiment_exposure` | Custom Event pushed **by the server response** that assigns the variant, not on render | experiment_id, variant | no | as above | Assignment log count = GA4 count x consent rate, per variant and device (SRM check `sql/11`) |
| `claim_start` | Custom Event on the first field change of step 1 | claim_type, market | no | as above | Open the form and type: one event; reload: no second event in the same session |
| `claim_submit` | Custom Event pushed after the API **confirms** the claim (HTTP 201), never on button click | claim_id_hash, claim_type, regulation, distance_band, passengers, value, currency | **yes** | as above | Submit a test claim on mobile Safari, mobile Chrome, desktop: GA4 DebugView shows it, CRM shows the same hash |
| `document_signed` | Custom Event after the e-signature callback | claim_id_hash, claim_type | yes | as above | Sign a test claim: event once; GA4/CRM daily ratio stays within the band |
| `subscription_purchase` | Custom Event after payment confirmation | tier, value, currency, billing (annual) | yes | as above | Test purchase in sandbox: one purchase, correct value |

## Consent
- Banner from the CMP sends `gtag('consent', 'default', {...denied})` before any tag, then `update` on choice. All GA4 and ads tags use built-in consent checks.
- Report GA4 numbers as "consented users"; business numbers come from the CRM. Expected GA4/CRM ratio = consent rate (about 0.6-0.75 in the simulation).
- Any banner change ships with a note in the release log: the weekly coverage check (`sql/04`) will move and must not be read as a demand change.

## Server-side and offline conversions
- `claim_submit` and `document_signed` are also sent server-side (GTM server container or Measurement Protocol) with `claim_id_hash`, so ad platforms receive conversions even when the browser tag fails.
- Paid claims are uploaded back to Google Ads / Meta / Microsoft Ads as **offline conversions** with their real value (fee earned). Bidding then optimises for paid claims, not form submissions.

## Release checklist (every front-end release)
1. Run the QA tests above on mobile and desktop in staging (GTM preview + GA4 DebugView).
2. Compare staging GA4 events with staging CRM rows for the test claims.
3. After release, the daily check `sql/03` must stay "ok" for mobile, desktop and tablet for 3 days; an alert pages the data owner.

## New feature tracking requirement (template)
Feature, owner, decision it informs, events and parameters, KPI affected (link to `KPI_DICTIONARY.md`), consent behaviour, QA test, dashboard where it appears.
