from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from pyproj import Geod, Transformer
from shapely.geometry import Point, shape
from shapely.strtree import STRtree

from . import config, db

logger = logging.getLogger(__name__)

GEO_DIR = config.DATA_DIR / "geo"
GEO_DIR.mkdir(parents=True, exist_ok=True)

LAYERS: dict[str, dict[str, str]] = {
    "land_use": {
        "dataset_id": "d_a8c3546b26712e35021f3a681d0353ae",
        "name": "Master Plan 2025 Land Use Layer",
        "file": "mp2025_land_use.geojson",
    },
    "lha": {
        "dataset_id": "d_70a5a4b67d9171dc0db6f6fd259a3215",
        "name": "Master Plan 2025 SDCP Landed Housing Area layer",
        "file": "mp2025_lha.geojson",
    },
    "conservation": {
        "dataset_id": "d_a3da5c26227f9ebc7e150813255f7a56",
        "name": "Master Plan 2025 Conservation Area Boundary Layer",
        "file": "mp2025_conservation.geojson",
    },
    "height": {
        "dataset_id": "d_0720d955bce304046d173d9e2a309652",
        "name": "Master Plan 2025 SDCP Building Height Control layer",
        "file": "mp2025_height.geojson",
    },
    "cadastral": {
        "dataset_id": "d_e7395d743076a2bcc487b0d12b9bf33b",
        "name": "SLA Cadastral Land Parcel",
        "file": "sla_cadastral.geojson",
    },
    "mrt": {
        "dataset_id": "d_b39d3a0871985372d7e1637193335da5",
        "name": "LTA MRT Station Exit (GEOJSON)",
        "file": "lta_mrt_exits.geojson",
    },
}

POLL_URL = "https://api-open.data.gov.sg/v1/public/api/datasets/{dataset_id}/poll-download"
_INDEX_CACHE: dict[str, tuple[float, "LayerIndex"]] = {}


@dataclass
class Feature:
    geometry: Any
    props: dict[str, Any]


class LayerIndex:
    def __init__(self, features: list[Feature]) -> None:
        self.features = features
        self.geometries = [feature.geometry for feature in features]
        self.tree = STRtree(self.geometries)

    def lookup(self, point: Point) -> list[dict[str, Any]]:
        indices = self.tree.query(point)
        return [self.features[int(index)].props for index in indices]


def layer_path(key: str) -> Path:
    return GEO_DIR / LAYERS[key]["file"]


def has_layers() -> bool:
    return any(layer_path(key).exists() for key in LAYERS)


def _poll_download(dataset_id: str) -> dict[str, Any]:
    url = POLL_URL.format(dataset_id=dataset_id)
    for attempt in range(6):
        response = requests.get(url, timeout=60)
        if response.status_code != 429:
            response.raise_for_status()
            return response.json()
        wait = 6 * (attempt + 1)
        logger.warning("data.gov.sg rate limit hit; waiting %ss", wait)
        time.sleep(wait)
    response.raise_for_status()
    raise RuntimeError("data.gov.sg poll-download failed after retries")


def download_layer(conn, key: str, force: bool = False) -> Path:
    meta = LAYERS[key]
    path = layer_path(key)
    if path.exists() and not force:
        logger.info("Geo layer already exists: %s", path)
        _record_layer(conn, key, meta, path)
        return path

    payload = _poll_download(meta["dataset_id"])
    url = (payload.get("data") or {}).get("url")
    if not url:
        raise RuntimeError(f"data.gov.sg did not return a download URL for {key}: {payload}")

    logger.info("Downloading %s ...", meta["name"])
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with requests.get(url, stream=True, timeout=600) as response:
        response.raise_for_status()
        with tmp_path.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
    tmp_path.replace(path)
    logger.info("Downloaded %s (%.1f MB)", path.name, path.stat().st_size / 1024 / 1024)
    _record_layer(conn, key, meta, path)
    time.sleep(6)
    return path


def _record_layer(conn, key: str, meta: dict[str, str], path: Path) -> None:
    conn.execute(
        "INSERT INTO geo_layers(key, dataset_id, name, path, feature_count, downloaded_at, updated_at) "
        "VALUES(?, ?, ?, ?, NULL, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET path=excluded.path, updated_at=excluded.updated_at",
        (key, meta["dataset_id"], meta["name"], str(path), db.now_iso(), db.now_iso()),
    )
    conn.commit()


def download_all(conn, force: bool = False) -> dict[str, str]:
    result: dict[str, str] = {}
    for key in LAYERS:
        result[key] = str(download_layer(conn, key, force=force))
    return result


def load_index(key: str) -> LayerIndex | None:
    path = layer_path(key)
    if not path.exists():
        return None
    mtime = path.stat().st_mtime
    cached = _INDEX_CACHE.get(key)
    if cached and cached[0] == mtime:
        return cached[1]
    logger.info("Loading %s ...", path.name)
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    features: list[Feature] = []
    for item in payload.get("features", []):
        geometry = item.get("geometry")
        if not geometry:
            continue
        try:
            parsed = shape(geometry)
        except Exception:
            continue
        features.append(Feature(parsed, item.get("properties") or {}))
    index = LayerIndex(features)
    _INDEX_CACHE[key] = (mtime, index)
    logger.info("Loaded %s: %d features", path.name, len(features))
    return index


def _pick_land_use(props_list: list[dict[str, Any]]) -> dict[str, Any]:
    for props in props_list:
        desc = str(props.get("LU_DESC") or "").upper()
        if "RESIDENTIAL" in desc:
            return props
    return props_list[0] if props_list else {}


