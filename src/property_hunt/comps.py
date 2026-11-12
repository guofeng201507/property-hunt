from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any

import pandas as pd

from . import config, db, geo, normalize

STREET_STATS_COLUMNS = [
    "street_key", "street", "district", "property_type", "tenure_type", "area_band",
    "lease_start_year", "remaining_lease_years",
    "sale_count_36m", "sale_count_12m", "sale_median_price", "sale_median_psf",
    "sale_p25_psf", "sale_p75_psf", "sale_last_date", "rent_count_24m",
    "rent_count_12m", "rent_median", "rent_median_psf", "rent_last_date",
    "gross_yield_pct", "liquidity_score", "confidence",
    "lu_desc", "gpr", "height_control", "lha_class", "lha_name", "lha_type",
    "conservation_area", "cadastral_lot", "nearest_mrt_name", "nearest_mrt_exit",
    "nearest_mrt_distance_m", "geo_updated_at", "updated_at",
]
CATALYST_KEYWORDS = (
    "SUBDIVISION", "AMALGAMATION", "RECONSTRUCTION", "ERECTION",
    "DETACHED", "SEMI-DETACHED", "SEMI DETACHED", "TERRACE",
    "ADDITIONS", "ALTERATIONS",
)


def _rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def _cutoff(months: int) -> str:
    return (pd.Timestamp.today().normalize() - pd.DateOffset(months=months)).date().isoformat()


def _quantile(values: list[float], q: float) -> float | None:
    clean = [float(value) for value in values if value is not None]
    if not clean:
        return None
    return float(pd.Series(clean).quantile(q))


def _median(values: list[float]) -> float | None:
    clean = [float(value) for value in values if value is not None]
    if not clean:
        return None
    return float(pd.Series(clean).median())


def _confidence(scope: str, count: int) -> str:
    if scope == "street" and count >= 8:
        return "high"
    if count >= 5:
        return "medium"
    return "low"


