from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

DB_PATH = Path(os.getenv("PROPERTY_HUNT_DB", ROOT / "db" / "property.db"))
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
FIXTURE_DIR = DATA_DIR / "fixtures"
SCHEMA_PATH = ROOT / "sql" / "schema.sql"

URA_ACCESS_KEY = os.getenv("URA_ACCESS_KEY", "").strip()
URA_BASE_URL = "https://eservice.ura.gov.sg/uraDataService"
URA_TIMEOUT = 60

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Personal decision parameters. Kept simple for P0.
VACANCY_RATE = 0.05
OPEX_RATE = 0.10
ACQUISITION_COST_RATE = 0.04
DEFAULT_TARGET_YIELD_PCT = 3.0
DEFAULT_VALUE_GAP_THRESHOLD = 0.10

for directory in (DB_PATH.parent, RAW_DIR, FIXTURE_DIR):
    directory.mkdir(parents=True, exist_ok=True)
