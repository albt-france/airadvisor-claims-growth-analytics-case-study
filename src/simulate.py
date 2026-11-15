"""SIMULATED data: 18 months of a claim-agency funnel, BigQuery style (seed 42). NOT AirAdvisor data.

Calibrated on public data: real route distances and EU261/UK261 bands (data/processed/routes_departures.parquet),
the monthly shape of UK flights and disruptions (CAA 2025), AirAdvisor's published fees (30% / 40% / 50%).
Volumes are scaled down and every rate is an assumption (data/ASSUMPTIONS.md).

Tables written to data/simulated/ (Parquet):
  events               GA4-like export, one row per event (consented sessions only, as with Consent Mode in basic mode)
  claims               the CRM: one row per submitted claim, with status and dates
  ad_spend             daily spend, clicks and conversions REPORTED by each ad platform
  experiment_assignments  server-side log of the fee-display A/B test
  support_tickets      customer service tickets
  subscriptions_test   annual-subscription pilot: offers, tier, price, sign-ups, cancellations, covered claims
and data/_hidden_truth.csv: the 8 events planted on purpose (used only at the end to score detection).
Usage:  python src/simulate.py
"""
import datetime as dt

import numpy as np
import polars as pl

from common import DATA, PROC, PUB, SIM, utf8

SEED = 42
START, END = dt.date(2025, 5, 1), dt.date(2026, 10, 31)
MARKETS = ["UK", "DE", "FR", "ES", "IT", "NL"]
NEW_MARKET, NEW_MARKET_OPEN = "NL", dt.date(2026, 4, 1)          # month 12
BASE_SESSIONS = {"UK": 520, "DE": 330, "FR": 260, "ES": 250, "IT": 200, "NL": 210}
CONSENT = {"UK": 0.74, "DE": 0.63, "FR": 0.66, "ES": 0.72, "IT": 0.70, "NL": 0.67}
# (source, campaign_type, share of sessions, device mix mobile/desktop/tablet, eligibility-check rate)
SOURCES = [
    ("google_ads", "brand", 0.10, (0.58, 0.37, 0.05), 0.55),
    ("google_ads", "non_brand", 0.20, (0.62, 0.33, 0.05), 0.40),
    ("meta_ads", "prospecting", 0.10, (0.82, 0.12, 0.06), 0.27),
    ("meta_ads", "retargeting", 0.04, (0.78, 0.16, 0.06), 0.45),
    ("microsoft_ads", "brand", 0.04, (0.30, 0.66, 0.04), 0.58),
    ("microsoft_ads", "non_brand", 0.02, (0.32, 0.63, 0.05), 0.38),
    ("seo", "organic", 0.32, (0.57, 0.38, 0.05), 0.44),
    ("organic_social", "organic", 0.05, (0.80, 0.14, 0.06), 0.30),
    ("crm", "email", 0.13, (0.52, 0.43, 0.05), 0.60),
]
CLAIM_TYPES = ["delay", "cancellation", "denied_boarding", "baggage"]
CLAIM_MIX = [0.52, 0.28, 0.06, 0.14]
DEVICES = ["mobile", "desktop", "tablet"]
CARRIERS = [f"Carrier {c}" for c in "ABCDEFGHIJKL"]
CARRIER_SHARE = np.array([14, 12, 11, 10, 9, 8, 8, 7, 6, 6, 5, 4], float)
CARRIER_ACCEPT = dict(zip(CARRIERS, [0.66, 0.60, 0.55, 0.62, 0.48, 0.58, 0.52, 0.62, 0.45, 0.57, 0.50, 0.64]))