def refresh_street_stats(conn: sqlite3.Connection) -> int:
    today = pd.Timestamp.today().normalize()
    tx = pd.read_sql_query("SELECT * FROM ura_transactions", conn)
    rt = pd.read_sql_query("SELECT * FROM ura_rentals", conn)
    if tx.empty:
        conn.execute("DELETE FROM street_stats")
        conn.commit()
        return 0

    tx["contract_dt"] = pd.to_datetime(tx["contract_date"], errors="coerce")
    rt["lease_dt"] = pd.to_datetime(rt["lease_date"], errors="coerce")
    tx = tx[tx["psf"].notna() & tx["contract_dt"].notna()].copy()
    if tx.empty:
        conn.execute("DELETE FROM street_stats")
        conn.commit()
        return 0

    sale_keys = ["street_key", "property_type", "tenure_type", "area_band"]
    tx36 = tx[tx["contract_dt"] >= today - pd.DateOffset(months=36)].copy()
    tx12 = tx[tx["contract_dt"] >= today - pd.DateOffset(months=12)].copy()

    sale = tx36.groupby(sale_keys, dropna=False).agg(
        street=("street", "first"),
        district=("district", "first"),
        lease_start_year=("lease_start_year", "median"),
        sale_count_36m=("id", "count"),
        sale_median_price=("price", "median"),
        sale_median_psf=("psf", "median"),
        sale_p25_psf=("psf", lambda values: values.quantile(0.25)),
        sale_p75_psf=("psf", lambda values: values.quantile(0.75)),
        sale_last_date=("contract_date", "max"),
    ).reset_index()
    sale12 = (
        tx12.groupby(sale_keys, dropna=False)
        .size()
        .reset_index(name="sale_count_12m")
    )
    stats = sale.merge(sale12, on=sale_keys, how="left")

    rent_keys = ["street_key", "property_type"]
    if not rt.empty:
        rt = rt[rt["rent_monthly"].notna() & rt["area_sqft_mid"].notna() & rt["lease_dt"].notna()].copy()
        rt["rent_psf"] = rt["rent_monthly"] / rt["area_sqft_mid"]
        rt24 = rt[rt["lease_dt"] >= today - pd.DateOffset(months=24)].copy()
        rt12 = rt[rt["lease_dt"] >= today - pd.DateOffset(months=12)].copy()
        rent = rt24.groupby(rent_keys, dropna=False).agg(
            rent_count_24m=("id", "count"),
            rent_median=("rent_monthly", "median"),
            rent_median_psf=("rent_psf", "median"),
            rent_last_date=("lease_date", "max"),
        ).reset_index()
        rent12 = rt12.groupby(rent_keys, dropna=False).size().reset_index(name="rent_count_12m")
        stats = stats.merge(rent, on=rent_keys, how="left").merge(rent12, on=rent_keys, how="left")
    else:
        stats["rent_count_24m"] = 0
        stats["rent_count_12m"] = 0
        stats["rent_median"] = None
        stats["rent_median_psf"] = None
        stats["rent_last_date"] = None

    for column in ("sale_count_12m", "rent_count_24m", "rent_count_12m"):
        stats[column] = stats[column].fillna(0).astype(int)

    stats["gross_yield_pct"] = stats.apply(
        lambda row: (
            row["rent_median"] * 12 / row["sale_median_price"] * 100
            if pd.notna(row["rent_median"]) and pd.notna(row["sale_median_price"]) and row["sale_median_price"]
            else None
        ),
        axis=1,
    )
    stats["lease_start_year"] = stats["lease_start_year"].apply(
        lambda value: int(value) if pd.notna(value) else None
    )
    stats["remaining_lease_years"] = [
        normalize.lease_remaining_years(tenure, start_year)
        for tenure, start_year in zip(stats["tenure_type"], stats["lease_start_year"])
    ]
    stats["liquidity_score"] = (
        0.5 * (stats["sale_count_12m"].clip(upper=5) / 5)
        + 0.5 * (stats["rent_count_12m"].clip(upper=5) / 5)
    )
    stats["confidence"] = [
        "high" if sale_count >= 8 and rent_count >= 6
        else "medium" if sale_count >= 5 or rent_count >= 3
        else "low"
        for sale_count, rent_count in zip(stats["sale_count_36m"], stats["rent_count_24m"])
    ]

    existing_geo = pd.read_sql_query(
        "SELECT street_key, property_type, tenure_type, area_band, "
        "lu_desc, gpr, height_control, lha_class, lha_name, lha_type, "
        "conservation_area, cadastral_lot, nearest_mrt_name, nearest_mrt_exit, "
        "nearest_mrt_distance_m, geo_updated_at FROM street_stats",
        conn,
    )
    geo_keys = ["street_key", "property_type", "tenure_type", "area_band"]
    stats = stats.merge(existing_geo, on=geo_keys, how="left")
    stats["updated_at"] = db.now_iso()
    stats = stats[STREET_STATS_COLUMNS].astype(object).where(pd.notnull(stats[STREET_STATS_COLUMNS]), None)

    conn.execute("DELETE FROM street_stats")
    placeholders = ", ".join("?" for _ in STREET_STATS_COLUMNS)
    conn.executemany(
        f"INSERT INTO street_stats ({', '.join(STREET_STATS_COLUMNS)}) VALUES ({placeholders})",
        [list(row) for row in stats.itertuples(index=False, name=None)],
    )
    conn.commit()
    return len(stats)


def list_street_stats(
    conn: sqlite3.Connection,
    *,
    property_type: str | None = None,
    district: str | None = None,
    min_sale: int = 0,
    min_rent: int = 0,
    min_lease_remaining: int = 0,
    mrt_station: str | None = None,
    max_mrt_distance_m: float = 0,
    sort: str = "gross_yield_pct",
    limit: int = 100,
) -> list[dict[str, Any]]:
    where = ["sale_count_36m >= ?", "rent_count_24m >= ?"]
    params: list[Any] = [min_sale, min_rent]
    if min_lease_remaining > 0:
        where.append("(remaining_lease_years IS NULL OR remaining_lease_years >= ?)")
        params.append(min_lease_remaining)
    if mrt_station:
        where.append("nearest_mrt_name LIKE ?")
        params.append(f"%{normalize.clean_text(mrt_station).upper()}%")
    if max_mrt_distance_m > 0:
        where.append("nearest_mrt_distance_m IS NOT NULL AND nearest_mrt_distance_m <= ?")
        params.append(max_mrt_distance_m)
    if property_type:
        where.append("property_type = ?")
        params.append(normalize.normalize_property_type(property_type))
    if district:
        where.append("district = ?")
        params.append(normalize.clean_text(district).zfill(2))
    sort_map = {
        "gross_yield_pct": "gross_yield_pct DESC",
        "sale_median_psf": "sale_median_psf DESC",
        "sale_count_36m": "sale_count_36m DESC",
        "liquidity_score": "liquidity_score DESC",
    }
    order = sort_map.get(sort, "gross_yield_pct DESC")
    sql = (
        "SELECT * FROM street_stats WHERE "
        + " AND ".join(where)
        + f" ORDER BY {order} NULLS LAST LIMIT ?"
    )
    params.append(limit)
    return _rows_to_dicts(conn.execute(sql, params).fetchall())


