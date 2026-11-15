"""Run every query in sql/ against the simulated tables (DuckDB) and print the first rows of each.
Usage:  python src/run_sql.py [file-prefix]      e.g.  python src/run_sql.py 03
"""
import sys

import polars as pl

from common import SQL, run_sql_file, sim_con, utf8


def main():
    utf8()
    pl.Config.set_tbl_cols(12); pl.Config.set_tbl_width_chars(160); pl.Config.set_tbl_formatting("ASCII_MARKDOWN")
    con = sim_con()
    prefix = sys.argv[1] if len(sys.argv) > 1 else ""
    for f in sorted(SQL.glob(f"{prefix}*.sql")):
        df = run_sql_file(f.name, con)
        print(f"\n-- {f.name}: {len(df)} rows")
        print(df.head(6))


if __name__ == "__main__":
    main()
