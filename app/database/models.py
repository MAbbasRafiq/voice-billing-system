"""SQLite table definitions."""

ITEMS_TABLE = """
CREATE TABLE IF NOT EXISTS items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    item_code   TEXT NOT NULL,
    model       TEXT,
    name        TEXT NOT NULL,
    urdu_name   TEXT,
    category    TEXT,
    ctn_qty     INTEGER,
    cp          REAL NOT NULL,
    foc_qty     INTEGER,
    foc_units   INTEGER,
    qrc_runs    INTEGER
);
"""

BILLS_TABLE = """
CREATE TABLE IF NOT EXISTS bills (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at   TEXT DEFAULT (datetime('now')),
    customer     TEXT,
    total        REAL,
    pdf_path     TEXT
);
"""

BILL_ITEMS_TABLE = """
CREATE TABLE IF NOT EXISTS bill_items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_id      INTEGER REFERENCES bills(id),
    item_id      INTEGER REFERENCES items(id),
    qty          INTEGER,
    unit_price   REAL,
    line_total   REAL,
    is_foc       INTEGER DEFAULT 0
);
"""

IMPORT_LOG_TABLE = """
CREATE TABLE IF NOT EXISTS import_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    imported_at     TEXT DEFAULT (datetime('now')),
    file_modified   TEXT,
    item_count      INTEGER
);
"""

ALL_TABLES = [ITEMS_TABLE, BILLS_TABLE, BILL_ITEMS_TABLE, IMPORT_LOG_TABLE]
