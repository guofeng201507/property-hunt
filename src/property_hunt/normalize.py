from __future__ import annotations

import hashlib
import re
from datetime import date

LANDED_TYPES = {"DETACHED", "SEMI_D", "TERRACE"}
STRATA_LANDED_TYPES = {"STRATA_DETACHED", "STRATA_SEMI_D", "STRATA_TERRACE"}
PROPERTY_TYPE_LABELS = {
    "DETACHED": "Detached",
    "SEMI_D": "Semi-Detached",
    "TERRACE": "Terrace",
    "STRATA_DETACHED": "Strata Detached",
    "STRATA_SEMI_D": "Strata Semi-Detached",
    "STRATA_TERRACE": "Strata Terrace",
    "CONDO": "Condominium",
    "APARTMENT": "Apartment",
    "EC": "Executive Condominium",
    "NON_LANDED": "Non-Landed",
}


def clean_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def street_key(street: str) -> str:
    return clean_text(street).upper()


def extract_street(address: str) -> str:
    first = clean_text(address).split(",")[0].strip()
    first = re.sub(r"^(BLK|BLOCK)\s+", "", first, flags=re.IGNORECASE)
    first = re.sub(r"^#?\d+[A-Z]?(?:-\d+[A-Z]?)?\s+", "", first, flags=re.IGNORECASE)
    first = re.sub(r"^\d+[A-Z]?[,\s]+", "", first, flags=re.IGNORECASE)
    return first.strip().upper()


def parse_mmyy(value: str | None) -> date | None:
    text = clean_text(value)
    if not re.fullmatch(r"\d{4}", text):
        return None
    month = int(text[:2])
    year = int(text[2:])
    year += 1900 if year >= 70 else 2000
    if not 1 <= month <= 12:
        return None
    return date(year, month, 1)


def parse_date_ddmmyyyy(value: str | None) -> date | None:
    text = clean_text(value)
    match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if not match:
        return None
    day, month, year = (int(part) for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_tenure(raw: str | None) -> tuple[str, int | None]:
    text = clean_text(raw)
    lower = text.lower()
    if "freehold" in lower:
        return "FREEHOLD", None
    match = re.search(r"(\d{2,4})\s*(?:yrs?|years?)\s*lease.*?(\d{4})", lower)
    if match:
        term = int(match.group(1))
        start = int(match.group(2))
        if term <= 99:
            return "LEASEHOLD_99", start
        if term >= 900:
            return "LEASEHOLD_999", start
        return "LEASEHOLD_OTHER", start
    match = re.search(r"(\d{2,4})\s*(?:yrs?|years?)", lower)
    if match:
        term = int(match.group(1))
        if term <= 99:
            return "LEASEHOLD_99", None
        if term >= 900:
            return "LEASEHOLD_999", None
        return "LEASEHOLD_OTHER", None
    return "UNKNOWN", None


def lease_remaining_years(tenure_type: str | None, lease_start_year: int | None) -> int | None:
    if not tenure_type or lease_start_year is None:
        return None
    term = {"LEASEHOLD_99": 99, "LEASEHOLD_999": 999}.get(tenure_type)
    if term is None:
        return None
    return max(0, term - (date.today().year - lease_start_year))


def normalize_property_type(raw: str | None) -> str:
    text = clean_text(raw).lower()
    text = text.replace("-", " ")
    if "strata" in text and "detached" in text:
        return "STRATA_DETACHED"
    if "strata" in text and ("semi" in text or "semi d" in text):
        return "STRATA_SEMI_D"
    if "strata" in text and "terrace" in text:
        return "STRATA_TERRACE"
    if "semi" in text and "detached" in text or "semi d" in text:
        return "SEMI_D"
    if "terrace" in text:
        return "TERRACE"
    if "detached" in text:
        return "DETACHED"
    if "executive condominium" in text or text == "ec":
        return "EC"
    if "condominium" in text or "condo" in text:
        return "CONDO"
    if "apartment" in text:
        return "APARTMENT"
    if "non landed" in text or "non landed properties" in text:
        return "NON_LANDED"
    return re.sub(r"[^A-Z0-9]+", "_", clean_text(raw).upper()).strip("_") or "UNKNOWN"


def property_type_label(code: str | None) -> str:
    return PROPERTY_TYPE_LABELS.get(code or "", code or "Unknown")


def is_landed(property_type: str) -> bool:
    return property_type in LANDED_TYPES or property_type in STRATA_LANDED_TYPES


def area_basis(property_type: str) -> str:
    if property_type in LANDED_TYPES:
        return "LAND"
    if property_type in STRATA_LANDED_TYPES or property_type in {"CONDO", "APARTMENT", "EC", "NON_LANDED"}:
        return "STRATA"
    return "UNKNOWN"


def area_band(property_type: str, area_sqft: float | None) -> str:
    if not area_sqft or area_sqft <= 0:
        return "unknown"
    if property_type == "TERRACE":
        cuts = (1500, 2000, 2800)
    elif property_type == "SEMI_D":
        cuts = (2500, 3500, 5000)
    elif property_type == "DETACHED":
        cuts = (4000, 6000, 10000)
    else:
        cuts = (1000, 1500, 2000)
    if area_sqft < cuts[0]:
        return f"<{cuts[0]}"
    if area_sqft < cuts[1]:
        return f"{cuts[0]}-{cuts[1]}"
    if area_sqft < cuts[2]:
        return f"{cuts[1]}-{cuts[2]}"
    return f">{cuts[2]}"


def parse_area_range(value: str | None) -> tuple[float | None, float | None, float | None]:
    text = clean_text(value)
    if not text or text.lower() in {"na", "n/a", "-", "unknown"}:
        return None, None, None
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)", text)
    if match:
        low, high = float(match.group(1)), float(match.group(2))
        return low, high, (low + high) / 2
    try:
        value_float = float(text)
    except ValueError:
        return None, None, None
    return value_float, value_float, value_float


def normalize_sale_type(value: str | None) -> str:
    return {"1": "NEW", "2": "SUB", "3": "RESALE"}.get(clean_text(value), "UNKNOWN")


def make_hash(*parts: object) -> str:
    payload = "|".join(clean_text(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sqm_to_sqft(value: float | None) -> float | None:
    return value * 10.7639 if value is not None else None
