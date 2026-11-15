"""Country-by-country claim opportunity model (PUBLIC DATA). Run after src/download_data.py.

Logic, per departure country (EU261 states from Eurostat, UK from the CAA):
  passengers on each route (Eurostat 2024 / CAA 2025)
  x share of flights 3h+ late or cancelled (UK CAA punctuality 2025, routes between the UK and that country)
  x statutory amount for the route distance (EU261 / UK261 bands, distances from OurAirports coordinates)
  = THEORETICAL CEILING: what would be owed if every disruption were the airline's responsibility and every
    passenger claimed. It is NOT money owed: extraordinary circumstances (weather, air traffic control, security...)
    remove the right to compensation, and most passengers never claim.
  then x share within the airline's control x fee        = TAM (agency revenue if every eligible passenger used an agency)
       x claim rate x agency share x airline payout rate = SAM
       x share AirAdvisor could win                      = SOM

Outputs (data/public/): disruption_rates.csv, market_opportunity.csv, market_sensitivity.csv, rank_stability.csv,
us_benchmark.csv, seasonality_uk_2025.csv, route_band_mix.csv ; data/processed/routes_departures.parquet
"""
import json
import re

import duckdb
import numpy as np
import polars as pl

from common import COUNTRY_NAME, EU261_STATES, PROC, PUB, RAW, utf8

# ---------------------------------------------------------------- assumptions (central, low, high) - see data/ASSUMPTIONS.md
A = {
    "airline_control": (0.55, 0.40, 0.70),   # share of 3h+/cancelled disruptions NOT due to extraordinary circumstances
    "claim_rate":      (0.35, 0.20, 0.50),   # share of eligible passengers who claim at all
    "agency_share":    (0.45, 0.30, 0.60),   # share of claims filed through a claim agency (vs directly)
    "payout_rate":     (0.85, 0.75, 0.95),   # share of agency claims the airline finally pays (agencies pre-screen)
    "fee":             (0.30, 0.25, 0.35),   # AirAdvisor's published success fee, pre-trial, VAT included
    "obtainable":      (0.12, 0.06, 0.20),   # share of the agency market AirAdvisor could win in a country
}
VARIABLE_COST = 0.30   # ops + legal cost as a share of revenue per claim (assumption) -> break-even CAC
SHRINK_FLIGHTS = 3000  # empirical-Bayes weight: countries with few UK flights are pulled toward the European mean

CAA_TO_CODE = {"AUSTRIA": "AT", "BELGIUM": "BE", "BULGARIA": "BG", "CYPRUS": "CY", "CZECH REPUBLIC": "CZ", "GERMANY": "DE",
               "DENMARK": "DK", "ESTONIA": "EE", "GREECE": "EL", "SPAIN": "ES", "SPAIN(CANARY ISLANDS)": "ES", "FINLAND": "FI",
               "FRANCE": "FR", "CROATIA": "HR", "HUNGARY": "HU", "IRISH REPUBLIC": "IE", "ITALY": "IT", "LITHUANIA": "LT",
               "LUXEMBOURG": "LU", "LATVIA": "LV", "MALTA": "MT", "NETHERLANDS": "NL", "POLAND": "PL",
               "PORTUGAL(EXCLUDING MADEIRA)": "PT", "PORTUGAL(MADEIRA)": "PT", "ROMANIA": "RO", "SWEDEN": "SE",
               "SLOVENIA": "SI", "SLOVAK REPUBLIC": "SK", "ICELAND": "IS", "NORWAY": "NO", "SWITZERLAND": "CH",
               "UNITED KINGDOM": "UK"}
EU_ISO = {c: ("GR" if c == "EL" else c) for c in EU261_STATES}  # Eurostat -> ISO 3166 (OurAirports)


