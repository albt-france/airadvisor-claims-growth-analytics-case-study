"""Download the public data used in the report (PUBLIC DATA). Raw files go to data/raw/ (not in git).

Sources (all free to re-use with attribution, see data/SOURCES.md):
  1. Eurostat avia_par_<country>: passengers carried, airport pair, 2024, departures   (Eurostat API, JSON-stat)
  2. Eurostat avia_paoc: passengers carried by reporting country, 2019-2024              (Eurostat API, JSON-stat)
  3. UK CAA punctuality statistics 2025: delay bands and cancellations by route and airline (CSV)
  4. US BTS On-Time Performance 2025, one zip per month (public domain)                   (large: ~330 MB zipped)
  5. OurAirports airports.csv: airport coordinates, to compute route distances (public domain)

Each file is downloaded once (cached), with a pause between requests. Then run src/build_public.py.
Usage:  python src/download_data.py [--skip-bts]
"""
import argparse
import re
import sys
import time
import zipfile
from pathlib import Path

import duckdb
import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"
UA = {"User-Agent": "Mozilla/5.0 (compatible; case-study-research/1.0)"}
EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
# EU27 + EFTA countries that report air passenger data to Eurostat (Eurostat 2-letter codes, Greece = EL)
COUNTRIES = ["AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "ES", "FI", "FR", "HR", "HU", "IE", "IT",
             "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SI", "SK", "IS", "NO", "CH"]
CAA_2025 = {  # links listed on caa.co.uk > UK flight punctuality statistics > 2025 (checked 2026-11-15)
    "caa_2025_full_analysis.csv": "https://www.caa.co.uk/Documents/Download/24022/3d82eddc-84f7-4692-bc12-a9ab96562d04/1714",
    "caa_2025_full_analysis_arr_dep.csv": "https://www.caa.co.uk/Documents/Download/24022/3d82eddc-84f7-4692-bc12-a9ab96562d04/1715",
}
CAA_AIRPORT_2025 = {  # caa.co.uk > UK airport data > 2025 > annual 2025 (passengers by route)
    "caa_2025_table_12_1_intl_routes.csv": "https://www.caa.co.uk/Documents/Download/24007/87fb7670-4e10-4aeb-942d-509238aa25a1/17509",
    "caa_2025_table_12_2_domestic_routes.csv": "https://www.caa.co.uk/Documents/Download/24007/87fb7670-4e10-4aeb-942d-509238aa25a1/17510",
}
CAA_PUNCT_PAGE = "https://www.caa.co.uk/data-and-analysis/uk-aviation-market/flight-punctuality/uk-flight-punctuality-statistics/2025/"
BTS_URL ="https://transtats.bts.gov/PREZIP/On_Time_Reporting_Carrier_On_Time_Performance_1987_present_{y}_{m}.zip"
OURAIRPORTS = "https://davidmegginson.github.io/ourairports-data/airports.csv"


def get(url, path, params=None, pause=2):
    """Download url to path unless it is already there."""
    if path.exists() and path.stat().st_size > 0:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, params=params, headers=UA, timeout=600, stream=True) as r:
        r.raise_for_status()
        tmp = path.with_suffix(path.suffix + ".part")
        with open(tmp, "wb") as fh:
            for chunk in r.iter_content(1 << 20):
                fh.write(chunk)
        tmp.replace(path)
    print(f"  downloaded {path.relative_to(ROOT)} ({path.stat().st_size / 1e6:.1f} MB)")
    time.sleep(pause)
    return path


def eurostat():
    print("Eurostat ...")
    for c in COUNTRIES:
        # 2024 is the latest complete year; a few countries report later, so fall back to 2023
        for year in ("2024", "2023"):
            try:
                get(EUROSTAT + f"avia_par_{c.lower()}", RAW / "eurostat" / f"avia_par_{c.lower()}_{year}.json",
                    params={"format": "JSON", "lang": "EN", "freq": "A", "time": year, "unit": "PAS", "tra_meas": "PAS_CRD_DEP"})
                break
            except requests.HTTPError as e:
                print(f"  {c} {year}: {e.response.status_code}, trying an earlier year" if year == "2024" else f"  {c}: no data, skipped")
                time.sleep(2)
    get(EUROSTAT + "avia_paoc", RAW / "eurostat" / "avia_paoc.json",
        params=[("format", "JSON"), ("lang", "EN"), ("freq", "A"), ("unit", "PAS"), ("tra_meas", "PAS_CRD"),
                ("tra_cov", "TOTAL"), ("schedule", "TOTAL")] + [("time", str(y)) for y in range(2019, 2025)])
    get(EUROSTAT + "avia_paoc", RAW / "eurostat" / "avia_paoc_monthly_2024.json",
        params=[("format", "JSON"), ("lang", "EN"), ("freq", "M"), ("unit", "PAS"), ("tra_meas", "PAS_CRD"),
                ("tra_cov", "TOTAL"), ("schedule", "TOTAL")] + [("time", f"2024-{m:02d}") for m in range(1, 13)])