# the 8 planted events
TAG_BREAK = dt.date(2026, 9, 15)                                # 1. claim_submit stops firing on mobile web
CONSENT_CHANGE = ("DE", dt.date(2026, 2, 16), 0.47)              # 2. new consent banner in Germany
PLATFORM_INFLATION = {"google_ads": 1.12, "meta_ads": 2.05, "microsoft_ads": 1.18}  # 3. platforms over-claim
PAUSE = ("FR", dt.date(2026, 2, 2), dt.date(2026, 3, 29))        # 4. Microsoft brand paused in France
SEO_TAKEOVER = 0.88                                              #    share of brand-ad sessions that come back via SEO
AB = (dt.date(2026, 6, 1), dt.date(2026, 7, 12))                 # 5. fee-display A/B test with SRM
AB_LOST_MOBILE_B = 0.14                                          #    share of low-intent mobile B users lost before logging
POLICY = ("Carrier H", dt.date(2026, 5, 1), 0.30)                # 6. first-response acceptance falls
#                                                                  7. summer peak (seasonality, nothing wrong)
DUP_DAY, DUP_N = dt.date(2026, 1, 20), 280                       # 8. CRM sync duplicates claims


def seasonal_index():
    """Monthly index from the CAA 2025 monthly files: flights x (half of the disruption swing)."""
    s = pl.read_csv(PUB / "seasonality_uk_2025.csv").sort("month")
    idx = s["index_flights"].to_numpy() * (1 + 0.5 * (s["index_disrupted"].to_numpy() - 1))
    return idx / idx.mean()


