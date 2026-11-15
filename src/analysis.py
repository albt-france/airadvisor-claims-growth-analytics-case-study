"""All analyses behind the report and the dashboard. Reads data/simulated + data/public, writes data/output/.

Sections (same order as the report):
  market      PUBLIC: country ranking, TAM/SAM/SOM, sensitivity
  tracking    SIMULATED: GA4 vs CRM vs ad platforms, consent gap, duplicates, the tag break
  testing     SIMULATED: SRM check, corrected A/B read, power, difference-in-differences on the brand pause
  spend       SIMULATED: CAC and ROAS per channel, wasted spend, forecast and budget
  subscription  PUBLIC + SIMULATED: expected cost per subscriber from real disruption rates, pilot tiers, LTV
  detection   scoring of the 8 planted events against data/_hidden_truth.csv (run last)
Every number in the PDF and dashboard comes from data/output/results.json or the CSVs next to it.
Usage:  python src/analysis.py
"""
import json
import math

import numpy as np
import polars as pl
from scipy import stats

from common import DATA, PUB, run_sql_file, sim_con, utf8

OUT = DATA / "output"
END = "2026-10-31"
HANDLING_COST = 35.0       # ops + legal cost of processing one claim (assumption)
BAGGAGE_RATE = 0.006       # mishandled bags per passenger-flight (order of magnitude of industry baggage reports; assumption)
BAGGAGE_CLAIMABLE = 0.40   # share of mishandled bags that lead to a valid claim (assumption)
BAGGAGE_VALUE = 450.0      # average baggage compensation, EUR (assumption, below the Montreal cap)
AIRLINE_CONTROL = 0.55     # same central assumption as the market model


