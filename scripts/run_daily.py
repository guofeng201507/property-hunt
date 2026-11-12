from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from property_hunt import comps, db, geo, ingest  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


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
    parser = argparse.ArgumentParser(description="Daily property-hunt refresh")
    parser.add_argument("--with-geo", action="store_true", help="Also recompute heavy geo/MRT enrichment")
    parser.add_argument("--force-rentals", action="store_true", help="Fetch rentals even before the 16th")
    parser.add_argument("--rental-quarters", type=int, default=8)
    args = parser.parse_args()

    today = date.today()
    last_dnload_date = (today - timedelta(days=1)).strftime("%d/%m/%Y")
    conn = db.connect()
    try:
        db.init_db(conn)
        counts: dict[str, int] = {}

        logger.info("Refreshing transactions")
        tx_counts = ingest.ingest_live(conn, dataset="transactions")
        counts["transactions"] = sum(tx_counts.values())

        logger.info("Refreshing planning decisions since %s", last_dnload_date)
        planning_counts = ingest.ingest_live(
            conn,
            dataset="planning",
            last_dnload_date=last_dnload_date,
            year=None,
        )
        counts["planning"] = sum(planning_counts.values())

        current_month = today.strftime("%Y-%m")
        last_rental_month = db.get_meta(conn, "last_rental_refresh_month")
        should_refresh_rentals = args.force_rentals or (
            today.day >= 16 and last_rental_month != current_month
        )
        if should_refresh_rentals:
            periods = previous_quarters(args.rental_quarters)
            logger.info("Refreshing rentals for %s", ",".join(periods))
            rental_counts = ingest.ingest_live(conn, dataset="rentals", ref_periods=periods)
            counts["rentals"] = sum(rental_counts.values())
            db.set_meta(conn, "last_rental_refresh_month", current_month)
        else:
            logger.info("Skipping rentals (last_rental_month=%s, day=%s)", last_rental_month, today.day)

        street_rows = comps.refresh_street_stats(conn)
        geo_rows = geo.enrich_street_stats(conn) if args.with_geo else 0
        db.set_meta(conn, "last_daily_refresh_at", db.now_iso())
        logger.info("Done: counts=%s street_stats=%s geo_streets=%s", counts, street_rows, geo_rows)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