def main():
    utf8()
    rng = np.random.default_rng(SEED)
    SIM.mkdir(parents=True, exist_ok=True)
    days = np.array([START + dt.timedelta(d) for d in range((END - START).days + 1)])
    n_days = len(days)
    month_idx = seasonal_index()
    dow = np.array([1.10, 1.05, 1.0, 0.98, 0.97, 0.88, 0.95])
    season = np.array([month_idx[d.month - 1] * dow[d.weekday()] for d in days])
    trend = np.array([1.012 ** ((d - START).days / 30.4) for d in days])
    # random disruption days (strikes, storms) per market: short spikes of demand
    shocks = {m: np.ones(n_days) for m in MARKETS}
    for m in MARKETS:
        for _ in range(4):
            s0 = rng.integers(0, n_days - 4)
            shocks[m][s0:s0 + 3] *= rng.uniform(1.4, 1.9)

    # ------------------------------------------------------------ sessions (one row per session, all sessions = truth)
    cells = []
    for m in MARKETS:
        ramp = np.ones(n_days)
        if m == NEW_MARKET:
            age = np.array([(d - NEW_MARKET_OPEN).days for d in days])
            ramp = np.where(age < 0, 0.0, np.minimum(1.0, 0.25 + age / 120))
        for si, (src, camp, share, _, _) in enumerate(SOURCES):
            lam = BASE_SESSIONS[m] * share * season * trend * shocks[m] * ramp
            if src == "microsoft_ads" and camp == "brand" and m == PAUSE[0]:
                paused = np.array([PAUSE[1] <= d <= PAUSE[2] for d in days])
                lam = np.where(paused, 0.0, lam)
            if src == "seo" and m == PAUSE[0]:  # brand searchers come back through organic results during the pause
                paused = np.array([PAUSE[1] <= d <= PAUSE[2] for d in days])
                brand_lam = BASE_SESSIONS[m] * SOURCES[4][2] * season * trend * shocks[m]
                lam = lam + np.where(paused, SEO_TAKEOVER * brand_lam, 0.0)
            cells.append((m, si, rng.poisson(lam)))
    day_i, mk, src_i = [], [], []
    for m, si, counts in cells:
        idx = np.repeat(np.arange(n_days), counts)
        day_i.append(idx); mk.append(np.full(len(idx), m)); src_i.append(np.full(len(idx), si))
    day_i, mk, src_i = np.concatenate(day_i), np.concatenate(mk), np.concatenate(src_i)
    n = len(day_i)
    sess_day = days[day_i]
    src = np.array([SOURCES[i][0] for i in range(len(SOURCES))])[src_i]
    camp = np.array([SOURCES[i][1] for i in range(len(SOURCES))])[src_i]
    dev = np.empty(n, dtype=object)
    for i, s in enumerate(SOURCES):
        mask = src_i == i
        dev[mask] = rng.choice(DEVICES, mask.sum(), p=s[3])
    dev = dev.astype(str)
    secs = rng.integers(6 * 3600, 24 * 3600, n)  # daytime traffic
    ts = (np.array([np.datetime64(d) for d in sess_day]) + secs.astype("timedelta64[s]")).astype("datetime64[us]")
    session_id = np.arange(1, n + 1)
    print(f"sessions (truth): {n:,}")

    # ------------------------------------------------------------ funnel (truth)
    p_check = np.array([s[4] for s in SOURCES])[src_i]
    check = rng.random(n) < p_check
    ctype = rng.choice(CLAIM_TYPES, n, p=CLAIM_MIX)
    p_elig = np.select([ctype == "delay", ctype == "cancellation", ctype == "denied_boarding"], [0.52, 0.60, 0.66], 0.58)
    eligible = check & (rng.random(n) < p_elig)
    p_start = np.where(dev == "desktop", 0.60, np.where(dev == "tablet", 0.55, 0.51))
    p_submit = np.where(dev == "desktop", 0.70, np.where(dev == "tablet", 0.63, 0.57))
    p_start = p_start * np.where(src == "meta_ads", 0.88, 1.0) * np.where(src == "crm", 1.12, 1.0)

    # A/B test on fee display (server-side assignment when an eligible result is shown)
    in_ab = eligible & np.array([AB[0] <= d <= AB[1] for d in sess_day]) & (mk != NEW_MARKET)
    variant = np.where(in_ab, rng.choice(["A", "B"], n), "")
    # true effect: upfront fee -> slightly fewer starts, slightly more completions -> no net change
    p_start = np.where(variant == "B", p_start * 0.975, p_start)
    p_submit = np.where(variant == "B", p_submit * 1.025, p_submit)
    start = eligible & (rng.random(n) < p_start)
    submit = start & (rng.random(n) < p_submit)
    signed = submit & (rng.random(n) < 0.86)

    # consent (truth -> what GA4 can see)
    p_consent = np.array([CONSENT[m] for m in mk])
    p_consent = np.where((mk == CONSENT_CHANGE[0]) & (sess_day >= CONSENT_CHANGE[1]), CONSENT_CHANGE[2], p_consent)
    consent = rng.random(n) < p_consent

    # returning customers: CRM-email sessions belong to earlier customers when there are any
    user = np.char.add("u", session_id.astype(str))

    # ------------------------------------------------------------ GA4 events (consented sessions only)
    ev = []
    def add(mask, name, offset_s, extra=None):
        k = mask & consent
        e = {"session_id": session_id[k], "event_name": np.full(k.sum(), name),
             "event_timestamp": ts[k] + (offset_s + rng.integers(0, 60, k.sum())).astype("timedelta64[s]")}
        if extra is not None:
            e["experiment_variant"] = extra[k]
        ev.append(e)
    add(np.ones(n, bool), "session_start", 0)
    add(check, "eligibility_check", 40)
    # exposure is logged when the result page has rendered: in B on mobile, low-intent users leave first
    lost = (variant == "B") & (dev == "mobile") & ~start & (rng.random(n) < AB_LOST_MOBILE_B / 0.5)
    add(in_ab & ~lost, "experiment_exposure", 45, variant)
    add(start, "claim_start", 120)
    tag_ok = ~((dev == "mobile") & (sess_day >= TAG_BREAK))
    add(submit & tag_ok, "claim_submit", 420)
    add(signed, "document_signed", 600)
    events = pl.concat([pl.DataFrame(e) for e in ev], how="diagonal_relaxed")
    sess = pl.DataFrame({"session_id": session_id, "user_pseudo_id": user, "device_category": dev, "country": mk,
                         "traffic_source": src, "campaign_type": camp, "claim_type": ctype})
    events = (events.join(sess, on="session_id", how="left")
                    .with_columns(event_date=pl.col("event_timestamp").dt.date(),
                                  claim_type=pl.when(pl.col("event_name").is_in(["session_start"])).then(None).otherwise(pl.col("claim_type")),
                                  consent_state=pl.lit("granted"))
                    .rename({"session_id": "ga_session_id"})
                    .select("event_date", "event_timestamp", "event_name", "user_pseudo_id", "ga_session_id", "country",
                            "device_category", "traffic_source", "campaign_type", "claim_type", "experiment_variant", "consent_state")
                    .sort("event_timestamp"))
    events.write_parquet(SIM / "events.parquet")
    print(f"events (GA4, consented only): {len(events):,}")

    pl.DataFrame({"session_id": session_id[in_ab], "variant": variant[in_ab],
                  "assigned_at": ts[in_ab] + np.timedelta64(42, "s"), "country": mk[in_ab], "device_category": dev[in_ab]}
                 ).write_parquet(SIM / "experiment_assignments.parquet")

    # ------------------------------------------------------------ claims (CRM = every submitted claim)
    k = np.flatnonzero(submit)
    nc = len(k)
    routes = pl.read_parquet(PROC / "routes_departures.parquet").filter(pl.col("country").is_in(MARKETS)).sort("country", "orig_icao", "dest_icao", "pax", "distance_km")  # fixed order: same sample on every run
    c_route, c_dist, c_band, c_amt = (np.empty(nc, dtype=object) for _ in range(4))
    for m in MARKETS:
        mm = np.flatnonzero(mk[k] == m)
        r = routes.filter(pl.col("country") == m)
        w = r["pax"].to_numpy(); w = w / w.sum()
        pick = rng.choice(len(r), len(mm), p=w)
        c_route[mm] = (r["orig_icao"] + " - " + r["dest_icao"]).to_numpy()[pick]
        c_dist[mm] = r["distance_km"].to_numpy()[pick]
        c_band[mm] = r["band"].to_numpy()[pick]
        c_amt[mm] = r["amount_eur"].to_numpy()[pick]
    c_dist, c_amt = c_dist.astype(float), c_amt.astype(float)
    pax = rng.choice([1, 2, 3, 4], nc, p=[0.52, 0.25, 0.15, 0.08])
    c_type = ctype[k]
    baggage_amt = np.minimum(rng.lognormal(np.log(420), 0.6, nc), 1851.0)  # capped near 1,519 SDR (Montreal)
    amount_due = np.where(c_type == "baggage", baggage_amt, c_amt * pax)
    carrier = rng.choice(CARRIERS, nc, p=CARRIER_SHARE / CARRIER_SHARE.sum())
    created = ts[k] + np.timedelta64(420, "s")
    c_day = sess_day[k].astype("datetime64[D]")

    # lifecycle (all in days after creation)
    is_signed = signed[k]
    withdrawn = is_signed & (rng.random(nc) < 0.04)                          # 14-day cooling-off
    p_valid = np.select([src[k] == "meta_ads", src[k] == "organic_social"], [0.76, 0.80], 0.88)  # social traffic: weaker cases
    valid = is_signed & ~withdrawn & (rng.random(nc) < p_valid)               # internal validation
    sent_d = rng.integers(2, 11, nc)
    resp_d = sent_d + rng.integers(20, 76, nc)
    resp_date = c_day + resp_d.astype("timedelta64[D]")
    p_acc = np.array([CARRIER_ACCEPT[c] for c in carrier])
    p_acc = np.where((carrier == POLICY[0]) & (resp_date >= np.datetime64(POLICY[1])), POLICY[2], p_acc)
    accepted_first = valid & (rng.random(nc) < p_acc)
    rejected_first = valid & ~accepted_first
    escalated = rejected_first & (rng.random(nc) < 0.62)
    legal_d = resp_d + rng.integers(120, 300, nc)
    won_legal = escalated & (rng.random(nc) < 0.74)
    pay_d = np.where(accepted_first, resp_d + rng.integers(10, 41, nc), legal_d + rng.integers(10, 41, nc))
    end = np.datetime64(END)
    cd = c_day.astype("datetime64[D]")
    sent_at = np.where(valid, cd + sent_d.astype("timedelta64[D]"), np.datetime64("NaT"))
    resp_at = np.where(valid, cd + resp_d.astype("timedelta64[D]"), np.datetime64("NaT"))
    legal_at = np.where(escalated, cd + legal_d.astype("timedelta64[D]"), np.datetime64("NaT"))
    paid_at = np.where(accepted_first | won_legal, cd + pay_d.astype("timedelta64[D]"), np.datetime64("NaT"))
    fee = np.where(c_type == "baggage", 0.40, 0.30)
    fee = np.where(won_legal & ~accepted_first, 0.50, fee)

    def known(x):  # nothing after the data cut-off is known yet
        return np.where(x <= end, x, np.datetime64("NaT", "D"))
    sent_at, resp_at, legal_at, paid_at = known(sent_at), known(resp_at), known(legal_at), known(paid_at)
    status = np.full(nc, "submitted", dtype=object)
    status[~is_signed] = "awaiting_documents"
    status[withdrawn] = "withdrawn"
    status[is_signed & ~withdrawn & ~valid] = "rejected_internal"
    status[~np.isnat(sent_at)] = "sent_to_airline"
    status[~np.isnat(resp_at) & accepted_first] = "accepted"
    status[~np.isnat(resp_at) & rejected_first & ~escalated] = "rejected_by_airline"
    status[~np.isnat(resp_at) & escalated] = "in_legal"
    status[~np.isnat(legal_at) & escalated & ~won_legal] = "lost_in_court"
    status[~np.isnat(paid_at)] = "paid"
    paid_amount = np.where(status == "paid", amount_due, 0.0)
    revenue = paid_amount * fee
    # customers: CRM-email claims re-use an earlier customer when possible (repeat claimants)
    cust = np.char.add("c", np.arange(1, nc + 1).astype(str)).astype(object)
    crm_rows = np.flatnonzero(src[k] == "crm")
    for i in crm_rows:
        if i > 50 and rng.random() < 0.7:
            cust[i] = cust[rng.integers(0, i)]
    claims = pl.DataFrame({
        "claim_id": np.char.add("CL", (100000 + np.arange(nc)).astype(str)), "customer_id": cust.astype(str),
        "session_id": session_id[k], "created_at": created, "market": mk[k], "device_category": dev[k],
        "traffic_source": src[k], "campaign_type": camp[k], "claim_type": c_type, "carrier": carrier,
        "route": c_route.astype(str), "distance_km": np.round(c_dist), "distance_band": c_band.astype(str),
        "passengers": pax, "amount_due_eur": np.round(amount_due, 2), "status": status.astype(str),
        "document_signed": is_signed, "sent_to_airline_at": sent_at, "airline_response_at": resp_at,
        "first_response": np.where(np.isnat(resp_at), None, np.where(accepted_first, "accepted", "rejected")),
        "escalated_to_legal": escalated & ~np.isnat(resp_at), "legal_outcome_at": legal_at, "paid_at": paid_at,
        "paid_amount_eur": np.round(paid_amount, 2), "fee_rate": fee, "revenue_eur": np.round(revenue, 2)})
    # 8. duplicates created by a CRM sync on one day
    day_rows = claims.filter(pl.col("created_at").dt.date() == DUP_DAY)
    dups = day_rows.sample(min(DUP_N, len(day_rows)), seed=SEED).with_columns(
        claim_id=pl.col("claim_id").str.replace("CL", "CLD"),
        created_at=pl.col("created_at") + pl.duration(seconds=37))
    claims = pl.concat([claims, dups]).sort("created_at")
    claims.write_parquet(SIM / "claims.parquet")
    print(f"claims (CRM): {len(claims):,} incl. {len(dups)} duplicates")

    # ------------------------------------------------------------ ad spend + platform-reported conversions
    cpc = {("google_ads", "brand"): 1.10, ("google_ads", "non_brand"): 6.20, ("meta_ads", "prospecting"): 2.70,
           ("meta_ads", "retargeting"): 1.60, ("microsoft_ads", "brand"): 0.95, ("microsoft_ads", "non_brand"): 4.10}
    ctr = {"brand": 0.21, "non_brand": 0.055, "prospecting": 0.011, "retargeting": 0.018}
    s_day = pl.Series("date", sess_day.astype("datetime64[D]"))
    base = sess.with_columns(date=s_day, submitted=pl.Series(submit)).filter(pl.col("traffic_source").is_in(list(PLATFORM_INFLATION)))
    agg = base.group_by("date", "country", "traffic_source", "campaign_type").agg(
        sessions=pl.len(), true_claims=pl.col("submitted").sum()).sort("date", "country", "traffic_source", "campaign_type")
    ga = agg.to_dict(as_series=False)
    clicks = np.round(np.array(ga["sessions"]) * rng.uniform(1.04, 1.12, len(agg))).astype(int)
    unit = np.array([cpc[(s, c)] for s, c in zip(ga["traffic_source"], ga["campaign_type"])]) * rng.uniform(0.85, 1.15, len(agg))
    infl = np.array([PLATFORM_INFLATION[s] for s in ga["traffic_source"]])
    reported = rng.poisson(np.array(ga["true_claims"]) * infl)
    ad = agg.with_columns(
        platform=pl.col("traffic_source"), clicks=pl.Series(clicks), spend_eur=pl.Series(np.round(clicks * unit, 2)),
        impressions=pl.Series(np.round(clicks / np.array([ctr[c] for c in ga["campaign_type"]])).astype(int)),
        platform_conversions=pl.Series(reported)).select(
        "date", "country", "platform", "campaign_type", "impressions", "clicks", "spend_eur", "platform_conversions")
    ad.write_parquet(SIM / "ad_spend.parquet")
    print(f"ad_spend rows: {len(ad):,}, spend {ad['spend_eur'].sum() / 1e6:.2f}M EUR")

    # ------------------------------------------------------------ support tickets
    cl = claims.filter(~pl.col("claim_id").str.starts_with("CLD"))
    h_rejected = ((cl["carrier"] == POLICY[0]) & (cl["first_response"] == "rejected")).fill_null(False)
    lam = 0.22 + 0.30 * cl["escalated_to_legal"].fill_null(False).cast(int).to_numpy() + 0.35 * h_rejected.cast(int).to_numpy()
    nt = rng.poisson(lam)
    ti = np.repeat(np.arange(len(cl)), nt)
    cats = rng.choice(["status_update", "documents", "payment", "rejection_question", "complaint"], len(ti), p=[0.42, 0.2, 0.14, 0.16, 0.08])
    t_created = cl["created_at"].to_numpy()[ti] + rng.integers(1, 120, len(ti)).astype("timedelta64[D]")
    keep = t_created <= np.datetime64(END)
    pl.DataFrame({"ticket_id": np.char.add("T", np.arange(keep.sum()).astype(str)), "claim_id": cl["claim_id"].to_numpy()[ti][keep],
                  "created_at": t_created[keep], "category": cats[keep],
                  "channel": rng.choice(["email", "chat"], keep.sum(), p=[0.6, 0.4]),
                  "first_response_hours": np.round(rng.gamma(2.0, 6.0, keep.sum()), 1)}).write_parquet(SIM / "support_tickets.parquet")

    # ------------------------------------------------------------ subscription pilot (UK + DE, from 2026-06-01)
    tiers = {"Lite": 29.0, "Plus": 49.0, "Pro": 79.0}
    p_start_pilot = dt.date(2026, 6, 1)
    pool = cl.filter((pl.col("market").is_in(["UK", "DE"])) & (pl.col("created_at").dt.date() >= p_start_pilot))
    no = len(pool) + 9000                                    # post-claim offers + website offers
    o_tier = rng.choice(list(tiers), no)
    price = np.array([tiers[t] for t in o_tier])
    trips = np.clip(np.round(rng.lognormal(np.log(3.0), 0.75, no)), 1, 40)   # declared trips per year
    logit = -3.1 - 0.028 * (price - 49) + 0.16 * (trips - 3)
    subscribed = rng.random(no) < 1 / (1 + np.exp(-logit))
    o_date = np.array([p_start_pilot + dt.timedelta(int(x)) for x in rng.integers(0, (END - p_start_pilot).days, no)])
    cooling = subscribed & (rng.random(no) < 0.07)
    days_on = np.array([(END - d).days for d in o_date])
    renew_off = subscribed & ~cooling & (rng.random(no) < (0.10 + 0.05 * (price == 79) + 0.03 * (price == 49)) * days_on / 30 * 0.6)
    renew_off_at = np.array([d + dt.timedelta(int(rng.integers(15, max(16, x)))) if r else None
                             for d, x, r in zip(o_date, days_on, renew_off)], dtype=object)
    # covered claims: 2 flights per trip x real per-flight eligible disruption (~1.0%) + baggage (~0.3%), claimed 90% of the time
    exp_claims = trips * 2 * 0.013 * 0.9 * days_on / 365
    covered = np.where(subscribed & ~cooling, rng.poisson(exp_claims), 0)
    pl.DataFrame({"offer_id": np.char.add("O", np.arange(no).astype(str)), "market": rng.choice(["UK", "DE"], no, p=[0.6, 0.4]),
                  "offer_date": pl.Series(list(o_date), dtype=pl.Date), "channel": np.where(np.arange(no) < len(pool), "post_claim_email", "website"),
                  "tier": o_tier, "price_eur": price, "declared_trips_per_year": trips.astype(int), "subscribed": subscribed,
                  "cooling_off_cancelled": cooling, "auto_renew_off_at": pl.Series(list(renew_off_at), dtype=pl.Date),
                  "covered_claims": covered.astype(int)}).write_parquet(SIM / "subscriptions_test.parquet")
    print(f"subscription offers: {no:,}, sign-ups {subscribed.sum():,}")

    # ------------------------------------------------------------ hidden truth (answer key, read only at the end)
    truth = [
        (1, "broken_tag", "claim_submit not sent on mobile web after a release", str(TAG_BREAK), str(END), "all", "mobile"),
        (2, "consent_mode", "new consent banner lowers consent from 63% to 47%", str(CONSENT_CHANGE[1]), str(END), "DE", "all"),
        (3, "double_counting", "platforms report 1.12x (Google), 2.05x (Meta), 1.18x (Microsoft) the claims they drove", str(START), str(END), "all", "all"),
        (4, "brand_cannibalisation", f"Microsoft brand paused; {SEO_TAKEOVER:.0%} of its sessions return via SEO", str(PAUSE[1]), str(PAUSE[2]), "FR", "all"),
        (5, "ab_srm", "fee-display test: 14% of low-intent mobile B users not logged; true effect ~0", str(AB[0]), str(AB[1]), "all but NL", "mobile"),
        (6, "acceptance_drop", "Carrier H first-response acceptance 62% -> 30%", str(POLICY[1]), str(END), "all", "all"),
        (7, "seasonal_peak", "summer peak follows the real CAA seasonality: nothing broken", "2026-06-01", "2026-08-31", "all", "all"),
        (8, "duplicates", f"{len(dups)} claims duplicated by a CRM sync (new id, +37 s)", str(DUP_DAY), str(DUP_DAY), "all", "all"),
    ]
    pl.DataFrame(truth, schema=["id", "event", "description", "start", "end", "market", "device"], orient="row").write_csv(DATA / "_hidden_truth.csv")
    print("hidden truth written to data/_hidden_truth.csv")


if __name__ == "__main__":
    main()