def caa():
    print("UK CAA ...")
    for name, url in CAA_2025.items():
        get(url, RAW / "caa" / name)
    for name, url in CAA_AIRPORT_2025.items():
        get(url, RAW / "caa" / name)
    # monthly punctuality files: read the links from the public 2025 page (label "2025MM Punctuality Statistics Full Analysis (CSV")
    page = requests.get(CAA_PUNCT_PAGE, headers=UA, timeout=60).text.replace("\n", " ")
    for m in range(1, 13):
        hit = re.search(r'href="(/Documents/Download/[^"]+)"[^>]*>(?:\s|<[^>]+>)*2025%02d Punctuality Statistics Full Analysis \(CSV' % m, page)
        if hit:
            get("https://www.caa.co.uk" + hit.group(1), RAW / "caa" / f"caa_2025{m:02d}_full_analysis.csv")
        else:
            print(f"  month {m:02d}: link not found on the page")


def ecb_fx():
    print("ECB GBP/EUR ...")
    get("https://data-api.ecb.europa.eu/service/data/EXR/A.GBP.EUR.SP00.A",
        RAW / "ecb" / "gbp_eur_annual.csv", params={"format": "csvdata", "startPeriod": "2023"})


def bts(year=2025):
    """Download one year of BTS on-time data and keep only an aggregate (carrier x route x month) in Parquet."""
    print("US BTS (large) ...")
    out = PROC / f"bts_routes_{year}.parquet"
    if out.exists():
        print(f"  {out.relative_to(ROOT)} already built")
        return
    parts = []
    for m in range(1, 13):
        z = get(BTS_URL.format(y=year, m=m), RAW / "bts" / f"ontime_{year}_{m:02d}.zip", pause=5)
        part = PROC / f"_bts_{year}_{m:02d}.parquet"
        if not part.exists():
            with zipfile.ZipFile(z) as zf:
                name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
                csv = RAW / "bts" / name
                if not csv.exists():
                    zf.extract(name, RAW / "bts")
            # one row per carrier, route and month; delay bands on arrival delay in minutes
            duckdb.sql(f"""
                copy (
                  select Year as year, Month as month, Reporting_Airline as carrier, Origin as origin, Dest as dest,
                         any_value(Distance) * 1.609344 as distance_km,
                         count(*) as flights,
                         sum(Cancelled) as cancelled,
                         sum(Diverted) as diverted,
                         sum(case when ArrDelayMinutes > 15 then 1 else 0 end) as arr_delay_15,
                         sum(case when ArrDelayMinutes >= 180 then 1 else 0 end) as arr_delay_180,
                         sum(case when ArrDelayMinutes >= 240 then 1 else 0 end) as arr_delay_240,
                         sum(case when ArrDelayMinutes >= 360 then 1 else 0 end) as arr_delay_360,
                         sum(case when ArrDelayMinutes >= 180 then CarrierDelay else 0 end) as carrier_delay_min_on_180,
                         sum(case when ArrDelayMinutes >= 180 then ArrDelayMinutes else 0 end) as arr_delay_min_on_180
                  from read_csv_auto('{csv.as_posix()}', all_varchar=false, ignore_errors=true)
                  group by all
                ) to '{part.as_posix()}' (format parquet)""")
            csv.unlink()  # keep disk use low: the zip stays in data/raw, the CSV is rebuilt if needed
            print(f"  aggregated month {m:02d}")
        parts.append(part)
    duckdb.sql(f"copy (select * from read_parquet({[p.as_posix() for p in parts]})) to '{out.as_posix()}' (format parquet)")
    for p in parts:
        p.unlink()
    print(f"  wrote {out.relative_to(ROOT)}")


def ourairports():
    print("OurAirports ...")
    get(OURAIRPORTS, RAW / "ourairports" / "airports.csv")
    get(OURAIRPORTS.replace("airports.csv", "countries.csv"), RAW / "ourairports" / "countries.csv")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-bts", action="store_true", help="skip the large US BTS download")
    a = ap.parse_args()
    PROC.mkdir(parents=True, exist_ok=True)
    ourairports()
    eurostat()
    caa()
    ecb_fx()
    if not a.skip_bts:
        bts()


if __name__ == "__main__":
    main()