def z_two_props(x1, n1, x2, n2):
    x1, n1, x2, n2 = float(x1), float(n1), float(x2), float(n2)   # DuckDB sums may arrive as Decimal
    p1, p2 = x1 / n1, x2 / n2
    p = (x1 + x2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    z = (p2 - p1) / se
    se_diff = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    return {"rate_a": p1, "rate_b": p2, "lift_rel": p2 / p1 - 1, "diff_pts": p2 - p1,
            "ci_low": p2 - p1 - 1.96 * se_diff, "ci_high": p2 - p1 + 1.96 * se_diff, "z": z, "p_value": 2 * (1 - stats.norm.cdf(abs(z)))}


def ols(y, X):
    """OLS with HC1 robust standard errors (numpy only)."""
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    n, k = X.shape
    xtx_inv = np.linalg.inv(X.T @ X)
    meat = X.T @ (X * (resid ** 2)[:, None])
    cov = xtx_inv @ meat @ xtx_inv * n / (n - k)
    return beta, np.sqrt(np.diag(cov))


# ---------------------------------------------------------------- PUBLIC market
def market():
    m = pl.read_csv(PUB / "market_opportunity.csv")
    sens = pl.read_csv(PUB / "market_sensitivity.csv")
    rs = pl.read_csv(PUB / "rank_stability.csv")
    rank_cols = [c for c in rs.columns if c != "country"]
    top5 = set(rs.filter(pl.col("central") <= 5)["country"])
    stable = all(set(rs.filter(pl.col(c) <= 7)["country"]) >= top5 for c in rank_cols)
    rs = rs.with_columns(best=pl.min_horizontal(rank_cols), worst=pl.max_horizontal(rank_cols))
    # priority tiers: scale (top 4 by SOM), next growth (5-8 with growth or long-haul mix), long tail
    tiers = []
    for r in m.sort("rank").iter_rows(named=True):
        t = "Core: defend and scale" if r["rank"] <= 4 else ("Next: invest in local growth" if r["rank"] <= 8 else "Long tail: SEO only")
        tiers.append(t)
    m = m.sort("rank").with_columns(tier=pl.Series(tiers))
    m.write_csv(OUT / "market_ranking.csv")
    us = dict(pl.read_csv(PUB / "us_benchmark.csv").iter_rows())
    eu = m.filter(pl.col("country") != "UK")
    return {
        "ceiling_eur": m["ceiling_eur"].sum(), "tam_eur": m["tam_eur"].sum(), "sam_eur": m["sam_eur"].sum(),
        "som_eur": m["som_eur"].sum(), "som_claims": m["som_claims"].sum(), "countries": len(m),
        "departing_pax": m["departing_pax"].sum(), "disrupted_pax": m["disrupted_pax"].sum(),
        "disrupted_share": m["disrupted_pax"].sum() / m["departing_pax"].sum(),
        "avg_amount_eur": m["ceiling_eur"].sum() / m["disrupted_pax"].sum(),
        "top5": m.head(5)["country"].to_list(), "next": m.filter(pl.col("rank").is_between(5, 8))["country"].to_list(),
        "top4_share_som": m.head(4)["som_eur"].sum() / m["som_eur"].sum(),
        "uk_share_ceiling": m.filter(pl.col("country") == "UK")["ceiling_eur"][0] / m["ceiling_eur"].sum(),
        "ranking_stable_top5": stable,
        "sens_min": sens["som_total_eur"].min(), "sens_max": sens["som_total_eur"].max(),
        "us_late3": us["late_3h_rate"], "us_cancel": us["cancel_rate"], "us_carrier_share": us["carrier_share_of_3h_delay_minutes"],
        "us_share_3to4": us["share_3to4h_of_3h"], "us_flights": us["flights"],
        "eu_late3_mean": float((eu["p_late3"] * eu["operated"]).sum() / eu["operated"].sum()),
        "uk_late3": m.filter(pl.col("country") == "UK")["p_late3"][0], "uk_cancel": m.filter(pl.col("country") == "UK")["p_cancel"][0],
    }


# ---------------------------------------------------------------- tracking & data quality
def tracking(con):
    r = {}
    f = run_sql_file("01_funnel_by_step.sql", con)
    f.write_csv(OUT / "funnel_by_device.csv")
    tot = f.select(pl.col("sessions", "checks", "starts", "submits", "signed").sum()).row(0, named=True)
    r["funnel"] = tot
    r["mobile_vs_desktop_submit"] = (f.filter(pl.col("device_category") == "mobile")["submit_rate"][0],
                                     f.filter(pl.col("device_category") == "desktop")["submit_rate"][0])

    q = run_sql_file("03_qa_ga4_vs_crm_daily.sql", con)
    q.write_csv(OUT / "qa_ga4_crm_daily.csv")
    mob = q.filter(pl.col("device_category") == "mobile").sort("d")
    alerts = mob["status"].to_list()
    first = None
    for i in range(len(alerts) - 2):
        if alerts[i] == alerts[i + 1] == alerts[i + 2] == "ALERT":
            first = str(mob["d"][i]); break
    pre = mob.filter(pl.col("d") < pl.lit(first).str.to_date())["ratio"].tail(56).mean() if first else None
    post = mob.filter(pl.col("d") >= pl.lit(first).str.to_date())["ratio"].mean() if first else None
    lost = mob.filter(pl.col("d") >= pl.lit(first).str.to_date())["crm_claims"].sum() if first else 0
    r["tag_break"] = {"detected": first, "ratio_before": pre, "ratio_after": post, "crm_claims_unseen_by_ga4": lost,
                      "false_alerts_before": int(mob.filter((pl.col("d") < pl.lit(first).str.to_date()) & (pl.col("status") == "ALERT")).height) if first else None}

    c = run_sql_file("04_qa_consent_gap_by_country.sql", con).with_columns(wk=pl.col("wk").cast(pl.Date))
    c.write_csv(OUT / "qa_consent_weekly.csv")
    res = {}
    for ctry in c["country"].unique().sort():
        s = c.filter((pl.col("country") == ctry) & (pl.col("wk") >= pl.date(2025, 11, 3))).sort("wk")
        base = s.filter(pl.col("wk") < pl.date(2026, 2, 9))
        after = s.filter(pl.col("wk") >= pl.date(2026, 2, 23))
        ratio = lambda f: f["ga_submits"].sum() / f["crm_claims"].sum() if f["crm_claims"].sum() else None  # noqa: E731
        res[ctry] = {"before": ratio(base), "after": ratio(after)}   # NL has no 'before' (opened in April 2026)
    # change point for DE: first week whose coverage is 3 sd below the trailing 12-week mean
    de = c.filter(pl.col("country") == "DE").sort("wk")
    cov = de["ga_coverage"].to_numpy()
    cp = None
    for i in range(12, len(cov)):
        w = cov[i - 12:i]
        if cov[i] < w.mean() - 3 * w.std(ddof=1) and cov[min(i + 1, len(cov) - 1)] < w.mean() - 3 * w.std(ddof=1):
            cp = str(de["wk"][i]); break
    de_crm = c.filter(pl.col("country") == "DE").sort("wk")
    crm_before = de_crm.filter(pl.col("wk").is_between(pl.date(2025, 11, 3), pl.date(2026, 2, 8)))["crm_claims"].mean()
    crm_after = de_crm.filter(pl.col("wk").is_between(pl.date(2026, 2, 23), pl.date(2026, 5, 31)))["crm_claims"].mean()
    r["consent"] = {"coverage": res, "de_change_week": cp, "de_crm_weekly_before": crm_before, "de_crm_weekly_after": crm_after}

    d = run_sql_file("05_qa_duplicate_claims.sql", con)
    r["duplicates"] = {"days": d.height, "count": int(d["duplicate_claims"].sum()) if d.height else 0,
                       "day": str(d["d"][0]) if d.height else None}

    p = run_sql_file("06_platform_vs_crm.sql", con).with_columns(pl.col("reported", "all_platforms_reported", "all_paid_crm_claims").cast(pl.Float64))
    p.write_csv(OUT / "platform_vs_crm_monthly.csv")
    by = p.group_by("platform").agg(pl.col("reported").sum(), pl.col("crm_claims").sum(), pl.col("spend_eur").sum()).with_columns(
        factor=pl.col("reported") / pl.col("crm_claims")).sort("platform")
    all_claims = con.sql("select count(*) from claims where claim_id not like 'CLD%'").fetchall()[0][0]
    r["platforms"] = {"by_platform": by.to_dicts(), "reported_total": by["reported"].sum(), "crm_paid_total": by["crm_claims"].sum(),
                      "over_total": by["reported"].sum() / by["crm_claims"].sum(), "all_crm_claims": all_claims,
                      "months_reported_gt_all_paid": int((p.group_by("m").agg(pl.col("reported").sum(), pl.col("crm_claims").sum())
                                                          .filter(pl.col("reported") > pl.col("crm_claims"))).height)}
    return r


# ---------------------------------------------------------------- testing
def testing(con):
    r = {}
    # SRM on GA4 exposures
    srm = run_sql_file("11_ab_test_srm.sql", con)
    srm.write_csv(OUT / "ab_srm.csv")
    tot = srm.group_by("variant").agg(pl.col("ga_exposures", "server_assignments").sum()).sort("variant")
    ga = tot["ga_exposures"].to_numpy(); sv = tot["server_assignments"].to_numpy()
    chi_ga = stats.chisquare(ga); chi_sv = stats.chisquare(sv)
    mob = srm.filter(pl.col("device_category") == "mobile").sort("variant")
    dsk = srm.filter(pl.col("device_category") == "desktop").sort("variant")
    r["srm"] = {"ga_a": int(ga[0]), "ga_b": int(ga[1]), "ga_share_b": ga[1] / ga.sum(), "ga_p": chi_ga.pvalue,
                "server_a": int(sv[0]), "server_b": int(sv[1]), "server_p": chi_sv.pvalue,
                "mobile_share_b": mob["ga_share"][1], "mobile_p": stats.chisquare(mob["ga_exposures"].to_numpy()).pvalue,
                "desktop_p": stats.chisquare(dsk["ga_exposures"].to_numpy()).pvalue}
    # raw read: GA4 claim_submit among GA4-exposed sessions
    raw = con.sql("""
        with ex as (select ga_session_id, experiment_variant v from events where event_name = 'experiment_exposure'),
             sb as (select distinct ga_session_id from events where event_name = 'claim_submit')
        select v, count(*) n, count(sb.ga_session_id) x from ex left join sb using (ga_session_id) group by v order by v""").pl()
    r["raw"] = z_two_props(raw["x"][0], raw["n"][0], raw["x"][1], raw["n"][1]) | {"n_a": raw["n"][0], "n_b": raw["n"][1]}
    # corrected read: every server assignment (intention to treat), outcome from the CRM
    itt = con.sql("""
        select a.variant v, count(*) n, count(c.claim_id) x
        from experiment_assignments a left join (select * from claims where claim_id not like 'CLD%') c using (session_id)
        group by v order by v""").pl()
    r["itt"] = z_two_props(itt["x"][0], itt["n"][0], itt["x"][1], itt["n"][1]) | {"n_a": itt["n"][0], "n_b": itt["n"][1]}
    # power: sample per arm for 80% power at alpha 5% to detect a 5% relative lift on the ITT baseline
    p0 = r["itt"]["rate_a"]
    def n_needed(p0, rel):
        p1 = p0 * (1 + rel); pbar = (p0 + p1) / 2
        za, zb = stats.norm.ppf(0.975), stats.norm.ppf(0.8)
        return ((za * math.sqrt(2 * pbar * (1 - pbar)) + zb * math.sqrt(p0 * (1 - p0) + p1 * (1 - p1))) / (p1 - p0)) ** 2
    n_arm = itt["n"][0]
    mde = next(rel for rel in np.arange(0.01, 0.5, 0.0025) if n_needed(p0, rel) <= n_arm)
    r["power"] = {"baseline": p0, "n_per_arm_for_5pct": n_needed(p0, 0.05), "n_per_arm_actual": n_arm, "mde_rel_actual": float(mde),
                  "weeks_for_5pct": n_needed(p0, 0.05) / (n_arm / 6)}
    # difference-in-differences: weekly brand demand (Microsoft brand + SEO claims) by country
    w = con.sql("""
        select date_trunc('week', cast(created_at as date)) wk, market,
               sum(case when traffic_source = 'microsoft_ads' and campaign_type = 'brand' then 1 else 0 end) ms_brand,
               sum(case when traffic_source = 'seo' then 1 else 0 end) seo
        from claims where claim_id not like 'CLD%' and market in ('FR','UK','DE','ES','IT')
          and cast(created_at as date) between date '2025-11-03' and date '2026-03-29'
        group by 1, 2 order by 1, 2""").pl().with_columns(wk=pl.col("wk").cast(pl.Date))
    w = w.with_columns(y=(pl.col("ms_brand") + pl.col("seo")).cast(pl.Float64),
                       treat=((pl.col("market") == "FR") & (pl.col("wk") >= pl.date(2026, 2, 2))).cast(pl.Float64))
    w.write_csv(OUT / "did_weekly.csv")
    mk = sorted(w["market"].unique()); wks = sorted(w["wk"].unique())
    X = np.column_stack([w["treat"].to_numpy()] + [(w["market"] == m).cast(float).to_numpy() for m in mk]
                        + [(w["wk"] == k).cast(float).to_numpy() for k in wks[1:]])
    yl = np.log(w["y"].to_numpy())
    b_log, se_log = ols(yl, X)
    b_lvl, se_lvl = ols(w["y"].to_numpy(), X)
    fr_ms_base = w.filter((pl.col("market") == "FR") & (pl.col("wk") < pl.date(2026, 2, 2)))["ms_brand"].mean()
    fr_seo_before = w.filter((pl.col("market") == "FR") & (pl.col("wk") < pl.date(2026, 2, 2)))["seo"].mean()
    fr_seo_pause = w.filter((pl.col("market") == "FR") & (pl.col("wk") >= pl.date(2026, 2, 2)))["seo"].mean()
    incr = -b_lvl[0] / fr_ms_base
    r["did"] = {"beta_log": b_log[0], "se_log": se_log[0], "beta_level": b_lvl[0], "se_level": se_lvl[0],
                "ci_level": (b_lvl[0] - 1.96 * se_lvl[0], b_lvl[0] + 1.96 * se_lvl[0]),
                "fr_ms_brand_per_week_before": fr_ms_base, "incrementality": incr,
                "incr_ci": (-(b_lvl[0] + 1.96 * se_lvl[0]) / fr_ms_base, -(b_lvl[0] - 1.96 * se_lvl[0]) / fr_ms_base),
                "fr_seo_before": fr_seo_before, "fr_seo_pause": fr_seo_pause}
    # pre-trend check: placebo pause 8 weeks earlier, pre-period only
    pre = w.filter(pl.col("wk") < pl.date(2026, 2, 2)).with_columns(
        treat=((pl.col("market") == "FR") & (pl.col("wk") >= pl.date(2025, 12, 22))).cast(pl.Float64))
    wks2 = sorted(pre["wk"].unique())
    X2 = np.column_stack([pre["treat"].to_numpy()] + [(pre["market"] == m).cast(float).to_numpy() for m in mk]
                         + [(pre["wk"] == k).cast(float).to_numpy() for k in wks2[1:]])
    bp, sp = ols(np.log(pre["y"].to_numpy()), X2)
    r["did"]["placebo_beta_log"], r["did"]["placebo_se_log"] = bp[0], sp[0]
    return r


# ---------------------------------------------------------------- spend, forecast, budget
def spend(con, did):
    r = {}
    ue = run_sql_file("07_unit_economics_channel.sql", con).with_columns(pl.col("valid_claims", "paid_claims").cast(pl.Float64))
    ue.write_csv(OUT / "unit_economics_market_channel.csv")
    ch = con.sql("""
        with c as (select traffic_source, campaign_type, count(*) claims, sum(case when status='paid' then 1 else 0 end) paid, sum(revenue_eur) rev
                   from claims where claim_id not like 'CLD%' and cast(created_at as date) between date '2025-05-01' and date '2025-10-31' group by 1,2),
             s as (select platform traffic_source, campaign_type, sum(spend_eur) spend from ad_spend
                   where date between date '2025-05-01' and date '2025-10-31' group by 1,2)
        select c.*, coalesce(s.spend, 0) spend from c left join s using (traffic_source, campaign_type) order by spend desc, traffic_source, campaign_type""").pl()
    ch = ch.with_columns(pl.col("paid").cast(pl.Float64)).with_columns(
        cac_claim=pl.col("spend") / pl.col("claims"), cac_paid=pl.col("spend") / pl.col("paid"),
        rev_per_claim=pl.col("rev") / pl.col("claims"), roas=pl.col("rev") / pl.col("spend"))
    # incrementality-adjusted ROAS: Microsoft brand from the DiD, other brand campaigns assumed similar, others 1.0 (to test)
    incr = max(0.0, min(1.0, did["incrementality"]))
    is_ms_brand = (pl.col("traffic_source") == "microsoft_ads") & (pl.col("campaign_type") == "brand")
    ch = ch.with_columns(
        incrementality=pl.when(is_ms_brand).then(incr).when(pl.col("campaign_type") == "brand").then(None)
                         .when(pl.col("spend") > 0).then(1.0).otherwise(None),
        incr_source=pl.when(is_ms_brand).then(pl.lit("measured (France pause)"))
                      .when(pl.col("campaign_type") == "brand").then(pl.lit("untested: run the same pause"))
                      .when(pl.col("spend") > 0).then(pl.lit("assumed 100% until tested")).otherwise(pl.lit(""))).with_columns(
        incr_roas=pl.col("roas") * pl.col("incrementality"), incr_cac_paid=pl.col("cac_paid") / pl.col("incrementality"))
    ch.write_csv(OUT / "unit_economics_channel.csv")
    year_spend = con.sql("select platform, campaign_type, sum(spend_eur) s from ad_spend where date between date '2025-11-01' and date '2026-10-31' group by 1, 2").pl()
    ms_brand = year_spend.filter((pl.col("platform") == "microsoft_ads") & (pl.col("campaign_type") == "brand"))["s"].sum()
    g_brand = year_spend.filter((pl.col("platform") == "google_ads") & (pl.col("campaign_type") == "brand"))["s"].sum()
    total = year_spend["s"].sum()
    r["channels"] = ch.to_dicts()
    r["waste"] = {"ms_brand_spend_12m": ms_brand, "google_brand_spend_12m": g_brand, "incrementality": incr,
                  "ms_brand_waste_12m": ms_brand * (1 - incr), "total_spend_12m": total,
                  "note": "Google brand not tested: same test recommended before cutting it"}
    meta = ch.filter(pl.col("traffic_source") == "meta_ads").select(pl.col("spend").sum(), pl.col("paid").sum(), pl.col("rev").sum()).row(0)
    goog = ch.filter((pl.col("traffic_source") == "google_ads") & (pl.col("campaign_type") == "non_brand")).row(0, named=True)
    r["meta_cac_paid"], r["meta_roas"] = meta[0] / meta[1], meta[2] / meta[0]
    r["google_nb_cac_paid"], r["google_nb_roas"] = goog["cac_paid"], goog["roas"]

    # forecast: log(claims / seasonal index) = a + b * t per market (NL excluded: ramp-up), 6 months ahead
    s = pl.read_csv(PUB / "seasonality_uk_2025.csv").sort("month")
    idx = s["index_flights"].to_numpy() * (1 + 0.5 * (s["index_disrupted"].to_numpy() - 1)); idx = idx / idx.mean()
    mon = con.sql("""select market, date_trunc('month', cast(created_at as date)) m, count(*) claims
                     from claims where claim_id not like 'CLD%' group by 1, 2 order by 1, 2""").pl().with_columns(m=pl.col("m").cast(pl.Date))
    fc_rows, fit_rows = [], []
    horizon = [(2026, 11), (2026, 12), (2027, 1), (2027, 2), (2027, 3), (2027, 4)]
    for mkt in ["UK", "DE", "FR", "ES", "IT"]:
        g = mon.filter(pl.col("market") == mkt).sort("m")
        months = g["m"].dt.month().to_numpy()
        t = np.arange(len(g))
        y = np.log(g["claims"].to_numpy() / idx[months - 1])
        A = np.column_stack([np.ones(len(t)), t])
        coef, *_ = np.linalg.lstsq(A, y, rcond=None)
        resid = y - A @ coef
        sd = resid.std(ddof=2)
        fitted = np.exp(A @ coef) * idx[months - 1]
        mape = float(np.mean(np.abs(fitted - g["claims"].to_numpy()) / g["claims"].to_numpy()))
        for i, mm in enumerate(g["m"]):
            fit_rows.append({"market": mkt, "month": mm, "actual": int(g["claims"][i]), "fitted": float(fitted[i])})
        for h, (yy, mo) in enumerate(horizon, start=1):
            tt = len(t) - 1 + h
            mu = coef[0] + coef[1] * tt
            fc_rows.append({"market": mkt, "month": f"{yy}-{mo:02d}-01", "forecast": float(np.exp(mu) * idx[mo - 1]),
                            "low": float(np.exp(mu - 1.28 * sd) * idx[mo - 1]), "high": float(np.exp(mu + 1.28 * sd) * idx[mo - 1]),
                            "monthly_growth": float(np.exp(coef[1]) - 1), "mape_in_sample": mape})
    fc = pl.DataFrame(fc_rows).with_columns(pl.col("month").str.to_date())
    fc.write_csv(OUT / "forecast_claims.csv")
    pl.DataFrame(fit_rows).write_csv(OUT / "forecast_fit.csv")
    # budget: paid share of claims per market x forecast x target CAC per paid-channel claim (efficient channels only)
    paid_share = con.sql("""select market, avg(case when traffic_source in ('google_ads','meta_ads','microsoft_ads') then 1.0 else 0 end) s
                            from claims where claim_id not like 'CLD%' and cast(created_at as date) >= date '2026-05-01' group by 1""").pl()
    cac_cur = con.sql("""with s as (select country market, sum(spend_eur) sp from ad_spend where date >= date '2026-05-01' group by 1),
                             c as (select market, count(*) n from claims where claim_id not like 'CLD%' and cast(created_at as date) >= date '2026-05-01'
                                   and traffic_source in ('google_ads','meta_ads','microsoft_ads') group by 1)
                         select market, sp / n cac from s join c using (market)""").pl()
    b = fc.group_by("market").agg(pl.col("forecast").sum()).join(paid_share, on="market").join(cac_cur, on="market")
    b = b.with_columns(paid_claims=pl.col("forecast") * pl.col("s"), budget_current=pl.col("forecast") * pl.col("s") * pl.col("cac"))
    saving_share = r["waste"]["ms_brand_waste_12m"] / total
    b = b.with_columns(budget_proposed=pl.col("budget_current") * (1 - saving_share)).sort("budget_current", descending=True)
    b.write_csv(OUT / "budget_6m.csv")
    r["forecast"] = {"total_6m": fc["forecast"].sum(), "low_6m": fc["low"].sum(), "high_6m": fc["high"].sum(),
                     "mape": float(np.mean([x["mape_in_sample"] for x in fc_rows])),
                     "budget_current_6m": b["budget_current"].sum(), "budget_proposed_6m": b["budget_proposed"].sum()}
    # seasonality / false signal
    sy = run_sql_file("12_seasonality_yoy.sql", con).with_columns(m=pl.col("m").cast(pl.Date))
    sy.write_csv(OUT / "seasonality_yoy.csv")
    jul = sy.filter(pl.col("m") == pl.date(2026, 7, 1)).row(0, named=True)
    yoy = sy.filter(pl.col("yoy_growth").is_not_null())
    r["season"] = {"jul26_vs_jun26": jul["claims"] / jul["prev_month"] - 1, "jul26_yoy": jul["yoy_growth"],
                   "yoy_min": yoy["yoy_growth"].min(), "yoy_max": yoy["yoy_growth"].max(),
                   "jul25_vs_jun25": sy.filter(pl.col("m") == pl.date(2025, 7, 1))["claims"][0] / sy.filter(pl.col("m") == pl.date(2025, 6, 1))["claims"][0] - 1}

    # acceptance by carrier: last 5 months vs the 6 months before
    acc = con.sql("""select carrier, case when airline_response_at >= date '2026-05-01' then 'after' else 'before' end p,
                            count(*) n, sum(case when first_response = 'accepted' then 1 else 0 end) x
                     from claims where airline_response_at between date '2025-11-01' and date '2026-10-31' and claim_id not like 'CLD%'
                     group by 1, 2""").pl()
    rows = []
    for c in sorted(acc["carrier"].unique()):
        a = acc.filter((pl.col("carrier") == c) & (pl.col("p") == "before")).row(0, named=True)
        bb = acc.filter((pl.col("carrier") == c) & (pl.col("p") == "after")).row(0, named=True)
        t = z_two_props(a["x"], a["n"], bb["x"], bb["n"])
        rows.append({"carrier": c, "before": t["rate_a"], "after": t["rate_b"], "change_pts": t["diff_pts"], "p_value": t["p_value"], "n_after": bb["n"]})
    acc_t = pl.DataFrame(rows).sort("change_pts")
    acc_t.write_csv(OUT / "acceptance_change_by_carrier.csv")
    h = acc_t.row(0, named=True)
    esc = con.sql("""select avg(case when status = 'paid' then 1.0 else 0 end) from claims where carrier = 'Carrier H'
                     and first_response = 'rejected' and escalated_to_legal and legal_outcome_at is not null""").fetchall()[0][0]
    r["acceptance"] = {"carrier": h["carrier"], "before": h["before"], "after": h["after"], "p_value": h["p_value"],
                       "others_max_drop": acc_t.row(1, named=True)["change_pts"], "legal_win_rate_after_rejection": esc}

    # LTV (commission customers)
    co = run_sql_file("09_cohorts_ltv.sql", con).with_columns(cohort=pl.col("cohort").cast(pl.Date))
    co.write_csv(OUT / "cohorts_ltv.csv")
    old = co.filter(pl.col("cohort") <= pl.date(2025, 10, 1))
    ltv12 = old.filter(pl.col("age") <= 12).group_by("cohort").agg(pl.col("cum_revenue_per_customer").max())["cum_revenue_per_customer"].mean()
    repeat = con.sql("""with f as (select customer_id, min(created_at) f, count(*) n from claims where claim_id not like 'CLD%' group by 1)
                        select avg(case when n > 1 then 1.0 else 0 end) from f where f < timestamp '2025-11-01'""").fetchall()[0][0]
    blended_cac = con.sql("""select (select sum(spend_eur) from ad_spend) / (select count(*) from claims where claim_id not like 'CLD%' and traffic_source in ('google_ads','meta_ads','microsoft_ads'))""").fetchall()[0][0]
    r["ltv"] = {"ltv12_per_customer": ltv12, "repeat_rate": repeat, "paid_cac_per_claim": blended_cac, "ltv_cac": ltv12 / blended_cac}
    return r


# ---------------------------------------------------------------- subscription pricing
def subscription(con, mk):
    p_dis = mk["disrupted_share"]                       # PUBLIC: share of departing passengers on 3h+/cancelled flights
    p_elig = p_dis * AIRLINE_CONTROL
    amt = mk["avg_amount_eur"]                          # PUBLIC: average statutory amount per disrupted passenger
    bag = BAGGAGE_RATE * BAGGAGE_CLAIMABLE
    rows = []
    for trips in [1, 2, 3, 4, 6, 8, 10, 12, 15, 20]:
        flights = 2 * trips
        ev_flight, ev_bag = flights * p_elig, flights * bag
        comp = ev_flight * amt + ev_bag * BAGGAGE_VALUE
        # cost to AirAdvisor if the subscription waives the fee: handling + commission it would have earned anyway
        commission_forgone = ev_flight * amt * 0.30 + ev_bag * BAGGAGE_VALUE * 0.40
        rows.append({"trips_per_year": trips, "flights": flights, "expected_claims": ev_flight + ev_bag,
                     "expected_compensation_eur": comp, "cost_incremental_eur": (ev_flight + ev_bag) * HANDLING_COST,
                     "cost_full_cannibalisation_eur": (ev_flight + ev_bag) * HANDLING_COST + commission_forgone})
    curve = pl.DataFrame(rows)
    curve.write_csv(OUT / "subscription_cost_curve.csv")
    pilot = run_sql_file("14_subscription_pilot.sql", con).with_columns(pl.col("subscribers", "covered_claims").cast(pl.Float64))
    pilot.write_csv(OUT / "subscription_pilot.csv")
    sub = con.sql("""select tier, price_eur, declared_trips_per_year t, cooling_off_cancelled c, auto_renew_off_at is not null off,
                            date_diff('day', offer_date, date '2026-10-31') days_on
                     from subscriptions_test where subscribed""").pl()
    tiers = []
    for tier in ["Lite", "Plus", "Pro"]:
        s = sub.filter(pl.col("tier") == tier)
        t = s["t"].to_numpy().astype(float)
        cost_full = (2 * t * p_elig) * (HANDLING_COST + amt * 0.30) + (2 * t * bag) * (HANDLING_COST + BAGGAGE_VALUE * 0.40)
        cost_inc = (2 * t * (p_elig + bag)) * HANDLING_COST
        keep = ~s["c"].to_numpy()
        months = s.filter(~pl.col("c"))["days_on"].mean() / 30.4
        off = s.filter(~pl.col("c"))["off"].mean()
        annual_off = 1 - (1 - off) ** (12 / months)        # turn-off share annualised (constant hazard, assumption)
        renewal = max(0.05, 1 - annual_off)
        row = pilot.filter(pl.col("tier") == tier).row(0, named=True)
        price = row["price_eur"]
        margin_mid = price * (1 - 0.03) - (0.5 * cost_full.mean() + 0.5 * cost_inc.mean())   # 3% payment fees; cannibalisation 50%
        lifetime = 1 / (1 - renewal) if renewal < 1 else 10
        tiers.append({"tier": tier, "price_eur": price, "take_up": row["take_up"], "subscribers": row["subscribers"],
                      "trips_subscribers": row["trips_subscribers"], "trips_offered": row["trips_all_offered"],
                      "cost_per_sub_full": cost_full.mean(), "cost_per_sub_incremental": cost_inc.mean(),
                      "margin_per_sub_year": margin_mid, "cooling_off": row["cooling_off_rate"], "renewal_off_observed": off,
                      "months_observed": months, "renewal_projected": renewal, "lifetime_years": lifetime,
                      "ltv_per_sub": margin_mid * lifetime, "ltv_per_offer": margin_mid * lifetime * row["take_up"] * (1 - row["cooling_off_rate"]),
                      "share_subs_above_breakeven_trips": float(np.mean((cost_full > price)[keep])) if keep.any() else None})
    tiers = pl.DataFrame(tiers)
    tiers.write_csv(OUT / "subscription_tiers.csv")
    best = tiers.sort("ltv_per_offer", descending=True).row(0, named=True)
    be = curve.with_columns(be=pl.col("cost_full_cannibalisation_eur")).to_dicts()
    return {"p_eligible_per_flight": p_elig, "p_disrupted_per_flight": p_dis, "avg_amount_eur": amt,
            "baggage_claims_per_flight": bag, "tiers": tiers.to_dicts(), "best_tier": best["tier"], "best_price": best["price_eur"],
            "curve": be,
            "breakeven_trips_full": {t["tier"]: next((r["trips_per_year"] for r in be if r["cost_full_cannibalisation_eur"] > t["price_eur"] * 0.97), None)
                                     for t in tiers.to_dicts()}}


# ---------------------------------------------------------------- detection vs answer key
def detection(res):
    truth = pl.read_csv(DATA / "_hidden_truth.csv")
    t = res["tracking"]; te = res["testing"]; sp = res["spend"]
    found = {
        "broken_tag": (t["tag_break"]["detected"] is not None, t["tag_break"]["detected"], "03 daily GA4/CRM ratio, 3 alerts in a row"),
        "consent_mode": (t["consent"]["de_change_week"] is not None, t["consent"]["de_change_week"], "04 weekly coverage, 3-sd drop, CRM flat"),
        "double_counting": (t["platforms"]["over_total"] > 1.2, "all period", "06 platform conversions vs CRM last click"),
        "brand_cannibalisation": (te["did"]["incrementality"] < 0.5, "2026-02-02", "10 + regression DiD"),
        "ab_srm": (te["srm"]["ga_p"] < 0.001, "2026-06-01", "11 chi-square on exposures vs server log"),
        "acceptance_drop": (sp["acceptance"]["carrier"] == "Carrier H" and sp["acceptance"]["p_value"] < 0.001, "2026-05", "08 + two-proportion z-test"),
        "seasonal_peak": (abs(sp["season"]["jul26_yoy"] - np.median([sp["season"]["yoy_min"], sp["season"]["yoy_max"]])) < 0.15, "2026-07",
                          "12 YoY growth stable while month-on-month jumps"),
        "duplicates": (t["duplicates"]["count"] > 0, t["duplicates"]["day"], "05 LAG window, same key within 5 min"),
    }
    rows = []
    for r in truth.iter_rows(named=True):
        ok, when, how = found[r["event"]]
        rows.append({"id": r["id"], "event": r["event"], "planted": r["description"], "true_start": r["start"],
                     "detected": bool(ok), "detected_at": str(when), "method": how})
    det = pl.DataFrame(rows)
    det.write_csv(OUT / "detection_scorecard.csv")
    return {"found": int(det["detected"].sum()), "total": det.height, "rows": det.to_dicts()}


def main():
    utf8()
    OUT.mkdir(parents=True, exist_ok=True)
    con = sim_con()
    res = {"market": market()}
    res["tracking"] = tracking(con)
    res["testing"] = testing(con)
    res["spend"] = spend(con, res["testing"]["did"])
    res["subscription"] = subscription(con, res["market"])
    res["detection"] = detection(res)
    (OUT / "results.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    m, t, te, s, sb = res["market"], res["tracking"], res["testing"], res["spend"], res["subscription"]
    print(f"MARKET ceiling {m['ceiling_eur']/1e9:.2f}bn | TAM {m['tam_eur']/1e6:.0f}M | SAM {m['sam_eur']/1e6:.0f}M | SOM {m['som_eur']/1e6:.1f}M | top5 {m['top5']} stable={m['ranking_stable_top5']}")
    print(f"TAG break detected {t['tag_break']['detected']} ratio {t['tag_break']['ratio_before']:.2f}->{t['tag_break']['ratio_after']:.2f}, unseen {t['tag_break']['crm_claims_unseen_by_ga4']}")
    print(f"CONSENT {t['consent']}")
    print(f"PLATFORMS over x{t['platforms']['over_total']:.2f} | DUPS {t['duplicates']}")
    print(f"SRM ga p={te['srm']['ga_p']:.2e} shareB={te['srm']['ga_share_b']:.3f} mobile shareB={te['srm']['mobile_share_b']:.3f} server p={te['srm']['server_p']:.2f}")
    print(f"RAW lift {te['raw']['lift_rel']:+.1%} p={te['raw']['p_value']:.4f} | ITT lift {te['itt']['lift_rel']:+.1%} p={te['itt']['p_value']:.3f} | power {te['power']}")
    print(f"DID {te['did']}")
    print(f"WASTE {s['waste']} | meta CAC paid {s['meta_cac_paid']:.0f} roas {s['meta_roas']:.2f} | google nb {s['google_nb_cac_paid']:.0f} {s['google_nb_roas']:.2f}")
    print(f"FORECAST {s['forecast']} | SEASON {s['season']} | ACC {s['acceptance']} | LTV {s['ltv']}")
    print(f"SUB p_elig {sb['p_eligible_per_flight']:.4f} amt {sb['avg_amount_eur']:.0f} best {sb['best_tier']} be {sb['breakeven_trips_full']}")
    for r in sb["tiers"]:
        print({k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items()})
    print(f"DETECTION {res['detection']['found']}/{res['detection']['total']}")


if __name__ == "__main__":
    main()