def search_street(
    conn: sqlite3.Connection,
    query: str,
    *,
    property_type: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    where = ["street LIKE ?"]
    params: list[Any] = [f"%{normalize.clean_text(query).upper()}%"]
    if property_type:
        where.append("property_type = ?")
        params.append(normalize.normalize_property_type(property_type))
    sql = (
        "SELECT * FROM street_stats WHERE "
        + " AND ".join(where)
        + " ORDER BY sale_count_36m DESC, gross_yield_pct DESC LIMIT ?"
    )
    params.append(limit)
    return _rows_to_dicts(conn.execute(sql, params).fetchall())


def _sale_rows(conn: sqlite3.Connection, where: str, params: list[Any], limit: int = 50) -> list[sqlite3.Row]:
    sql = (
        "SELECT * FROM ura_transactions WHERE "
        + where
        + " ORDER BY contract_date DESC LIMIT ?"
    )
    return conn.execute(sql, [*params, limit]).fetchall()


def _sale_scope_rows(
    conn: sqlite3.Connection,
    *,
    scope: str,
    street: str,
    district: str | None,
    property_type: str,
    cutoff: str,
    tenure_type: str | None,
    band: str | None,
) -> list[sqlite3.Row]:
    clauses = ["contract_date >= ?", "psf IS NOT NULL"]
    params: list[Any] = [cutoff]
    if scope == "street":
        clauses.append("street_key = ?")
        params.append(street)
    elif scope == "district":
        clauses.append("district = ?")
        params.append(district)
    clauses.append("property_type = ?")
    params.append(property_type)
    if tenure_type:
        clauses.append("tenure_type = ?")
        params.append(tenure_type)
    if band:
        clauses.append("area_band = ?")
        params.append(band)
    return _sale_rows(conn, " AND ".join(clauses), params)


def _sale_stats(rows: list[sqlite3.Row]) -> dict[str, Any]:
    psfs = [row["psf"] for row in rows if row["psf"] is not None]
    prices = [row["price"] for row in rows if row["price"] is not None]
    latest = max((row["contract_date"] for row in rows if row["contract_date"]), default=None)
    return {
        "count": len(rows),
        "median_psf": _median(psfs),
        "p25_psf": _quantile(psfs, 0.25),
        "p75_psf": _quantile(psfs, 0.75),
        "median_price": _median(prices),
        "latest_contract_date": latest,
    }


def get_sale_comps(
    conn: sqlite3.Connection,
    street: str,
    property_type: str,
    *,
    tenure_type: str | None = None,
    land_sqft: float | None = None,
    months: int = 36,
) -> dict[str, Any]:
    key = normalize.street_key(street)
    pt = normalize.normalize_property_type(property_type)
    requested_band = normalize.area_band(pt, land_sqft) if land_sqft else None
    cutoff = _cutoff(months)
    district_row = conn.execute(
        "SELECT district FROM ura_transactions WHERE street_key = ? AND property_type = ? "
        "AND district IS NOT NULL LIMIT 1",
        (key, pt),
    ).fetchone()
    district = district_row["district"] if district_row else None

    attempts: list[tuple[str, str | None]] = []
    if key:
        attempts.append(("street", requested_band))
        if requested_band:
            attempts.append(("street", None))
    if district:
        attempts.append(("district", requested_band))
        if requested_band:
            attempts.append(("district", None))
    attempts.append(("type", requested_band))
    if requested_band:
        attempts.append(("type", None))

    rows: list[sqlite3.Row] = []
    scope = "type"
    applied_band: str | None = None
    best_rows: list[sqlite3.Row] = []
    best_scope = "type"
    best_band: str | None = None
    for attempt_scope, attempt_band in attempts:
        candidate = _sale_scope_rows(
            conn,
            scope=attempt_scope,
            street=key,
            district=district,
            property_type=pt,
            cutoff=cutoff,
            tenure_type=tenure_type,
            band=attempt_band,
        )
        if len(candidate) > len(best_rows):
            best_rows, best_scope, best_band = candidate, attempt_scope, attempt_band
        if len(candidate) >= 5:
            rows, scope, applied_band = candidate, attempt_scope, attempt_band
            break
    else:
        rows, scope, applied_band = best_rows, best_scope, best_band

    stats = _sale_stats(rows)
    return {
        "street": street.upper(),
        "property_type": pt,
        "property_type_label": normalize.property_type_label(pt),
        "tenure_type": tenure_type,
        "requested_area_band": requested_band,
        "area_band": applied_band,
        "months": months,
        "scope": scope,
        "confidence": _confidence(scope, len(rows)),
        "stats": stats,
        "comps": _rows_to_dicts(rows),
        "as_of": date.today().isoformat(),
    }


def _rent_rows(conn: sqlite3.Connection, where: str, params: list[Any], limit: int = 50) -> list[sqlite3.Row]:
    sql = (
        "SELECT * FROM ura_rentals WHERE "
        + where
        + " ORDER BY lease_date DESC LIMIT ?"
    )
    return conn.execute(sql, [*params, limit]).fetchall()


def _rent_scope_rows(
    conn: sqlite3.Connection,
    *,
    scope: str,
    street: str,
    district: str | None,
    property_type: str,
    cutoff: str,
    band: str | None,
) -> list[sqlite3.Row]:
    clauses = ["lease_date >= ?", "rent_monthly IS NOT NULL"]
    params: list[Any] = [cutoff]
    if scope == "street":
        clauses.append("street_key = ?")
        params.append(street)
    elif scope == "district":
        clauses.append("district = ?")
        params.append(district)
    clauses.append("property_type = ?")
    params.append(property_type)
    if band:
        clauses.append("area_band = ?")
        params.append(band)
    return _rent_rows(conn, " AND ".join(clauses), params)


def _rent_stats(rows: list[sqlite3.Row]) -> dict[str, Any]:
    rents = [row["rent_monthly"] for row in rows if row["rent_monthly"] is not None]
    psfs = [
        row["rent_monthly"] / row["area_sqft_mid"]
        for row in rows
        if row["rent_monthly"] and row["area_sqft_mid"]
    ]
    latest = max((row["lease_date"] for row in rows if row["lease_date"]), default=None)
    return {
        "count": len(rows),
        "median_rent": _median(rents),
        "median_rent_psf": _median(psfs),
        "p25_rent_psf": _quantile(psfs, 0.25),
        "p75_rent_psf": _quantile(psfs, 0.75),
        "latest_lease_date": latest,
    }


def get_rent_comps(
    conn: sqlite3.Connection,
    street: str,
    property_type: str,
    *,
    sqft: float | None = None,
    months: int = 24,
) -> dict[str, Any]:
    key = normalize.street_key(street)
    pt = normalize.normalize_property_type(property_type)
    requested_band = normalize.area_band(pt, sqft) if sqft else None
    cutoff = _cutoff(months)
    district_row = conn.execute(
        "SELECT district FROM ura_rentals WHERE street_key = ? AND property_type = ? "
        "AND district IS NOT NULL LIMIT 1",
        (key, pt),
    ).fetchone()
    district = district_row["district"] if district_row else None

    attempts: list[tuple[str, str | None]] = []
    if key:
        attempts.append(("street", requested_band))
        if requested_band:
            attempts.append(("street", None))
    if district:
        attempts.append(("district", requested_band))
        if requested_band:
            attempts.append(("district", None))
    attempts.append(("type", requested_band))
    if requested_band:
        attempts.append(("type", None))

    rows: list[sqlite3.Row] = []
    scope = "type"
    applied_band: str | None = None
    best_rows: list[sqlite3.Row] = []
    best_scope = "type"
    best_band: str | None = None
    for attempt_scope, attempt_band in attempts:
        candidate = _rent_scope_rows(
            conn,
            scope=attempt_scope,
            street=key,
            district=district,
            property_type=pt,
            cutoff=cutoff,
            band=attempt_band,
        )
        if len(candidate) > len(best_rows):
            best_rows, best_scope, best_band = candidate, attempt_scope, attempt_band
        if len(candidate) >= 5:
            rows, scope, applied_band = candidate, attempt_scope, attempt_band
            break
    else:
        rows, scope, applied_band = best_rows, best_scope, best_band

    stats = _rent_stats(rows)
    return {
        "street": street.upper(),
        "property_type": pt,
        "property_type_label": normalize.property_type_label(pt),
        "requested_area_band": requested_band,
        "area_band": applied_band,
        "months": months,
        "scope": scope,
        "confidence": _confidence(scope, len(rows)),
        "stats": stats,
        "comps": _rows_to_dicts(rows),
        "as_of": date.today().isoformat(),
    }


def estimate_yield(
    conn: sqlite3.Connection,
    street: str,
    property_type: str,
    price: float,
    *,
    rent: float | None = None,
    built_up_sqft: float | None = None,
) -> dict[str, Any]:
    rent_comps = get_rent_comps(conn, street, property_type, sqft=built_up_sqft)
    assumptions: list[str] = []
    monthly_rent = rent
    if monthly_rent is None:
        if built_up_sqft and rent_comps["stats"]["median_rent_psf"]:
            monthly_rent = rent_comps["stats"]["median_rent_psf"] * built_up_sqft
            assumptions.append("Rent estimated from street rent psf x built-up area")
        else:
            monthly_rent = rent_comps["stats"]["median_rent"]
            assumptions.append("Rent estimated from street median rent")
    if monthly_rent is None:
        raise ValueError("No rent provided and no rental comps available")
    annual_rent = monthly_rent * 12
    effective_rent = annual_rent * (1 - config.VACANCY_RATE)
    net_income = effective_rent * (1 - config.OPEX_RATE)
    total_cost = price * (1 + config.ACQUISITION_COST_RATE)
    return {
        "street": street.upper(),
        "property_type": normalize.normalize_property_type(property_type),
        "price": price,
        "monthly_rent": round(monthly_rent, 2),
        "annual_rent": round(annual_rent, 2),
        "gross_yield_pct": round(annual_rent / price * 100, 3),
        "net_yield_pct": round(net_income / total_cost * 100, 3),
        "assumptions": assumptions + [
            f"vacancy={config.VACANCY_RATE:.0%}",
            f"opex={config.OPEX_RATE:.0%}",
            f"acquisition_cost={config.ACQUISITION_COST_RATE:.0%}",
        ],
        "rent_comps": rent_comps,
        "as_of": date.today().isoformat(),
    }


def value_gaps(
    conn: sqlite3.Connection,
    *,
    street: str | None = None,
    property_type: str | None = None,
    months: int = 12,
    discount_threshold: float = config.DEFAULT_VALUE_GAP_THRESHOLD,
    limit: int = 100,
) -> list[dict[str, Any]]:
    cutoff = _cutoff(months)
    where = [
        "t.area_basis = 'LAND'",
        "t.psf IS NOT NULL",
        "t.contract_date >= ?",
        "s.sale_count_36m >= 3",
        "t.sale_type != 'NEW'",
    ]
    params: list[Any] = [cutoff]
    if street:
        where.append("t.street_key = ?")
        params.append(normalize.street_key(street))
    if property_type:
        where.append("t.property_type = ?")
        params.append(normalize.normalize_property_type(property_type))
    sql = (
        "SELECT t.*, s.sale_median_psf AS comp_median_psf, s.sale_count_36m, "
        "s.sale_p25_psf, s.sale_p75_psf, s.confidence, s.gross_yield_pct, "
        "s.remaining_lease_years AS comp_remaining_lease_years, "
        "s.lu_desc AS comp_zoning, s.lha_class AS comp_lha, "
        "s.conservation_area AS comp_conservation, "
        "s.nearest_mrt_name AS comp_mrt_name, s.nearest_mrt_distance_m AS comp_mrt_distance_m "
        "FROM ura_transactions t "
        "JOIN street_stats s ON t.street_key = s.street_key "
        "AND t.property_type = s.property_type "
        "AND t.tenure_type = s.tenure_type "
        "AND t.area_band = s.area_band "
        "WHERE " + " AND ".join(where) + " ORDER BY t.contract_date DESC LIMIT ?"
    )
    rows = conn.execute(sql, [*params, limit]).fetchall()
    results: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        median_psf = item.get("comp_median_psf")
        if not median_psf or not item.get("psf"):
            continue
        discount = 1 - item["psf"] / median_psf
        if discount < discount_threshold:
            continue
        remaining = normalize.lease_remaining_years(item.get("tenure_type"), item.get("lease_start_year"))
        risk_flags: list[str] = []
        if remaining is not None and remaining < 60:
            risk_flags.append(f"lease_remaining_{remaining}y")
        item["discount_pct"] = round(discount * 100, 2)
        item["lease_remaining_years"] = remaining
        item["risk_flags"] = risk_flags
        item["property_type_label"] = normalize.property_type_label(item.get("property_type"))
        results.append(item)
    results.sort(key=lambda item: item["discount_pct"], reverse=True)
    return results


def planning_signals(
    conn: sqlite3.Connection,
    *,
    street: str | None = None,
    months: int = 12,
    limit: int = 100,
) -> list[dict[str, Any]]:
    cutoff = _cutoff(months)
    where = ["decision_date >= ?"]
    params: list[Any] = [cutoff]
    if street:
        where.append("street_key = ?")
        params.append(normalize.street_key(street))
    sql = (
        "SELECT * FROM ura_planning WHERE "
        + " AND ".join(where)
        + " ORDER BY decision_date DESC LIMIT ?"
    )
    rows = conn.execute(sql, [*params, limit]).fetchall()
    results: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        text = f"{item.get('submission_desc') or ''} {item.get('appl_type') or ''}".upper()
        item["is_catalyst"] = any(keyword in text for keyword in CATALYST_KEYWORDS)
        results.append(item)
    return results


def watchlist_add(
    conn: sqlite3.Connection,
    *,
    address: str,
    property_type: str,
    asking_price: float,
    land_sqft: float | None = None,
    built_up_sqft: float | None = None,
    monthly_rent: float | None = None,
    tenure_type: str | None = None,
    lease_start_year: int | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    street = normalize.extract_street(address)
    now = db.now_iso()
    cursor = conn.execute(
        "INSERT INTO watchlist(address, house_no, street, street_key, property_type, tenure_type, "
        "lease_start_year, land_sqft, built_up_sqft, asking_price, monthly_rent, status, notes, "
        "created_at, updated_at) "
        "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'watching', ?, ?, ?)",
        (
            normalize.clean_text(address),
            normalize.clean_text(address).split(" ")[0] if address else None,
            street,
            normalize.street_key(street),
            normalize.normalize_property_type(property_type),
            tenure_type,
            lease_start_year,
            land_sqft,
            built_up_sqft,
            asking_price,
            monthly_rent,
            notes,
            now,
            now,
        ),
    )
    conn.commit()
    return watchlist_get(conn, cursor.lastrowid)


def watchlist_get(conn: sqlite3.Connection, watchlist_id: int) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM watchlist WHERE id = ?", (watchlist_id,)).fetchone()
    if not row:
        raise ValueError(f"Watchlist item not found: {watchlist_id}")
    return dict(row)


def watchlist_list(conn: sqlite3.Connection, status: str | None = None) -> list[dict[str, Any]]:
    if status:
        rows = conn.execute(
            "SELECT * FROM watchlist WHERE status = ? ORDER BY updated_at DESC",
            (status,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM watchlist ORDER BY updated_at DESC").fetchall()
    return _rows_to_dicts(rows)


def watchlist_delete(conn: sqlite3.Connection, watchlist_id: int) -> dict[str, Any]:
    conn.execute("DELETE FROM watchlist WHERE id = ?", (watchlist_id,))
    conn.commit()
    return {"deleted": watchlist_id}


def due_diligence_list(conn: sqlite3.Connection, watchlist_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM due_diligence WHERE watchlist_id = ? ORDER BY checked_at DESC",
        (watchlist_id,),
    ).fetchall()
    return _rows_to_dicts(rows)


def due_diligence_add(
    conn: sqlite3.Connection,
    *,
    watchlist_id: int,
    product: str,
    result: str,
    checked_at: str | None = None,
    file_path: str | None = None,
) -> dict[str, Any]:
    watchlist_get(conn, watchlist_id)
    cursor = conn.execute(
        "INSERT INTO due_diligence(watchlist_id, product, result, checked_at, file_path) "
        "VALUES(?, ?, ?, ?, ?)",
        (watchlist_id, normalize.clean_text(product), result, checked_at or date.today().isoformat(), file_path),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM due_diligence WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return dict(row)


def due_diligence_checklist(watchlist_id: int | None = None) -> dict[str, Any]:
    return {
        "watchlist_id": watchlist_id,
        "note": "INLIS has no public API. Run these manually for a shortlisted property.",
        "products": [
            {"code": "POI", "name": "Property Ownership Information", "fee_sgd": 5.25},
            {"code": "PTI", "name": "Property Title Information", "fee_sgd": 16.00},
            {"code": "PTIEI", "name": "PTI - Encumbrances Information (caveats/mortgages)", "fee_sgd": 11.00},
            {"code": "PTICM", "name": "PTI with Cadastral Map", "fee_sgd": 27.55},
            {"code": "LP", "name": "Lot Particulars", "fee_sgd": 5.80},
            {"code": "CII", "name": "Caveat Index Information", "fee_sgd": 8.40},
        ],
        "steps": [
            "Verify owner name, title type, tenure, lease start and remaining lease.",
            "Check encumbrances: caveats, mortgages, charging orders.",
            "Verify land lot, survey boundary and road/rail reserve lines.",
            "Check URA approved residential use, planning decisions and conservation/LHA controls.",
            "Check PUB flood prone area and site access/drainage.",
        ],
    }


def property_brief(conn: sqlite3.Connection, watchlist_id: int) -> dict[str, Any]:
    item = watchlist_get(conn, watchlist_id)
    pt = normalize.normalize_property_type(item.get("property_type"))
    street = item.get("street") or normalize.extract_street(item["address"])
    sale = get_sale_comps(
        conn,
        street,
        pt,
        tenure_type=item.get("tenure_type"),
        land_sqft=item.get("land_sqft"),
        months=36,
    )
    rent = get_rent_comps(conn, street, pt, sqft=item.get("built_up_sqft"), months=24)
    asking_price = item.get("asking_price")
    land_sqft = item.get("land_sqft")
    built_up_sqft = item.get("built_up_sqft")
    land_psf = asking_price / land_sqft if asking_price and land_sqft else None
    discount_pct = (
        1 - land_psf / sale["stats"]["median_psf"]
        if land_psf and sale["stats"].get("median_psf")
        else None
    )
    monthly_rent = item.get("monthly_rent")
    rent_estimate_source = "provided"
    if monthly_rent is None and built_up_sqft and rent["stats"].get("median_rent_psf"):
        monthly_rent = rent["stats"]["median_rent_psf"] * built_up_sqft
        rent_estimate_source = "street rent psf x built-up"
    if monthly_rent is None and rent["stats"].get("median_rent"):
        monthly_rent = rent["stats"]["median_rent"]
        rent_estimate_source = "street median rent"
    gross_yield = monthly_rent * 12 / asking_price * 100 if monthly_rent and asking_price else None
    remaining = normalize.lease_remaining_years(item.get("tenure_type"), item.get("lease_start_year"))
    risk_flags: list[str] = []
    if remaining is not None and remaining < 60:
        risk_flags.append(f"lease_remaining_{remaining}y")
    return {
        "watchlist": item,
        "metrics": {
            "land_psf": round(land_psf, 2) if land_psf else None,
            "comp_median_psf": sale["stats"].get("median_psf"),
            "discount_pct": round(discount_pct * 100, 2) if discount_pct is not None else None,
            "monthly_rent_estimate": round(monthly_rent, 2) if monthly_rent else None,
            "rent_estimate_source": rent_estimate_source if monthly_rent else None,
            "gross_yield_pct": round(gross_yield, 3) if gross_yield else None,
            "risk_flags": risk_flags,
            "confidence": sale["confidence"],
        },
        "sale_comps": sale,
        "rent_comps": rent,
        "planning_signals": planning_signals(conn, street=street, months=24),
        "geo": geo.street_geo(conn, normalize.street_key(street)),
        "checklist": due_diligence_checklist(watchlist_id),
        "due_diligence": due_diligence_list(conn, watchlist_id),
        "as_of": date.today().isoformat(),
    }
