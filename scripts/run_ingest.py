from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from property_hunt import comps, config, db, geo, ingest  # noqa: E402


def previous_quarter() -> str:
    return previous_quarters(1)[0]


def previous_quarters(count: int) -> list[str]:
    quarter = (date.today().month - 1) // 3 + 1
    year = date.today().year
    periods: list[str] = []
    for _ in range(max(1, count)):
        quarter -= 1
        if quarter == 0:
            quarter = 4
            year -= 1
        periods.append(f"{year % 100:02d}q{quarter}")
    return periods


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest URA data into SQLite")
    parser.add_argument("--mode", choices=["demo", "live"], default="demo")
    parser.add_argument(
        "--dataset",
        choices=["all", "transactions", "rentals", "planning"],
        default="all",
    )
    parser.add_argument("--ref-period", help="Rental reference quarter, e.g. 26q3")
    parser.add_argument(
        "--rental-quarters",
        type=int,
        default=8,
        help="How many previous quarters to fetch for rentals (default 8 = 24 months)",
    )
    parser.add_argument("--year", type=int, help="Planning decisions for a year")
    parser.add_argument("--last-dnload-date", help="Planning incremental date dd/mm/yyyy")
    args = parser.parse_args()

    conn = db.connect()
    try:
        db.init_db(conn)
        if args.mode == "demo":
            counts = ingest.ingest_demo(conn)
        else:
            ref_periods = [args.ref_period] if args.ref_period else previous_quarters(args.rental_quarters)
            year = args.year
            if args.dataset in {"all", "planning"} and not args.last_dnload_date and year is None:
                year = date.today().year
            counts = ingest.ingest_live(
                conn,
                dataset=args.dataset,
                ref_periods=ref_periods,
                year=year,
                last_dnload_date=args.last_dnload_date,
            )
        street_rows = comps.refresh_street_stats(conn)
        geo_rows = geo.enrich_street_stats(conn) if geo.has_layers() else 0
        print(f"counts={counts}")
        print(f"street_stats={street_rows}")
        print(f"geo_enriched_streets={geo_rows}")
        print(f"db={config.DB_PATH}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
