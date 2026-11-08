from __future__ import annotations

import logging
import sys
from contextlib import closing
from typing import Any

from mcp.server.fastmcp import FastMCP

from . import comps, config, db

logging.basicConfig(stream=sys.stderr, level=config.LOG_LEVEL)
logger = logging.getLogger(__name__)

mcp = FastMCP("property-hunt")


def _read_conn():
    return closing(db.connect(readonly=True))


@mcp.tool()
def get_data_status() -> dict[str, Any]:
    """Return local database mode, row counts and last ingest time."""
    with closing(db.connect(readonly=True)) as conn:
        return {
            "mode": db.get_meta(conn, "data_mode", "empty"),
            "last_ingest_at": db.get_meta(conn, "last_ingest_at"),
            "counts": db.table_counts(conn),
            "db_path": str(config.DB_PATH),
        }


@mcp.tool()
def search_street(
    query: str,
    property_type: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Search street-level stats by street name (e.g. JALAN, SUNSET)."""
    with _read_conn() as conn:
        return comps.search_street(conn, query, property_type=property_type, limit=limit)


@mcp.tool()
def get_sale_comps(
    street: str,
    property_type: str,
    tenure_type: str | None = None,
    land_sqft: float | None = None,
    months: int = 36,
) -> dict[str, Any]:
    """Get landed sale comparables and median/percentile land psf."""
    with _read_conn() as conn:
        return comps.get_sale_comps(
            conn,
            street,
            property_type,
            tenure_type=tenure_type,
            land_sqft=land_sqft,
            months=months,
        )


@mcp.tool()
def get_rent_comps(
    street: str,
    property_type: str,
    sqft: float | None = None,
    months: int = 24,
) -> dict[str, Any]:
    """Get rental comparables for landed or non-landed property."""
    with _read_conn() as conn:
        return comps.get_rent_comps(conn, street, property_type, sqft=sqft, months=months)


@mcp.tool()
def estimate_yield(
    street: str,
    property_type: str,
    price: float,
    rent: float | None = None,
    built_up_sqft: float | None = None,
) -> dict[str, Any]:
    """Estimate gross and net yield, using comps when rent is omitted."""
    with _read_conn() as conn:
        return comps.estimate_yield(
            conn,
            street,
            property_type,
            price,
            rent=rent,
            built_up_sqft=built_up_sqft,
        )


@mcp.tool()
def get_value_gap(
    street: str | None = None,
    property_type: str | None = None,
    months: int = 12,
    discount_threshold: float = 0.10,
) -> list[dict[str, Any]]:
    """Find recent landed transactions below their street/type median land psf."""
    with _read_conn() as conn:
        return comps.value_gaps(
            conn,
            street=street,
            property_type=property_type,
            months=months,
            discount_threshold=discount_threshold,
        )


@mcp.tool()
def get_planning_signals(
    street: str | None = None,
    months: int = 12,
) -> list[dict[str, Any]]:
    """Get recent URA Written Permission decisions and catalyst flags."""
    with _read_conn() as conn:
        return comps.planning_signals(conn, street=street, months=months)


@mcp.tool()
def watchlist_add(
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
    """Add a candidate property to the personal watchlist."""
    with closing(db.connect()) as conn:
        return comps.watchlist_add(
            conn,
            address=address,
            property_type=property_type,
            asking_price=asking_price,
            land_sqft=land_sqft,
            built_up_sqft=built_up_sqft,
            monthly_rent=monthly_rent,
            tenure_type=tenure_type,
            lease_start_year=lease_start_year,
            notes=notes,
        )


@mcp.tool()
def watchlist_list(status: str | None = None) -> list[dict[str, Any]]:
    """List watchlist properties, optionally filtered by status."""
    with _read_conn() as conn:
        return comps.watchlist_list(conn, status=status)


@mcp.tool()
def watchlist_delete(watchlist_id: int) -> dict[str, Any]:
    """Delete a watchlist property and its due-diligence records."""
    with closing(db.connect()) as conn:
        return comps.watchlist_delete(conn, watchlist_id)


@mcp.tool()
def get_property_brief(watchlist_id: int) -> dict[str, Any]:
    """Get comps, yield, discount, planning signals and due-diligence checklist."""
    with _read_conn() as conn:
        return comps.property_brief(conn, watchlist_id)


@mcp.tool()
def get_due_diligence_checklist(watchlist_id: int | None = None) -> dict[str, Any]:
    """Return the INLIS/title/planning due-diligence checklist."""
    return comps.due_diligence_checklist(watchlist_id)


@mcp.tool()
def due_diligence_add(
    watchlist_id: int,
    product: str,
    result: str,
    checked_at: str | None = None,
    file_path: str | None = None,
) -> dict[str, Any]:
    """Record an INLIS due-diligence product result for a watchlist property."""
    with closing(db.connect()) as conn:
        return comps.due_diligence_add(
            conn,
            watchlist_id=watchlist_id,
            product=product,
            result=result,
            checked_at=checked_at,
            file_path=file_path,
        )


@mcp.tool()
def due_diligence_list(watchlist_id: int) -> list[dict[str, Any]]:
    """List recorded INLIS due-diligence results for a watchlist property."""
    with _read_conn() as conn:
        return comps.due_diligence_list(conn, watchlist_id)


def main() -> None:
    logger.info("Starting property-hunt MCP server (stdio)")
    mcp.run()


if __name__ == "__main__":
    main()
