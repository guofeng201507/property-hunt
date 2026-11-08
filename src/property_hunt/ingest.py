from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from . import config, db, normalize, ura

logger = logging.getLogger(__name__)

TRANSACTION_COLUMNS = [
    "raw_hash", "project", "street", "street_key", "property_type", "district",
    "market_segment", "tenure_raw", "tenure_type", "lease_start_year", "sale_type",
    "contract_date", "contract_month", "price", "nett_price", "area_sqm", "area_sqft",
    "area_basis", "area_band", "psf", "floor_range", "no_of_units", "x_svy21",
    "y_svy21", "ingested_at",
]
RENTAL_COLUMNS = [
    "raw_hash", "project", "street", "street_key", "property_type", "district",
    "lease_date", "lease_month", "rent_monthly", "area_sqft_low", "area_sqft_high",
    "area_sqft_mid", "area_sqm_low", "area_sqm_high", "area_band", "bedrooms",
    "x_svy21", "y_svy21", "ingested_at",
]
PLANNING_COLUMNS = [
    "submission_no", "decision_no", "dr_id", "address", "street", "street_key",
    "submission_desc", "appl_type", "decision_type", "decision_date", "mkts_lotno",
    "delete_ind", "ingested_at",
]


def _float(value: Any) -> float | None:
    try:
        if value in (None, "", "-", "na", "N/A"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    number = _float(value)
    return int(number) if number is not None else None


def _as_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _write_parquet(records: list[dict[str, Any]], prefix: str) -> Path | None:
    if not records:
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = config.RAW_DIR / f"{prefix}_{stamp}.parquet"
    pd.DataFrame(records).to_parquet(path, index=False)
    return path


def flatten_transactions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    ingested_at = db.now_iso()
    records: list[dict[str, Any]] = []
    for item in payload.get("Result", []) or []:
        project = normalize.clean_text(item.get("project"))
        street = normalize.clean_text(item.get("street"))
        if not street:
            continue
        key = normalize.street_key(street)
        x = _float(item.get("x"))
        y = _float(item.get("y"))
        for tx in _as_list(item.get("transaction")):
            property_type = normalize.normalize_property_type(tx.get("propertyType"))
            contract_date = normalize.parse_mmyy(tx.get("contractDate"))
            if contract_date is None:
                continue
            area_sqm = _float(tx.get("area"))
            area_sqft = normalize.sqm_to_sqft(area_sqm)
            price = _int(tx.get("price"))
            nett_price = _int(tx.get("nettPrice"))
            sale_type = normalize.normalize_sale_type(tx.get("typeOfSale"))
            type_of_area = normalize.clean_text(tx.get("typeOfArea")).upper()
            basis = "LAND" if type_of_area == "LAND" else "STRATA" if type_of_area == "STRATA" else normalize.area_basis(property_type)
            tenure_raw = normalize.clean_text(tx.get("tenure"))
            tenure_type, lease_start = normalize.parse_tenure(tenure_raw)
            psf = price / area_sqft if price and area_sqft else None
            no_of_units = _int(tx.get("noOfUnits"))
            raw_hash = normalize.make_hash(
                "tx", project, key, property_type, contract_date.isoformat(),
                price, area_sqm, sale_type, no_of_units,
            )
            records.append({
                "raw_hash": raw_hash,
                "project": project,
                "street": street,
                "street_key": key,
                "property_type": property_type,
                "district": normalize.clean_text(tx.get("district")) or None,
                "market_segment": normalize.clean_text(item.get("marketSegment")) or None,
                "tenure_raw": tenure_raw,
                "tenure_type": tenure_type,
                "lease_start_year": lease_start,
                "sale_type": sale_type,
                "contract_date": contract_date.isoformat(),
                "contract_month": contract_date.strftime("%Y-%m"),
                "price": price,
                "nett_price": nett_price,
                "area_sqm": area_sqm,
                "area_sqft": area_sqft,
                "area_basis": basis,
                "area_band": normalize.area_band(property_type, area_sqft),
                "psf": psf,
                "floor_range": normalize.clean_text(tx.get("floorRange")) or None,
                "no_of_units": no_of_units,
                "x_svy21": x,
                "y_svy21": y,
                "ingested_at": ingested_at,
            })
    return records


def flatten_rentals(payload: dict[str, Any]) -> list[dict[str, Any]]:
    ingested_at = db.now_iso()
    records: list[dict[str, Any]] = []
    for item in payload.get("Result", []) or []:
        project = normalize.clean_text(item.get("project"))
        street = normalize.clean_text(item.get("street"))
        if not street:
            continue
        key = normalize.street_key(street)
        x = _float(item.get("x"))
        y = _float(item.get("y"))
        for rental in _as_list(item.get("rental")):
            property_type = normalize.normalize_property_type(rental.get("propertyType"))
            lease_date = normalize.parse_mmyy(rental.get("leaseDate"))
            if lease_date is None:
                continue
            area_sqft_low, area_sqft_high, area_sqft_mid = normalize.parse_area_range(rental.get("areaSqft"))
            area_sqm_low, area_sqm_high, _ = normalize.parse_area_range(rental.get("areaSqm"))
            rent = _float(rental.get("rent"))
            if rent is None or area_sqft_mid is None:
                continue
            bedrooms = _int(rental.get("noOfBedRoom"))
            raw_hash = normalize.make_hash(
                "rent", project, key, property_type, lease_date.isoformat(),
                rent, area_sqft_low, area_sqft_high,
            )
            records.append({
                "raw_hash": raw_hash,
                "project": project,
                "street": street,
                "street_key": key,
                "property_type": property_type,
                "district": normalize.clean_text(rental.get("district")) or None,
                "lease_date": lease_date.isoformat(),
                "lease_month": lease_date.strftime("%Y-%m"),
                "rent_monthly": rent,
                "area_sqft_low": area_sqft_low,
                "area_sqft_high": area_sqft_high,
                "area_sqft_mid": area_sqft_mid,
                "area_sqm_low": area_sqm_low,
                "area_sqm_high": area_sqm_high,
                "area_band": normalize.area_band(property_type, area_sqft_mid),
                "bedrooms": bedrooms,
                "x_svy21": x,
                "y_svy21": y,
                "ingested_at": ingested_at,
            })
    return records


def flatten_planning(payload: dict[str, Any]) -> list[dict[str, Any]]:
    ingested_at = db.now_iso()
    records: list[dict[str, Any]] = []
    for item in payload.get("Result", []) or []:
        address = normalize.clean_text(item.get("address"))
        if not address:
            continue
        decision_date = normalize.parse_date_ddmmyyyy(item.get("decision_date"))
        street = normalize.extract_street(address)
        submission_no = normalize.clean_text(item.get("submission_no")) or normalize.clean_text(item.get("dr_id"))
        if not submission_no:
            continue
        records.append({
            "submission_no": submission_no,
            "decision_no": normalize.clean_text(item.get("decision_no")),
            "dr_id": normalize.clean_text(item.get("dr_id")) or None,
            "address": address,
            "street": street,
            "street_key": normalize.street_key(street),
            "submission_desc": normalize.clean_text(item.get("submission_desc")) or None,
            "appl_type": normalize.clean_text(item.get("appl_type")) or None,
            "decision_type": normalize.clean_text(item.get("decision_type")) or None,
            "decision_date": decision_date.isoformat() if decision_date else None,
            "mkts_lotno": normalize.clean_text(item.get("mkts_lotno")) or None,
            "delete_ind": normalize.clean_text(item.get("delete_ind")) or "No",
            "ingested_at": ingested_at,
        })
    return records


def _insert_transactions(conn: sqlite3.Connection, records: list[dict[str, Any]]) -> int:
    if not records:
        return 0
    sql = (
        f"INSERT OR IGNORE INTO ura_transactions ({', '.join(TRANSACTION_COLUMNS)}) "
        f"VALUES ({', '.join('?' for _ in TRANSACTION_COLUMNS)})"
    )
    conn.executemany(sql, [[row.get(column) for column in TRANSACTION_COLUMNS] for row in records])
    conn.commit()
    return len(records)


def _insert_rentals(conn: sqlite3.Connection, records: list[dict[str, Any]]) -> int:
    if not records:
        return 0
    sql = (
        f"INSERT OR IGNORE INTO ura_rentals ({', '.join(RENTAL_COLUMNS)}) "
        f"VALUES ({', '.join('?' for _ in RENTAL_COLUMNS)})"
    )
    conn.executemany(sql, [[row.get(column) for column in RENTAL_COLUMNS] for row in records])
    conn.commit()
    return len(records)


def _upsert_planning(conn: sqlite3.Connection, records: list[dict[str, Any]]) -> int:
    if not records:
        return 0
    for row in records:
        if normalize.clean_text(row.get("delete_ind")).lower() == "yes":
            conn.execute(
                "DELETE FROM ura_planning WHERE submission_no = ? AND decision_no = ?",
                (row["submission_no"], row["decision_no"]),
            )
            continue
        placeholders = ", ".join("?" for _ in PLANNING_COLUMNS)
        updates = ", ".join(
            f"{column} = excluded.{column}"
            for column in PLANNING_COLUMNS
            if column not in {"submission_no", "decision_no"}
        )
        conn.execute(
            f"INSERT INTO ura_planning ({', '.join(PLANNING_COLUMNS)}) VALUES ({placeholders}) "
            f"ON CONFLICT(submission_no, decision_no) DO UPDATE SET {updates}",
            [row.get(column) for column in PLANNING_COLUMNS],
        )
    conn.commit()
    return len(records)


def ingest_payload(conn: sqlite3.Connection, dataset: str, payload: dict[str, Any]) -> int:
    if dataset == "transactions":
        records = flatten_transactions(payload)
        _write_parquet(records, "ura_transactions")
        count = _insert_transactions(conn, records)
    elif dataset == "rentals":
        records = flatten_rentals(payload)
        _write_parquet(records, "ura_rentals")
        count = _insert_rentals(conn, records)
    elif dataset == "planning":
        records = flatten_planning(payload)
        _write_parquet(records, "ura_planning")
        count = _upsert_planning(conn, records)
    else:
        raise ValueError(f"Unknown dataset: {dataset}")
    db.set_meta(conn, "last_ingest_at", db.now_iso())
    return count


def ingest_demo(conn: sqlite3.Connection) -> dict[str, int]:
    started = db.now_iso()
    fixtures = {
        "transactions": config.FIXTURE_DIR / "ura_transactions_demo.json",
        "rentals": config.FIXTURE_DIR / "ura_rentals_demo.json",
        "planning": config.FIXTURE_DIR / "ura_planning_demo.json",
    }
    counts: dict[str, int] = {}
    try:
        for dataset, path in fixtures.items():
            payload = json.loads(path.read_text(encoding="utf-8"))
            counts[dataset] = ingest_payload(conn, dataset, payload)
        db.set_meta(conn, "data_mode", "demo")
        db.record_sync(conn, "demo_ingest", started, "success", sum(counts.values()))
        return counts
    except Exception as exc:
        db.record_sync(conn, "demo_ingest", started, "error", sum(counts.values()), str(exc))
        raise


def ingest_live(
    conn: sqlite3.Connection,
    *,
    dataset: str = "all",
    ref_period: str | None = None,
    ref_periods: list[str] | None = None,
    year: int | None = None,
    last_dnload_date: str | None = None,
) -> dict[str, int]:
    if not config.URA_ACCESS_KEY:
        raise ura.UraError("URA_ACCESS_KEY is missing. Add it to .env or run demo mode.")
    started = db.now_iso()
    token = ura.get_token()
    counts: dict[str, int] = {}
    try:
        if dataset in {"all", "transactions"}:
            for batch in range(1, 5):
                payload = ura.fetch_transactions(batch, token)
                counts[f"transactions_batch_{batch}"] = ingest_payload(conn, "transactions", payload)
        if dataset in {"all", "rentals"}:
            periods = ref_periods or ([ref_period] if ref_period else [])
            if not periods:
                raise ValueError("A rental ref_period or ref_periods list is required")
            total = 0
            for period in periods:
                payload = ura.fetch_rentals(period, token)
                total += ingest_payload(conn, "rentals", payload)
            counts["rentals"] = total
        if dataset in {"all", "planning"}:
            payload = ura.fetch_planning(token, year=year, last_dnload_date=last_dnload_date)
            counts["planning"] = ingest_payload(conn, "planning", payload)
        db.set_meta(conn, "data_mode", "live")
        db.record_sync(conn, f"live_ingest:{dataset}", started, "success", sum(counts.values()))
        return counts
    except Exception as exc:
        db.record_sync(conn, f"live_ingest:{dataset}", started, "error", sum(counts.values()), str(exc))
        raise
