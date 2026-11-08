PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS ura_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_hash TEXT NOT NULL UNIQUE,
    project TEXT,
    street TEXT NOT NULL,
    street_key TEXT NOT NULL,
    property_type TEXT NOT NULL,
    district TEXT,
    market_segment TEXT,
    tenure_raw TEXT,
    tenure_type TEXT,
    lease_start_year INTEGER,
    sale_type TEXT,
    contract_date TEXT,
    contract_month TEXT,
    price INTEGER,
    nett_price INTEGER,
    area_sqm REAL,
    area_sqft REAL,
    area_basis TEXT,
    area_band TEXT,
    psf REAL,
    floor_range TEXT,
    no_of_units INTEGER,
    x_svy21 REAL,
    y_svy21 REAL,
    ingested_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tx_street
    ON ura_transactions(street_key, property_type, contract_date);
CREATE INDEX IF NOT EXISTS idx_tx_contract
    ON ura_transactions(contract_date);
CREATE INDEX IF NOT EXISTS idx_tx_district
    ON ura_transactions(district, property_type, contract_date);

CREATE TABLE IF NOT EXISTS ura_rentals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_hash TEXT NOT NULL UNIQUE,
    project TEXT,
    street TEXT NOT NULL,
    street_key TEXT NOT NULL,
    property_type TEXT NOT NULL,
    district TEXT,
    lease_date TEXT,
    lease_month TEXT,
    rent_monthly REAL,
    area_sqft_low REAL,
    area_sqft_high REAL,
    area_sqft_mid REAL,
    area_sqm_low REAL,
    area_sqm_high REAL,
    area_band TEXT,
    bedrooms INTEGER,
    x_svy21 REAL,
    y_svy21 REAL,
    ingested_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_rent_street
    ON ura_rentals(street_key, property_type, lease_date);
CREATE INDEX IF NOT EXISTS idx_rent_lease
    ON ura_rentals(lease_date);

CREATE TABLE IF NOT EXISTS ura_planning (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_no TEXT NOT NULL,
    decision_no TEXT NOT NULL,
    dr_id TEXT,
    address TEXT NOT NULL,
    street TEXT,
    street_key TEXT,
    submission_desc TEXT,
    appl_type TEXT,
    decision_type TEXT,
    decision_date TEXT,
    mkts_lotno TEXT,
    delete_ind TEXT DEFAULT 'No',
    ingested_at TEXT NOT NULL,
    UNIQUE(submission_no, decision_no)
);

CREATE INDEX IF NOT EXISTS idx_planning_street
    ON ura_planning(street_key, decision_date);
CREATE INDEX IF NOT EXISTS idx_planning_date
    ON ura_planning(decision_date);
CREATE INDEX IF NOT EXISTS idx_planning_lot
    ON ura_planning(mkts_lotno);

CREATE TABLE IF NOT EXISTS market_indices (
    series TEXT NOT NULL,
    property_type TEXT NOT NULL,
    quarter TEXT NOT NULL,
    index_value REAL,
    PRIMARY KEY (series, property_type, quarter)
);

CREATE TABLE IF NOT EXISTS geo_layers (
    key TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL,
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    feature_count INTEGER,
    downloaded_at TEXT NOT NULL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS street_stats (
    street_key TEXT NOT NULL,
    street TEXT NOT NULL,
    district TEXT,
    property_type TEXT NOT NULL,
    tenure_type TEXT NOT NULL,
    area_band TEXT NOT NULL,
    lease_start_year INTEGER,
    remaining_lease_years INTEGER,
    lu_desc TEXT,
    gpr TEXT,
    height_control TEXT,
    lha_class TEXT,
    lha_name TEXT,
    lha_type TEXT,
    conservation_area TEXT,
    cadastral_lot TEXT,
    nearest_mrt_name TEXT,
    nearest_mrt_exit TEXT,
    nearest_mrt_distance_m REAL,
    geo_updated_at TEXT,
    sale_count_36m INTEGER NOT NULL DEFAULT 0,
    sale_count_12m INTEGER NOT NULL DEFAULT 0,
    sale_median_price REAL,
    sale_median_psf REAL,
    sale_p25_psf REAL,
    sale_p75_psf REAL,
    sale_last_date TEXT,
    rent_count_24m INTEGER NOT NULL DEFAULT 0,
    rent_count_12m INTEGER NOT NULL DEFAULT 0,
    rent_median REAL,
    rent_median_psf REAL,
    rent_last_date TEXT,
    gross_yield_pct REAL,
    liquidity_score REAL,
    confidence TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (street_key, property_type, tenure_type, area_band)
);

CREATE TABLE IF NOT EXISTS watchlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    address TEXT NOT NULL,
    house_no TEXT,
    street TEXT,
    street_key TEXT,
    property_type TEXT,
    tenure_type TEXT,
    lease_start_year INTEGER,
    land_sqft REAL,
    built_up_sqft REAL,
    asking_price REAL,
    monthly_rent REAL,
    status TEXT NOT NULL DEFAULT 'watching',
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS due_diligence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    watchlist_id INTEGER NOT NULL,
    product TEXT NOT NULL,
    result TEXT,
    checked_at TEXT NOT NULL,
    file_path TEXT,
    FOREIGN KEY (watchlist_id) REFERENCES watchlist(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    rows INTEGER DEFAULT 0,
    error TEXT
);
