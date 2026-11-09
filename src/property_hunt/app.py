from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from property_hunt import comps, config, db, geo, ingest, normalize  # noqa: E402

st.set_page_config(page_title="Property Hunt", layout="wide")


@st.cache_resource
def ensure_db() -> None:
    conn = db.connect()
    db.init_db(conn)
    conn.close()


def counts() -> dict[str, int]:
    conn = db.connect()
    try:
        return db.table_counts(conn)
    finally:
        conn.close()


def mode_label() -> str:
    conn = db.connect()
    try:
        return db.get_meta(conn, "data_mode", "empty") or "empty"
    finally:
        conn.close()


def load_demo() -> None:
    conn = db.connect()
    try:
        ingest.ingest_demo(conn)
        comps.refresh_street_stats(conn)
    finally:
        conn.close()


def refresh_stats() -> None:
    conn = db.connect()
    try:
        comps.refresh_street_stats(conn)
        if geo.has_layers():
            geo.enrich_street_stats(conn)
    finally:
        conn.close()


def tenure_label(value: str | None) -> str:
    return {
        "FREEHOLD": "FH",
        "LEASEHOLD_99": "99y",
        "LEASEHOLD_999": "999y",
        "LEASEHOLD_OTHER": "Lease",
        "UNKNOWN": "—",
    }.get(value or "", value or "—")


def _is_missing(value: object) -> bool:
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def compact_zoning(value: str | None) -> str:
    if _is_missing(value):
        return "—"
    text = str(value).upper()
    if "RESIDENTIAL WITH COMMERCIAL" in text or "COMMERCIAL & RESIDENTIAL" in text:
        return "Resi/Comm"
    if "RESIDENTIAL" in text:
        return "Resi"
    if "COMMERCIAL" in text:
        return "Comm"
    return str(value)


def compact_lha(value: str | None) -> str:
    if _is_missing(value):
        return "—"
    text = str(value).upper()
    if "GOOD CLASS" in text:
        return "GCB"
    if "LANDED" in text:
        return "Landed"
    return str(value)


def compact_mrt(value: str | None) -> str:
    if _is_missing(value):
        return "—"
    return str(value).replace(" MRT STATION", "").title()


