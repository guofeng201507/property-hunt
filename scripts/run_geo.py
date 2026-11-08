from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from property_hunt import comps, config, db, geo  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Download MP2025/cadastral layers and enrich street stats")
    parser.add_argument("--force", action="store_true", help="Re-download existing layers")
    args = parser.parse_args()

    conn = db.connect()
    try:
        db.init_db(conn)
        paths = geo.download_all(conn, force=args.force)
        for key, path in paths.items():
            print(f"{key}: {path}")
        rows = geo.enrich_street_stats(conn)
        print(f"geo_enriched_streets={rows}")
        for item in geo.layer_status(conn):
            print(f"{item['key']}: {item['size_mb']} MB, exists={item['exists']}")
        print(f"db={config.DB_PATH}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