def _first(props_list: list[dict[str, Any]]) -> dict[str, Any]:
    return props_list[0] if props_list else {}


def enrich_street_stats(conn) -> int:
    indices = {key: load_index(key) for key in LAYERS}
    if not any(indices.values()):
        logger.warning("No geo layers available; run scripts/run_geo.py first")
        return 0

    rows = conn.execute(
        "SELECT street_key, AVG(x_svy21) AS x, AVG(y_svy21) AS y "
        "FROM ura_transactions WHERE x_svy21 IS NOT NULL AND y_svy21 IS NOT NULL "
        "GROUP BY street_key"
    ).fetchall()
    point_rows = conn.execute(
        "SELECT street_key, x_svy21, y_svy21 FROM ("
        "  SELECT street_key, x_svy21, y_svy21, "
        "         ROW_NUMBER() OVER (PARTITION BY street_key ORDER BY contract_date DESC) AS rn "
        "  FROM ura_transactions WHERE x_svy21 IS NOT NULL AND y_svy21 IS NOT NULL"
        ") WHERE rn <= 10"
    ).fetchall()
    points_by_street: dict[str, list[tuple[float, float]]] = {}
    for row in point_rows:
        points_by_street.setdefault(row["street_key"], []).append((row["x_svy21"], row["y_svy21"]))

    transformer = Transformer.from_crs("EPSG:3414", "EPSG:4326", always_xy=True)
    geod = Geod(ellps="WGS84")
    now = db.now_iso()
    updates: list[tuple[Any, ...]] = []
    for row in rows:
        lon, lat = transformer.transform(row["x"], row["y"])
        point = Point(lon, lat)
        land_use: dict[str, Any] = {}
        if indices["land_use"]:
            counts: dict[str, int] = {}
            examples: dict[str, dict[str, Any]] = {}
            candidates = points_by_street.get(row["street_key"], [(row["x"], row["y"])])
            for x, y in candidates:
                candidate_lon, candidate_lat = transformer.transform(x, y)
                for props in indices["land_use"].lookup(Point(candidate_lon, candidate_lat)):
                    desc = str(props.get("LU_DESC") or "").strip()
                    if desc:
                        counts[desc] = counts.get(desc, 0) + 1
                        examples.setdefault(desc, props)
            if counts:
                residential = [desc for desc in counts if "RESIDENTIAL" in desc.upper()]
                chosen_desc = max(residential or counts, key=lambda key: counts[key])
                land_use = examples.get(chosen_desc, {"LU_DESC": chosen_desc})
        lha = _first(indices["lha"].lookup(point)) if indices["lha"] else {}
        conservation = _first(indices["conservation"].lookup(point)) if indices["conservation"] else {}
        height = _first(indices["height"].lookup(point)) if indices["height"] else {}
        cadastral = _first(indices["cadastral"].lookup(point)) if indices["cadastral"] else {}
        nearest_mrt: dict[str, Any] = {}
        nearest_mrt_distance = None
        if indices.get("mrt") and indices["mrt"].features:
            nearest_index = indices["mrt"].tree.nearest(point)
            if nearest_index is not None and nearest_index >= 0:
                station_geometry = indices["mrt"].geometries[int(nearest_index)]
                if station_geometry.geom_type == "Point":
                    _, _, nearest_mrt_distance = geod.inv(
                        lon, lat, station_geometry.x, station_geometry.y
                    )
                    nearest_mrt = indices["mrt"].features[int(nearest_index)].props
        lu_desc = land_use.get("LU_DESC")
        if str(lu_desc or "").upper() == "ROAD" and lha:
            lu_desc = "RESIDENTIAL (LHA)"
        updates.append(
            (
                lu_desc,
                land_use.get("GPR"),
                height.get("HT_CTL_TXT") or land_use.get("WHI_Q_MX"),
                lha.get("CLASSIFCTN"),
                lha.get("NAME"),
                lha.get("TYPE"),
                conservation.get("NAME"),
                cadastral.get("LOT_KEY"),
                nearest_mrt.get("STATION_NA"),
                nearest_mrt.get("EXIT_CODE"),
                nearest_mrt_distance,
                now,
                row["street_key"],
            )
        )
    conn.executemany(
        "UPDATE street_stats SET lu_desc=?, gpr=?, height_control=?, lha_class=?, "
        "lha_name=?, lha_type=?, conservation_area=?, cadastral_lot=?, "
        "nearest_mrt_name=?, nearest_mrt_exit=?, nearest_mrt_distance_m=?, geo_updated_at=? "
        "WHERE street_key=?",
        updates,
    )
    conn.commit()
    return len(updates)


def street_geo(conn, street_key_value: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT street, lu_desc, gpr, height_control, lha_class, lha_name, lha_type, "
        "conservation_area, cadastral_lot, nearest_mrt_name, nearest_mrt_exit, "
        "nearest_mrt_distance_m, geo_updated_at "
        "FROM street_stats WHERE street_key = ? LIMIT 1",
        (street_key_value,),
    ).fetchone()
    return dict(row) if row else {}


def layer_status(conn) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM geo_layers ORDER BY name").fetchall()
    results = [dict(row) for row in rows]
    for item in results:
        path = Path(item["path"])
        item["exists"] = path.exists()
        item["size_mb"] = round(path.stat().st_size / 1024 / 1024, 1) if path.exists() else 0
    return results
