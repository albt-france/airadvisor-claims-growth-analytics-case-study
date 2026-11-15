"""Monthly search interest for "flight delay compensation" in the local language of each market (Google Trends).

PUBLIC DATA. Uses pytrends (unofficial client of the public Trends endpoints), one request per country,
10 seconds apart. Google rescales every request to 0-100, so values show the SEASONAL SHAPE inside a country,
not the size of demand between countries. Output: data/public/trends_monthly.csv
If Google refuses the requests (HTTP 429), the script stops and the report states that Trends was not used.
Usage:  python src/collect_trends.py
"""
import sys
import time
from pathlib import Path

import pandas as pd
from pytrends.request import TrendReq

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "public" / "trends_monthly.csv"
TERMS = {  # country: local search term for "flight delay compensation"
    "GB": "flight delay compensation",
    "DE": "flug verspätung entschädigung",
    "FR": "indemnisation retard vol",
    "ES": "indemnización retraso vuelo",
    "IT": "rimborso volo in ritardo",
    "PL": "odszkodowanie za opóźniony lot",
    "NL": "vertraagde vlucht compensatie",
    "PT": "indemnização voo atrasado",
}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    py = TrendReq(hl="en-US", tz=0, retries=2, backoff_factor=5)
    rows = []
    for geo, term in TERMS.items():
        try:
            py.build_payload([term], timeframe="2021-01-01 2026-10-31", geo=geo)
            df = py.interest_over_time()
        except Exception as e:  # noqa: BLE001 - report and stop politely
            print(f"{geo}: request refused ({type(e).__name__}); stopping")
            break
        if not df.empty:
            s = df[term].resample("MS").mean()
            rows += [{"country": geo, "term": term, "month": m.strftime("%Y-%m"), "interest": round(v, 1)} for m, v in s.items()]
            print(f"{geo}: {len(s)} months")
        time.sleep(10)
    if rows:
        pd.DataFrame(rows).to_csv(OUT, index=False)
        print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