def dataframe(rows: list[dict], columns: dict[str, str] | None = None) -> None:
    if not rows:
        st.info("没有数据。检查筛选条件，或先运行 `make ingest` / `make geo`。")
        return
    frame = pd.DataFrame(rows)
    if "property_type" in frame.columns:
        frame["property_type"] = frame["property_type"].map(
            lambda value: normalize.property_type_label(value) if value else value
        )
    if "tenure_type" in frame.columns:
        frame["tenure_type"] = frame["tenure_type"].map(tenure_label)
    for column in ("remaining_lease_years", "comp_remaining_lease_years"):
        if column in frame.columns:
            frame[column] = frame[column].map(
                lambda value: "—" if pd.isna(value) else int(value)
            )
    for column in ("lu_desc", "comp_zoning"):
        if column in frame.columns:
            frame[column] = frame[column].map(compact_zoning)
    for column in ("lha_class", "comp_lha"):
        if column in frame.columns:
            frame[column] = frame[column].map(compact_lha)
    for column in ("nearest_mrt_name", "comp_mrt_name"):
        if column in frame.columns:
            frame[column] = frame[column].map(compact_mrt)
    for column in (
        "sale_median_psf", "sale_median_price", "psf", "comp_median_psf",
        "rent_median", "rent_monthly", "area_sqft", "area_sqft_mid",
        "nearest_mrt_distance_m", "comp_mrt_distance_m",
    ):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce").round(0)
    for column in ("gross_yield_pct", "discount_pct"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce").round(2)
    if "confidence" in frame.columns:
        frame["confidence"] = frame["confidence"].map(
            {"high": "High", "medium": "Med", "low": "Low"}
        ).fillna(frame["confidence"])
    if "risk_flags" in frame.columns:
        frame["risk_flags"] = frame["risk_flags"].map(
            lambda value: ", ".join(
                str(item).replace("lease_remaining_", "Lease ") for item in value
            ) if isinstance(value, list) else value
        )
    if columns:
        frame = frame[[column for column in columns if column in frame.columns]].rename(columns=columns)
    st.dataframe(frame, width="stretch", hide_index=True)


ensure_db()
current_counts = counts()
current_mode = mode_label()

with st.sidebar:
    st.title("Property Hunt")
    st.caption("Personal landed property research")
    st.write(f"数据模式：**{current_mode}**")
    st.write(f"成交：**{current_counts['ura_transactions']}**")
    st.write(f"租赁：**{current_counts['ura_rentals']}**")
    st.write(f"规划：**{current_counts['ura_planning']}**")
    st.write(f"街道统计：**{current_counts['street_stats']}**")
    if current_mode != "live" and st.button("加载 demo 数据", width="stretch"):
        load_demo()
        st.rerun()
    if st.button("重算街道统计", width="stretch"):
        refresh_stats()
        st.rerun()
    st.caption(f"DB: {config.DB_PATH}")
    st.caption("MP2025/地籍: " + ("已加载" if geo.has_layers() else "未加载，运行 make geo"))
    if current_mode == "live":
        st.caption("数据已加载；刷新用 `make ingest`。")
    else:
        st.caption("真实数据：在 .env 填 URA_ACCESS_KEY，然后 `make ingest`。")

st.title("新加坡有地房产 · 个人决策台")
st.caption(
    "P0 是街道级监控：URA 成交/租赁没有门牌号，具体房源请用 Watchlist 手动录入，再做 INLIS 尽调。"
)

tab_yield, tab_gap, tab_watchlist, tab_planning = st.tabs(
    ["收租筛选", "估值差", "Watchlist", "规划信号"]
)

with tab_yield:
    st.subheader("半独立 / 排屋收租筛选")
    st.caption("gross yield 是街道级估算；不要只看 yield，旁边看 land psf 和样本数。")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        yield_type = st.selectbox(
            "Property type",
            ["ALL", "SEMI_D", "TERRACE", "DETACHED"],
            format_func=lambda value: {
                "ALL": "All landed",
                "SEMI_D": "Semi-Detached",
                "TERRACE": "Terrace",
                "DETACHED": "Detached",
            }[value],
            key="yield_type",
        )
    with col2:
        yield_district = st.text_input("District（可空）", key="yield_district")
    with col3:
        min_sale = st.number_input("最少成交样本（36m）", min_value=0, value=3, step=1)
    with col4:
        min_rent = st.number_input("最少租赁样本（24m）", min_value=0, value=3, step=1)
    min_lease = st.slider("最少剩余 lease（年，freehold 不限）", min_value=0, max_value=99, value=40)
    col5, col6 = st.columns(2)
    with col5:
        mrt_station = st.text_input("MRT station（可空，如 KEMBANGAN）", key="yield_mrt")
    with col6:
        max_mrt_distance = st.slider("离 MRT 最远（米，直线）", min_value=0, max_value=2000, value=0, step=50)

    conn = db.connect()
    try:
        rows = comps.list_street_stats(
            conn,
            property_type=None if yield_type == "ALL" else yield_type,
            district=yield_district.strip() or None,
            min_sale=int(min_sale),
            min_rent=int(min_rent),
            min_lease_remaining=int(min_lease),
            mrt_station=mrt_station.strip() or None,
            max_mrt_distance_m=float(max_mrt_distance),
            sort="gross_yield_pct",
        )
    finally:
        conn.close()
    st.caption(f"{len(rows)} 条街道/面积段，按 gross yield 排序。")
    dataframe(
        rows,
        {
            "street": "Street",
            "property_type": "Type",
            "tenure_type": "Tenure",
            "remaining_lease_years": "Lease",
            "area_band": "Area band",
            "lha_class": "LHA",
            "nearest_mrt_name": "MRT",
            "nearest_mrt_distance_m": "MRT m",
            "sale_median_psf": "Land psf",
            "rent_median": "Rent",
            "gross_yield_pct": "Yield %",
            "confidence": "Conf",
        },
    )
    if rows:
        best = rows[0]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Best street", best["street"])
        c2.metric("Gross yield", f"{best['gross_yield_pct']:.2f}%")
        c3.metric("Land psf", f"S${best['sale_median_psf']:,.0f}")
        c4.metric("Confidence", best["confidence"])

with tab_gap:
    st.subheader("低买高卖 / 估值差")
    st.caption("折价是相对同街道、同类型、同 tenure、同面积段的成交中位数；先看 risk/confidence。")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        gap_type = st.selectbox(
            "Property type",
            ["ALL", "SEMI_D", "TERRACE", "DETACHED"],
            format_func=lambda value: {
                "ALL": "All landed",
                "SEMI_D": "Semi-Detached",
                "TERRACE": "Terrace",
                "DETACHED": "Detached",
            }[value],
            key="gap_type",
        )
    with col2:
        gap_street = st.text_input("Street（可空）", key="gap_street")
    with col3:
        gap_threshold = st.slider("最低折价 %", min_value=0, max_value=40, value=8, step=1)
    with col4:
        gap_months = st.selectbox("最近几个月", [6, 12, 24], index=1)

    conn = db.connect()
    try:
        rows = comps.value_gaps(
            conn,
            street=gap_street.strip() or None,
            property_type=None if gap_type == "ALL" else gap_type,
            months=int(gap_months),
            discount_threshold=gap_threshold / 100,
        )
    finally:
        conn.close()
    st.caption(f"{len(rows)} 条低于街道中位数的成交。")
    dataframe(
        rows,
        {
            "street": "Street",
            "property_type_label": "Type",
            "contract_date": "Contract",
            "price": "Price",
            "area_sqft": "Land sqft",
            "psf": "Land psf",
            "comp_median_psf": "Comp psf",
            "discount_pct": "Disc %",
            "comp_remaining_lease_years": "Lease",
            "comp_mrt_name": "MRT",
            "confidence": "Conf",
            "risk_flags": "Risk",
        },
    )

with tab_watchlist:
    st.subheader("Watchlist：正在看的房")
    st.caption("URA 没有门牌级数据；这里手动录入候选房源，自动算 comps / yield / 折价。")
    with st.form("watchlist_form", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            address = st.text_input("Address", placeholder="15 JALAN BERJAYA")
            wl_type = st.selectbox(
                "Property type",
                ["SEMI_D", "TERRACE", "DETACHED"],
                format_func=lambda value: {
                    "SEMI_D": "Semi-Detached",
                    "TERRACE": "Terrace",
                    "DETACHED": "Detached",
                }[value],
            )
            tenure_type = st.selectbox(
                "Tenure",
                ["FREEHOLD", "LEASEHOLD_99", "LEASEHOLD_999", "LEASEHOLD_OTHER", "UNKNOWN"],
            )
        with col2:
            asking_price = st.number_input("Asking price (S$)", min_value=0.0, step=100000.0)
            land_sqft = st.number_input("Land sqft", min_value=0.0, step=100.0)
            built_up_sqft = st.number_input("Built-up sqft（可空填 0）", min_value=0.0, step=100.0)
        with col3:
            monthly_rent = st.number_input("Monthly rent（可空填 0）", min_value=0.0, step=100.0)
            lease_start_year = st.number_input("Lease start year（freehold 填 0）", min_value=0, step=1)
            notes = st.text_area("Notes", height=80)
        submitted = st.form_submit_button("加入 watchlist")
    if submitted and address.strip() and asking_price > 0:
        conn = db.connect()
        try:
            comps.watchlist_add(
                conn,
                address=address.strip(),
                property_type=wl_type,
                asking_price=asking_price,
                land_sqft=land_sqft or None,
                built_up_sqft=built_up_sqft or None,
                monthly_rent=monthly_rent or None,
                tenure_type=tenure_type,
                lease_start_year=int(lease_start_year) or None,
                notes=notes.strip() or None,
            )
        finally:
            conn.close()
        st.success("已加入 watchlist")
        st.rerun()

    conn = db.connect()
    try:
        watchlist = comps.watchlist_list(conn)
    finally:
        conn.close()
    if watchlist:
        options = {f"{item['id']} · {item['address']}": item["id"] for item in watchlist}
        selected = st.selectbox("选择房源查看 brief", list(options))
        watchlist_id = options[selected]
        if st.button("删除这条 watchlist"):
            conn = db.connect()
            try:
                comps.watchlist_delete(conn, watchlist_id)
            finally:
                conn.close()
            st.success("已删除")
            st.rerun()
        conn = db.connect()
        try:
            brief = comps.property_brief(conn, watchlist_id)
        finally:
            conn.close()
        metrics = brief["metrics"]
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Land psf", f"S${metrics['land_psf']:,.0f}" if metrics["land_psf"] else "—")
        c2.metric("Comp median psf", f"S${metrics['comp_median_psf']:,.0f}" if metrics["comp_median_psf"] else "—")
        c3.metric("Discount", f"{metrics['discount_pct']:.1f}%" if metrics["discount_pct"] is not None else "—")
        c4.metric("Est. monthly rent", f"S${metrics['monthly_rent_estimate']:,.0f}" if metrics["monthly_rent_estimate"] else "—")
        c5.metric("Gross yield", f"{metrics['gross_yield_pct']:.2f}%" if metrics["gross_yield_pct"] else "—")
        st.caption(
            f"Sale comps: {brief['sale_comps']['stats']['count']} · "
            f"scope={brief['sale_comps']['scope']} · confidence={brief['sale_comps']['confidence']}；"
            f"rent estimate source={metrics['rent_estimate_source'] or '—'}；risk={metrics['risk_flags'] or '—'}"
        )
        geo_info = brief.get("geo") or {}
        st.markdown("**Geo / Planning**")
        g1, g2, g3 = st.columns(3)
        g1.metric("Zoning", compact_zoning(geo_info.get("lu_desc")))
        g2.metric("GPR", geo_info.get("gpr") or "—")
        g3.metric("LHA", compact_lha(geo_info.get("lha_class")))
        g4, g5, g6 = st.columns(3)
        g4.metric("Height", geo_info.get("height_control") or "—")
        g5.metric("Conservation", geo_info.get("conservation_area") or "—")
        g6.metric("Lot", geo_info.get("cadastral_lot") or "—")
        if geo_info.get("nearest_mrt_name"):
            st.caption(
                f"Nearest MRT: {geo_info.get('nearest_mrt_name')} "
                f"{geo_info.get('nearest_mrt_exit') or ''} · "
                f"{geo_info.get('nearest_mrt_distance_m') or 0:.0f} m straight-line"
            )
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("**Sale comps**")
            dataframe(
                brief["sale_comps"]["comps"],
                {
                    "contract_date": "Contract",
                    "project": "Project",
                    "tenure_type": "Tenure",
                    "price": "Price",
                    "area_sqft": "Land sqft",
                    "psf": "Land psf",
                },
            )
        with col_b:
            st.markdown("**Rent comps**")
            dataframe(
                brief["rent_comps"]["comps"],
                {
                    "lease_date": "Lease",
                    "project": "Project",
                    "rent_monthly": "Rent",
                    "area_sqft_mid": "Sqft",
                    "area_band": "Area band",
                },
            )
        st.markdown("**Planning signals**")
        dataframe(brief["planning_signals"])
        with st.expander("INLIS due diligence checklist"):
            st.json(brief["checklist"])
        with st.expander("INLIS 尽调记录"):
            dataframe(
                brief["due_diligence"],
                {
                    "product": "Product",
                    "result": "Result",
                    "checked_at": "Checked",
                    "file_path": "File",
                },
            )
            with st.form("due_diligence_form", clear_on_submit=True):
                dd_product = st.selectbox(
                    "Product",
                    [item["code"] for item in brief["checklist"]["products"]] + ["OTHER"],
                )
                dd_result = st.text_area("Result", height=80)
                dd_date = st.date_input("Checked date")
                dd_file = st.text_input("File path（可空）")
                dd_submit = st.form_submit_button("记录尽调结果")
            if dd_submit and dd_result.strip():
                conn = db.connect()
                try:
                    comps.due_diligence_add(
                        conn,
                        watchlist_id=watchlist_id,
                        product=dd_product,
                        result=dd_result.strip(),
                        checked_at=dd_date.isoformat(),
                        file_path=dd_file.strip() or None,
                    )
                finally:
                    conn.close()
                st.success("已记录")
                st.rerun()
    else:
        st.info("还没有 watchlist。先加一套正在看的房。")

with tab_planning:
    st.subheader("规划信号")
    st.caption("Planning Decisions 是已批/已拒的 Written Permission；适合找重建、分割、合并活跃街道。")
    col1, col2 = st.columns(2)
    with col1:
        planning_street = st.text_input("Street（可空）", key="planning_street")
    with col2:
        planning_months = st.selectbox("最近几个月", [6, 12, 24, 36], index=1, key="planning_months")
    catalyst_only = st.checkbox("只看重建 / 分割 / 合并相关", value=False)
    conn = db.connect()
    try:
        rows = comps.planning_signals(
            conn,
            street=planning_street.strip() or None,
            months=int(planning_months),
        )
    finally:
        conn.close()
    if catalyst_only:
        rows = [row for row in rows if row.get("is_catalyst")]
    st.caption(f"{len(rows)} 条规划决定")
    dataframe(
        rows,
        {
            "decision_date": "Decision date",
            "street": "Street",
            "address": "Address",
            "appl_type": "Application type",
            "submission_desc": "Description",
            "mkts_lotno": "Lot",
            "is_catalyst": "Catalyst",
        },
    )
