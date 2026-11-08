from property_hunt import comps, config, db, ingest


def test_demo_pipeline(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    monkeypatch.setattr(config, "RAW_DIR", raw_dir)

    conn = db.connect(tmp_path / "test.db")
    try:
        db.init_db(conn)
        counts = ingest.ingest_demo(conn)
        assert counts["transactions"] > 0
        assert counts["rentals"] > 0
        assert counts["planning"] > 0

        street_rows = comps.refresh_street_stats(conn)
        assert street_rows > 0

        sale = comps.get_sale_comps(conn, "JALAN BERJAYA", "SEMI_D")
        assert sale["stats"]["count"] >= 5
        assert sale["stats"]["median_psf"] > 0

        rent = comps.get_rent_comps(conn, "JALAN BERJAYA", "SEMI_D")
        assert rent["stats"]["count"] >= 5

        gaps = comps.value_gaps(conn, discount_threshold=0.05)
        assert len(gaps) > 0

        item = comps.watchlist_add(
            conn,
            address="15 JALAN BERJAYA",
            property_type="SEMI_D",
            asking_price=6_500_000,
            land_sqft=4_000,
            built_up_sqft=3_500,
            monthly_rent=7_500,
            tenure_type="FREEHOLD",
        )
        brief = comps.property_brief(conn, item["id"])
        assert brief["metrics"]["gross_yield_pct"] > 0
        assert brief["sale_comps"]["stats"]["count"] >= 5
        assert brief["checklist"]["products"]
    finally:
        conn.close()