def haversine(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi, dl = p2 - p1, np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def airports():
    return duckdb.sql(f"""
        select ident, iata_code, upper(name) as name, upper(coalesce(municipality, '')) as municipality, iso_country,
               type, cast(scheduled_service as varchar) in ('yes', 'true') as scheduled_service, latitude_deg as lat, longitude_deg as lon
        from read_csv_auto('{(RAW / 'ourairports' / 'airports.csv').as_posix()}')
        where type in ('large_airport', 'medium_airport', 'small_airport')""").pl()


# ---------------------------------------------------------------- 1. Eurostat routes (departures, 2024)
def eurostat_routes(ap):
    rows = []
    for c in EU261_STATES:
        files = sorted((RAW / "eurostat").glob(f"avia_par_{c.lower()}_*.json"))
        if not files:
            continue
        js = json.loads(files[-1].read_text(encoding="utf-8"))
        year = files[-1].stem.split("_")[-1]
        idx = js["dimension"]["airp_pr"]["category"]["index"]
        for code, i in idx.items():
            v = js["value"].get(str(i))
            parts = code.split("_")
            if v is None or len(parts) != 4:
                continue
            rows.append({"country": c, "year": int(year), "orig_icao": parts[1], "dest_cc": parts[2], "dest_icao": parts[3], "pax": float(v)})
    r = pl.DataFrame(rows)
    coords = ap.select("ident", "lat", "lon")
    r = (r.join(coords.rename({"ident": "orig_icao", "lat": "o_lat", "lon": "o_lon"}), on="orig_icao", how="left")
          .join(coords.rename({"ident": "dest_icao", "lat": "d_lat", "lon": "d_lon"}), on="dest_icao", how="left"))
    r = r.with_columns(pl.Series("distance_km", haversine(r["o_lat"].to_numpy(), r["o_lon"].to_numpy(),
                                                          r["d_lat"].to_numpy(), r["d_lon"].to_numpy())))
    matched = r.filter(pl.col("distance_km").is_not_nan())["pax"].sum() / r["pax"].sum()
    print(f"Eurostat routes: {len(r):,} airport pairs, {r['pax'].sum() / 1e6:,.0f}M departing passengers, "
          f"{matched:.1%} of passengers with coordinates")
    return r.filter(pl.col("distance_km").is_not_nan()).with_columns(
        intra=pl.col("dest_cc").is_in(EU261_STATES), regime=pl.lit("EU261"), currency=pl.lit("EUR"))


# ---------------------------------------------------------------- 2. UK routes (CAA 2025, airport names -> coordinates)
def _norm(s):
    s = re.sub(r"\(.*?\)", " ", s.upper())
    s = re.sub(r"[^A-Z ]", " ", s)
    return " ".join(w for w in s.split() if w not in {"INTERNATIONAL", "INT", "L", "AIRPORT", "MAIN", "CITY"})


def match_names(names_countries, ap, iso_of):
    """Map CAA airport names to coordinates: exact municipality, then first word of municipality or name, in the same country."""
    ap = ap.filter(pl.col("scheduled_service"))
    rank = {"large_airport": 0, "medium_airport": 1, "small_airport": 2}
    by_country = {}
    for row in ap.iter_rows(named=True):
        by_country.setdefault(row["iso_country"], []).append(row)
    for lst in by_country.values():
        lst.sort(key=lambda r: rank[r["type"]])
    out = {}
    for name, country in names_countries:
        iso = iso_of(country)
        cands = by_country.get(iso, [])
        n = _norm(name)
        first = n.split()[0] if n else ""
        hit = next((a for a in cands if a["municipality"] == n), None) \
            or next((a for a in cands if first and (a["municipality"].startswith(first) or first in a["name"].split())), None)
        if hit is None and "(" in name:  # e.g. "TENERIFE (SURREINA SOFIA)" -> try the words inside the brackets
            inner = _norm(name.split("(")[1])
            hit = next((a for a in cands if inner and inner.split()[0] in a["name"]), None)
        if hit:
            out[(name, country)] = (hit["lat"], hit["lon"])
    return out


def uk_routes(ap):
    countries = {r[2].upper(): r[1] for r in duckdb.sql(
        f"select * from read_csv_auto('{(RAW / 'ourairports' / 'countries.csv').as_posix()}')").fetchall()}
    fix = {"USA": "US", "IRISH REPUBLIC": "IE", "UNITED KINGDOM": "GB", "CZECH REPUBLIC": "CZ", "SLOVAK REPUBLIC": "SK",
           "SPAIN(CANARY ISLANDS)": "ES", "PORTUGAL(EXCLUDING MADEIRA)": "PT", "PORTUGAL(MADEIRA)": "PT",
           "REPUBLIC OF KOREA": "KR", "REPUBLIC OF SOUTH AFRICA": "ZA", "REPUBLIC OF SERBIA": "RS", "REPUBLIC OF MONTENEGRO": "ME",
           "REPUBLIC OF MOLDOVA": "MD", "MACEDONIA": "MK", "BOSNIA-HERZEGOVINA": "BA", "TURKEY": "TR", "CAPE VERDE ISLANDS": "CV",
           "MALDIVE ISLANDS": "MV", "ISLE OF CURACAO NETH.ANTILLES": "CW", "ST LUCIA": "LC", "ST MAARTEN": "SX",
           "HONG KONG": "HK", "TAIWAN": "TW", "BRUNEI": "BN", "VIETNAM": "VN", "IRAN": "IR", "RUSSIA": "RU",
           "ISLE OF DIEGO GARCIA": "IO", "KOSOVO": "XK", "GAMBIA": "GM", "BAHAMAS": "BS"}
    iso_of = lambda c: fix.get(c) or countries.get(c, "")  # noqa: E731
    intl = duckdb.sql(f"""select foreign_country, uk_apt, foreign_apt, sum(ty_t_pax)::double as pax
        from read_csv_auto('{(RAW / 'caa' / 'caa_2025_table_12_1_intl_routes.csv').as_posix()}') group by all""").pl()
    dom = duckdb.sql(f"""select 'UNITED KINGDOM' as foreign_country, apt1_apt_name as uk_apt, apt2_apt_name as foreign_apt,
        sum(total_pax_tp)::double as pax from read_csv_auto('{(RAW / 'caa' / 'caa_2025_table_12_2_domestic_routes.csv').as_posix()}') group by all""").pl()
    r = pl.concat([intl, dom])
    uk_iso = lambda c: "GB"  # noqa: E731
    uk_names = set((a, "UNITED KINGDOM") for a in r["uk_apt"].unique())
    m_uk = match_names(uk_names, ap.filter(pl.col("iso_country").is_in(["GB", "JE", "GG", "IM"])).with_columns(iso_country=pl.lit("GB")), uk_iso)
    m_f = match_names(set(zip(r["foreign_apt"], r["foreign_country"])), ap, iso_of)
    # Channel Islands / Isle of Man airports are listed under their own ISO codes in OurAirports
    m_f.update({k: v for k, v in match_names(set(zip(r["foreign_apt"], r["foreign_country"])),
                                             ap.filter(pl.col("iso_country").is_in(["GB", "JE", "GG", "IM"])).with_columns(iso_country=pl.lit("GB")),
                                             lambda c: "GB" if c == "UNITED KINGDOM" else "").items() if k not in m_f})
    lat_o = [m_uk.get((a, "UNITED KINGDOM"), (np.nan, np.nan))[0] for a in r["uk_apt"]]
    lon_o = [m_uk.get((a, "UNITED KINGDOM"), (np.nan, np.nan))[1] for a in r["uk_apt"]]
    lat_d = [m_f.get((a, c), (np.nan, np.nan))[0] for a, c in zip(r["foreign_apt"], r["foreign_country"])]
    lon_d = [m_f.get((a, c), (np.nan, np.nan))[1] for a, c in zip(r["foreign_apt"], r["foreign_country"])]
    r = r.with_columns(pl.Series("distance_km", haversine(np.array(lat_o, float), np.array(lon_o, float),
                                                          np.array(lat_d, float), np.array(lon_d, float))))
    # unmatched routes: use the passenger-weighted median distance of the matched routes to the same country
    med = r.filter(pl.col("distance_km").is_not_nan()).group_by("foreign_country").agg(med_km=pl.col("distance_km").median())
    share = r.filter(pl.col("distance_km").is_not_nan())["pax"].sum() / r["pax"].sum()
    r = r.join(med, on="foreign_country", how="left").with_columns(
        distance_km=pl.when(pl.col("distance_km").is_nan()).then(pl.col("med_km")).otherwise(pl.col("distance_km")))
    print(f"CAA routes: {len(r):,} routes, {r['pax'].sum() / 1e6:,.0f}M terminal passengers, {share:.1%} matched to "
          f"airport coordinates, {r.filter(pl.col('distance_km').is_null())['pax'].sum() / r['pax'].sum():.1%} without any distance")
    r = r.filter(pl.col("distance_km").is_not_null())
    # CAA counts terminal passengers on both directions of a route: departures from the UK ~ half
    return r.select(country=pl.lit("UK"), year=pl.lit(2025), orig_icao=pl.col("uk_apt"),
                    dest_cc=pl.col("foreign_country").replace(CAA_TO_CODE), dest_icao=pl.col("foreign_apt"),
                    pax=pl.col("pax").cast(pl.Float64) / 2, distance_km=pl.col("distance_km"),
                    intra=(pl.col("foreign_country") == "UNITED KINGDOM"), regime=pl.lit("UK261"), currency=pl.lit("GBP"))


# ---------------------------------------------------------------- 3. disruption rates (CAA 2025, UK <-> country)
def disruption_rates():
    f = (RAW / "caa" / "caa_2025_full_analysis_arr_dep.csv").as_posix()
    d = duckdb.sql(f"""
        select origin_destination_country as caa_country, arrival_departure as dir,
               sum(number_flights_matched)::double as operated, sum(number_flights_cancelled)::double as cancelled,
               sum(number_flights_matched * (flights_between_181_and_360_minutes_late_percent + flights_more_than_360_minutes_late_percent) / 100) as late_3h,
               sum(number_flights_matched * flights_more_than_360_minutes_late_percent / 100) as late_6h,
               sum(number_flights_matched * (100 - flights_more_than_15_minutes_early_percent - flights_15_minutes_early_to_1_minute_early_percent - flights_0_to_15_minutes_late_percent) / 100) as late_15
        from read_csv_auto('{f}') group by all""").pl()
    # UK row = every flight in the file (all destinations); other rows = flights between the UK and that country
    d_uk = d.with_columns(code=pl.lit("UK"))
    d = d.with_columns(code=pl.col("caa_country").replace_strict(CAA_TO_CODE, default=None))          .filter(pl.col("code").is_not_null() & (pl.col("code") != "UK"))
    d = pl.concat([d, d_uk.select(d.columns)])

    def rates(frame, label):
        g = frame.group_by("code").agg(pl.col("operated", "cancelled", "late_3h", "late_6h", "late_15").sum())
        tot = g.select(pl.col("operated", "cancelled", "late_3h").sum()).row(0, named=True)
        p3_all, pc_all = tot["late_3h"] / tot["operated"], tot["cancelled"] / (tot["operated"] + tot["cancelled"])
        k = SHRINK_FLIGHTS
        return g.with_columns(
            p_late3_raw=pl.col("late_3h") / pl.col("operated"),
            p_cancel_raw=pl.col("cancelled") / (pl.col("operated") + pl.col("cancelled")),
            p_late15=pl.col("late_15") / pl.col("operated"),
            p_late3=(pl.col("late_3h") + k * p3_all) / (pl.col("operated") + k),
            p_cancel=(pl.col("cancelled") + k * pc_all) / (pl.col("operated") + pl.col("cancelled") + k),
            measure=pl.lit(label))

    both = rates(d, "both directions (shrunk)")
    arr = rates(d.filter(pl.col("dir") == "A"), "arrivals into the UK only")
    dep = rates(d.filter(pl.col("dir") == "D"), "departures from the UK only")
    return both, arr, dep


def seasonality():
    """Monthly share of UK flights 3h+ late or cancelled, and flight volume (CAA monthly files 2025)."""
    rows = []
    for m in range(1, 13):
        f = RAW / "caa" / f"caa_2025{m:02d}_full_analysis.csv"
        if not f.exists():
            continue
        x = duckdb.sql(f"""select sum(number_flights_matched)::double as operated, sum(number_flights_cancelled)::double as cancelled,
            sum(number_flights_matched * (flights_between_181_and_360_minutes_late_percent + flights_more_than_360_minutes_late_percent) / 100) as late_3h
            from read_csv_auto('{f.as_posix()}')""").fetchall()[0]
        rows.append({"month": m, "flights": x[0] + x[1], "operated": x[0], "cancelled": x[1], "late_3h": x[2]})
    s = pl.DataFrame(rows).with_columns(
        disrupted=pl.col("late_3h") + pl.col("cancelled"),
        disruption_rate=(pl.col("late_3h") + pl.col("cancelled")) / pl.col("flights"))
    return s.with_columns(index_flights=pl.col("flights") / pl.col("flights").mean(),
                          index_disrupted=pl.col("disrupted") / pl.col("disrupted").mean())


def us_benchmark():
    f = (PROC / "bts_routes_2025.parquet").as_posix()
    tot = duckdb.sql(f"""select sum(flights) as flights, sum(cancelled) as cancelled, sum(diverted) as diverted,
        sum(arr_delay_15) as late_15, sum(arr_delay_180) as late_3h, sum(arr_delay_240) as late_4h, sum(arr_delay_360) as late_6h,
        sum(carrier_delay_min_on_180) as carrier_min, sum(arr_delay_min_on_180) as delay_min from '{f}'""").pl().cast(pl.Float64)
    by_month = duckdb.sql(f"""select month, sum(flights) as flights, sum(cancelled) as cancelled, sum(arr_delay_180) as late_3h
        from '{f}' group by month order by month""").pl()
    t = tot.row(0, named=True)
    operated = t["flights"] - t["cancelled"] - t["diverted"]
    bench = pl.DataFrame({
        "metric": ["flights", "cancel_rate", "late_15_rate", "late_3h_rate", "share_3to4h_of_3h", "carrier_share_of_3h_delay_minutes"],
        "value": [t["flights"], t["cancelled"] / t["flights"], t["late_15"] / operated, t["late_3h"] / operated,
                  1 - t["late_4h"] / t["late_3h"], t["carrier_min"] / t["delay_min"]]})
    return bench, by_month


# ---------------------------------------------------------------- 4. money per route
def amounts(routes, gbp_eur, share_3to4):
    d, intra, uk = pl.col("distance_km"), pl.col("intra"), pl.col("regime") == "UK261"
    # EU261 Art. 7(1): 250 (<=1500 km), 400 (intra-Community > 1500 km, or 1500-3500 km), 600 (other)
    eu = pl.when(d <= 1500).then(250).when(intra | (d <= 3500)).then(400).otherwise(600)
    ukm = pl.when(d <= 1500).then(220).when(intra | (d <= 3500)).then(350).otherwise(520)
    band = pl.when(d <= 1500).then(pl.lit("short (<=1,500 km)")).when(intra | (d <= 3500)).then(pl.lit("medium (1,500-3,500 km)")).otherwise(pl.lit("long (>3,500 km)"))
    base = pl.when(uk).then(ukm * gbp_eur).otherwise(eu)
    long_ = (d > 3500) & ~intra
    # long-haul arrival delay of 3-4h: amount halved (EU261 Art. 7(2)(c) as applied by the CJEU; CAA: £260)
    delay_amt = pl.when(long_).then(base * (1 - 0.5 * share_3to4)).otherwise(base)
    return routes.with_columns(band=band, amount_eur=base.cast(pl.Float64), delay_amount_eur=delay_amt.cast(pl.Float64))


def market(routes, rates, cz_pax=None, a=None):
    a = a or {k: v[0] for k, v in A.items()}
    rt = routes.join(rates.select("code", "p_late3", "p_cancel"), left_on="country", right_on="code", how="left")
    rt = rt.with_columns(
        pax_late3=pl.col("pax") * pl.col("p_late3"),
        pax_cancel=pl.col("pax") * pl.col("p_cancel") / (1 - pl.col("p_cancel")),  # carried pax exclude cancelled flights
    ).with_columns(
        ceiling_eur=pl.col("pax_late3") * pl.col("delay_amount_eur") + pl.col("pax_cancel") * pl.col("amount_eur"))
    m = rt.group_by("country").agg(
        regime=pl.col("regime").first(), data_year=pl.col("year").first(),
        departing_pax=pl.col("pax").sum(), disrupted_pax=(pl.col("pax_late3") + pl.col("pax_cancel")).sum(),
        ceiling_eur=pl.col("ceiling_eur").sum(),
        long_haul_pax_share=pl.col("pax").filter(pl.col("band") == "long (>3,500 km)").sum() / pl.col("pax").sum())
    if cz_pax:  # Czechia: no airport-pair table at Eurostat -> national total x European average per passenger
        avg = m.select(pl.col("ceiling_eur").sum() / pl.col("departing_pax").sum(),
                       pl.col("disrupted_pax").sum() / pl.col("departing_pax").sum()).row(0)
        m = pl.concat([m, pl.DataFrame({"country": ["CZ"], "regime": ["EU261"], "data_year": [2024], "departing_pax": [cz_pax],
                                        "disrupted_pax": [cz_pax * avg[1]], "ceiling_eur": [cz_pax * avg[0]],
                                        "long_haul_pax_share": [None]})], how="diagonal_relaxed")
    m = m.with_columns(
        avg_amount_eur=pl.col("ceiling_eur") / pl.col("disrupted_pax"),
        eligible_pax=pl.col("disrupted_pax") * a["airline_control"],
    ).with_columns(
        tam_eur=pl.col("ceiling_eur") * a["airline_control"] * a["fee"],
    ).with_columns(
        sam_eur=pl.col("tam_eur") * a["claim_rate"] * a["agency_share"] * a["payout_rate"],
        sam_claims=pl.col("eligible_pax") * a["claim_rate"] * a["agency_share"],
    ).with_columns(
        som_eur=pl.col("sam_eur") * a["obtainable"],
        som_claims=pl.col("sam_claims") * a["obtainable"],
    ).with_columns(
        revenue_per_claim_eur=pl.col("som_eur") / pl.col("som_claims"),
    ).with_columns(breakeven_cac_eur=pl.col("revenue_per_claim_eur") * (1 - VARIABLE_COST))
    return m.sort("som_eur", descending=True).with_columns(rank=pl.int_range(1, pl.len() + 1))


def main():
    utf8()
    PUB.mkdir(parents=True, exist_ok=True)
    ap = airports()
    gbp_eur = 1 / float(duckdb.sql(f"select OBS_VALUE from read_csv_auto('{(RAW / 'ecb' / 'gbp_eur_annual.csv').as_posix()}') where TIME_PERIOD = 2025").fetchall()[0][0])
    bench, us_month = us_benchmark()
    share_3to4 = bench.filter(pl.col("metric") == "share_3to4h_of_3h")["value"][0]
    print(f"GBP->EUR 2025 (ECB annual average): {gbp_eur:.4f}; BTS share of 3h+ delays that are 3-4h: {share_3to4:.1%}")

    routes = pl.concat([eurostat_routes(ap), uk_routes(ap)], how="diagonal_relaxed")
    routes = amounts(routes, gbp_eur, share_3to4)
    routes.select("country", "year", "orig_icao", "dest_cc", "dest_icao", "pax", "distance_km", "intra", "regime", "band",
                  "amount_eur").sort("country", "orig_icao", "dest_icao", "pax", "distance_km").write_parquet(PROC / "routes_departures.parquet")
    mix = routes.group_by("country", "band").agg(pax=pl.col("pax").sum()).with_columns(
        share=pl.col("pax") / pl.col("pax").sum().over("country")).sort("country", "band")
    mix.write_csv(PUB / "route_band_mix.csv")

    both, arr, dep = disruption_rates()
    both.with_columns(country_name=pl.col("code").replace(COUNTRY_NAME)).sort("p_late3", descending=True).write_csv(PUB / "disruption_rates.csv")

    js = json.loads((RAW / "eurostat" / "avia_paoc.json").read_text(encoding="utf-8"))
    geo, tim = js["dimension"]["geo"]["category"]["index"], js["dimension"]["time"]["category"]["index"]
    ng, nt = len(geo), len(tim)
    paoc = {(g, t): js["value"].get(str(gi * nt + ti)) for g, gi in geo.items() for t, ti in tim.items()}
    cz_pax = (paoc.get(("CZ", "2024")) or 0) / 2  # total carried (arrivals + departures) -> departures ~ half

    m = market(routes, both, cz_pax)
    growth = pl.DataFrame([{"country": c, "pax_2019": paoc.get((c, "2019")), "pax_2024": paoc.get((c, "2024"))} for c in EU261_STATES])
    m = m.join(growth, on="country", how="left").with_columns(
        growth_2019_2024=pl.col("pax_2024") / pl.col("pax_2019") - 1,
        country_name=pl.col("country").replace(COUNTRY_NAME))
    m = m.join(both.select(pl.col("code").alias("country"), "operated", "p_late3", "p_cancel", "p_late15"), on="country", how="left")
    m.write_csv(PUB / "market_opportunity.csv")

    # sensitivity 1: tornado on total SOM (each assumption at its low and high value, the others central)
    central = m["som_eur"].sum()
    tor = []
    for k, (c, lo, hi) in A.items():
        for lab, v in (("low", lo), ("high", hi)):
            a = {kk: vv[0] for kk, vv in A.items()} | {k: v}
            tor.append({"assumption": k, "case": lab, "value": v, "som_total_eur": market(routes, both, cz_pax, a)["som_eur"].sum(),
                        "central_eur": central})
    tor.append({"assumption": "disruption share (CAA)", "case": "low", "value": None, "central_eur": central,
                "som_total_eur": market(routes, both.with_columns(pl.col("p_late3") * 0.8, pl.col("p_cancel") * 0.8), cz_pax)["som_eur"].sum()})
    tor.append({"assumption": "disruption share (CAA)", "case": "high", "value": None, "central_eur": central,
                "som_total_eur": market(routes, both.with_columns(pl.col("p_late3") * 1.2, pl.col("p_cancel") * 1.2), cz_pax)["som_eur"].sum()})
    pl.DataFrame(tor).write_csv(PUB / "market_sensitivity.csv")

    # sensitivity 2: does the ranking change with the way disruption is measured?
    def ranks(rates_df, label, raw=False):
        r = rates_df.with_columns(p_late3=pl.col("p_late3_raw"), p_cancel=pl.col("p_cancel_raw")) if raw else rates_df
        return market(routes, r, cz_pax).select("country", pl.col("rank").alias(label))
    st = ranks(both, "central").join(ranks(both, "no_shrinkage", raw=True), on="country") \
        .join(ranks(arr, "arrivals_only"), on="country").join(ranks(dep, "departures_only"), on="country")
    lo_case = market(routes, both, cz_pax, {k: v[1] for k, v in A.items()}).select("country", pl.col("rank").alias("all_low"))
    st = st.join(lo_case, on="country").sort("central")
    st.write_csv(PUB / "rank_stability.csv")

    seas = seasonality()
    seas.write_csv(PUB / "seasonality_uk_2025.csv")
    bench.write_csv(PUB / "us_benchmark.csv")
    us_month.write_csv(PUB / "us_monthly_2025.csv")

    print(f"\nTotal ceiling {m['ceiling_eur'].sum() / 1e9:.2f}bn EUR | TAM {m['tam_eur'].sum() / 1e6:,.0f}M | "
          f"SAM {m['sam_eur'].sum() / 1e6:,.0f}M | SOM {central / 1e6:,.0f}M EUR")
    print(m.select("rank", "country", "departing_pax", "p_late3", "p_cancel", "avg_amount_eur", "ceiling_eur", "som_eur",
                   "breakeven_cac_eur").head(12))
    print(st.head(10))


if __name__ == "__main__":
    main()
