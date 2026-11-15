"""Shared paths, colours, constants and small helpers (no pandas: DuckDB + Polars + NumPy only)."""
import sys
from pathlib import Path

import duckdb
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw"
PUB = DATA / "public"
PROC = DATA / "processed"
SIM = DATA / "simulated"
DOCS = ROOT / "docs"
SQL = ROOT / "sql"

# light grey-beige theme shared with the earlier case studies
INK, INK2, MUTED = "#0B0B0B", "#52514E", "#898781"
BG, CARD, BORDER = "#F4F4F2", "#FCFCFB", "#E1E0D9"
BLUE, BLUE_LIGHT, BLUE_DARK = "#2A78D6", "#86B6EF", "#104281"
GREY, GREY_LIGHT = "#A8A69E", "#D6D4CC"
RED, RED_LIGHT = "#D03B3B", "#F4C7C6"
ORANGE, AQUA, YELLOW = "#EB6834", "#1BAF7A", "#EDA100"

DISCLAIMER = "Independent case study based on public data · not affiliated with or endorsed by AirAdvisor"


def ai_note() -> str:
    """The AI-use statement lives in one place, the README's last section; the PDF quotes it from there."""
    text = (ROOT / "README.md").read_text(encoding="utf-8").split("## Methods: AI note", 1)[1]
    return " ".join(text.strip().split("\n\n")[0].split())


SIM_START, SIM_END = "2025-05-01", "2026-10-31"

# EU27 + EEA/EFTA states that apply Regulation (EC) 261/2004 (Eurostat codes, Greece = EL)
EU261_STATES = ["AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "ES", "FI", "FR", "HR", "HU", "IE", "IT",
                "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SI", "SK", "IS", "NO", "CH"]
COUNTRY_NAME = {"AT": "Austria", "BE": "Belgium", "BG": "Bulgaria", "CY": "Cyprus", "CZ": "Czechia", "DE": "Germany",
                "DK": "Denmark", "EE": "Estonia", "EL": "Greece", "ES": "Spain", "FI": "Finland", "FR": "France",
                "HR": "Croatia", "HU": "Hungary", "IE": "Ireland", "IT": "Italy", "LT": "Lithuania", "LU": "Luxembourg",
                "LV": "Latvia", "MT": "Malta", "NL": "Netherlands", "PL": "Poland", "PT": "Portugal", "RO": "Romania",
                "SE": "Sweden", "SI": "Slovenia", "SK": "Slovakia", "IS": "Iceland", "NO": "Norway", "CH": "Switzerland",
                "UK": "United Kingdom"}


def utf8():
    sys.stdout.reconfigure(encoding="utf-8")


def q(sql: str, con=None) -> pl.DataFrame:
    """Run a DuckDB query and return a Polars frame."""
    return (con or duckdb).sql(sql).pl()


def sim_con():
    """In-memory DuckDB with one view per simulated table (data/simulated/*.parquet) and public table (data/public/*.csv)."""
    con = duckdb.connect()
    for p in sorted(SIM.glob("*.parquet")):
        con.sql(f"create or replace view {p.stem} as select * from read_parquet('{p.as_posix()}')")
    for p in sorted(PUB.glob("*.csv")):
        con.sql(f"create or replace view pub_{p.stem} as select * from read_csv_auto('{p.as_posix()}', header=true)")
    return con


def run_sql_file(name: str, con) -> pl.DataFrame:
    """Run the last statement of sql/<name> (files may hold comments and CTEs)."""
    return con.sql((SQL / name).read_text(encoding="utf-8")).pl()


def fmt_int(x) -> str:
    return f"{x:,.0f}"


def fmt_pct(x, digits=0) -> str:
    return f"{100 * x:.{digits}f}%"


def fmt_eur(x, digits=1) -> str:
    if abs(x) >= 1e9:
        return f"€{x / 1e9:.{digits}f}bn"
    if abs(x) >= 1e6:
        return f"€{x / 1e6:.{digits}f}M"
    if abs(x) >= 1e3:
        return f"€{x / 1e3:.0f}K"
    return f"€{x:,.0f}"
