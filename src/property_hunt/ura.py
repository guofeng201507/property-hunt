from __future__ import annotations

import logging
from typing import Any

import requests

from . import config

logger = logging.getLogger(__name__)


class UraError(RuntimeError):
    pass


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": "property-hunt/0.1"})
    return session


def _check(payload: dict[str, Any]) -> dict[str, Any]:
    status = payload.get("Status")
    if status != "Success":
        raise UraError(f"URA API error: {payload.get('Message') or status or payload}")
    return payload


def get_token(access_key: str | None = None) -> str:
    key = (access_key or config.URA_ACCESS_KEY).strip()
    if not key:
        raise UraError("URA_ACCESS_KEY is missing. Add it to .env or use demo mode.")
    url = f"{config.URA_BASE_URL}/insertNewToken/v1"
    response = _session().get(url, headers={"AccessKey": key}, timeout=config.URA_TIMEOUT)
    response.raise_for_status()
    payload = _check(response.json())
    token = payload.get("Result")
    if not token:
        raise UraError("URA token response did not contain Result")
    return str(token)


def fetch_transactions(batch: int, token: str, access_key: str | None = None) -> dict[str, Any]:
    key = (access_key or config.URA_ACCESS_KEY).strip()
    url = f"{config.URA_BASE_URL}/invokeUraDS/v1"
    response = _session().get(
        url,
        params={"service": "PMI_Resi_Transaction", "batch": batch},
        headers={"AccessKey": key, "Token": token},
        timeout=config.URA_TIMEOUT,
    )
    response.raise_for_status()
    return _check(response.json())


def fetch_rentals(
    ref_period: str,
    token: str,
    access_key: str | None = None,
) -> dict[str, Any]:
    key = (access_key or config.URA_ACCESS_KEY).strip()
    url = f"{config.URA_BASE_URL}/invokeUraDS/v1"
    response = _session().get(
        url,
        params={"service": "PMI_Resi_Rental", "refPeriod": ref_period},
        headers={"AccessKey": key, "Token": token},
        timeout=config.URA_TIMEOUT,
    )
    response.raise_for_status()
    return _check(response.json())


def fetch_planning(
    token: str,
    *,
    year: int | None = None,
    last_dnload_date: str | None = None,
    access_key: str | None = None,
) -> dict[str, Any]:
    if bool(year) == bool(last_dnload_date):
        raise ValueError("Provide exactly one of year or last_dnload_date")
    key = (access_key or config.URA_ACCESS_KEY).strip()
    params: dict[str, Any] = {"service": "Planning_Decision"}
    if year:
        params["year"] = year
    else:
        params["last_dnload_date"] = last_dnload_date
    url = f"{config.URA_BASE_URL}/invokeUraDS/v1"
    response = _session().get(
        url,
        params=params,
        headers={"AccessKey": key, "Token": token},
        timeout=config.URA_TIMEOUT,
    )
    response.raise_for_status()
    return _check(response.json())
