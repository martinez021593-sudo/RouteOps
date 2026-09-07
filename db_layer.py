import os
import re
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATABASE_URL = (os.environ.get("DATABASE_URL") or "").strip()
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://"):]

IS_POSTGRES = DATABASE_URL.startswith("postgresql://") or DATABASE_URL.startswith("postgresql+psycopg://")
SQLITE_PATH = Path(os.environ.get("SQLITE_PATH") or (BASE_DIR / "routeops_v030.db"))

try:
    import psycopg
    from psycopg.rows import dict_row
    PSYCOPG_INTEGRITY = (psycopg.IntegrityError,)
except Exception:
    psycopg = None
    dict_row = None
    PSYCOPG_INTEGRITY = tuple()

INTEGRITY_ERRORS = (sqlite3.IntegrityError,) + PSYCOPG_INTEGRITY


def database_backend():
    return "postgresql" if IS_POSTGRES else "sqlite"


def _translate_postgres(sql: str) -> str:
    # SQLite counts booleans as 0/1. PostgreSQL requires CASE expressions.
    sql = re.sub(
        r"SUM\(\s*([A-Za-z_][\w.]*)\s*=\s*'([^']*)'\s*\)",
        r"SUM(CASE WHEN \1='\2' THEN 1 ELSE 0 END)", sql, flags=re.I,
    )
    sql = re.sub(
        r"SUM\(\s*([A-Za-z_][\w.]*)\s+IS\s+NOT\s+NULL\s+AND\s+([A-Za-z_][\w.]*)\s+IS\s+NOT\s+NULL\s*\)",
        r"SUM(CASE WHEN \1 IS NOT NULL AND \2 IS NOT NULL THEN 1 ELSE 0 END)", sql, flags=re.I,
    )
    sql = re.sub(
        r"SUM\(\s*([A-Za-z_][\w.]*)\s+IS\s+NULL\s+OR\s+([A-Za-z_][\w.]*)\s+IS\s+NULL\s*\)",
        r"SUM(CASE WHEN \1 IS NULL OR \2 IS NULL THEN 1 ELSE 0 END)", sql, flags=re.I,
    )
    sql = sql.replace("?", "%s")
    return sql


class CursorResult:
    def __init__(self, cursor, *, prefetched=None, lastrowid=None):
        self.cursor = cursor
        self._prefetched = prefetched
        self.lastrowid = lastrowid

    def fetchone(self):
        if self._prefetched is not None:
            row = self._prefetched
            self._prefetched = None
            return row
        return self.cursor.fetchone()

    def fetchall(self):
        rows = []
        if self._prefetched is not None:
            rows.append(self._prefetched)
            self._prefetched = None
        rows.extend(self.cursor.fetchall())
        return rows

    def __iter__(self):
        if self._prefetched is not None:
            yield self._prefetched
            self._prefetched = None
        yield from self.cursor


class DBConnection:
    def __init__(self):
        self.backend = database_backend()
        if self.backend == "postgresql":
            if psycopg is None:
                raise RuntimeError("DATABASE_URL is PostgreSQL but psycopg is not installed.")
            self.conn = psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=False)
        else:
            self.conn = sqlite3.connect(SQLITE_PATH, timeout=30)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA foreign_keys = ON")
            self.conn.execute("PRAGMA journal_mode = WAL")

    def execute(self, sql, params=()):
        params = tuple(params or ())
        if self.backend == "postgresql":
            q = _translate_postgres(sql)
            cur = self.conn.cursor()
            is_insert = bool(re.match(r"^\s*INSERT\s+INTO\s+", q, flags=re.I))
            # Return generated id so existing V0.2.1 code can continue using lastrowid.
            if is_insert and not re.search(r"\bRETURNING\b", q, flags=re.I):
                q = q.rstrip().rstrip(";") + " RETURNING id"
                cur.execute(q, params)
                row = cur.fetchone()
                last_id = row["id"] if isinstance(row, dict) else row[0]
                return CursorResult(cur, lastrowid=last_id)
            cur.execute(q, params)
            return CursorResult(cur)
        cur = self.conn.execute(sql, params)
        return CursorResult(cur, lastrowid=cur.lastrowid)

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        self.conn.close()


def get_db():
    return DBConnection()


SQLITE_SCHEMA = r"""
CREATE TABLE IF NOT EXISTS organizations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    timezone TEXT NOT NULL DEFAULT 'Europe/Madrid',
    currency TEXT NOT NULL DEFAULT 'EUR',
    depot_lat REAL,
    depot_lon REAL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS drivers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    pay_per_delivery REAL NOT NULL DEFAULT 0.85,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    FOREIGN KEY(organization_id) REFERENCES organizations(id)
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL,
    email TEXT,
    username TEXT,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin','driver')),
    driver_id INTEGER,
    UNIQUE(organization_id, email),
    UNIQUE(organization_id, username),
    FOREIGN KEY(organization_id) REFERENCES organizations(id),
    FOREIGN KEY(driver_id) REFERENCES drivers(id)
);
CREATE TABLE IF NOT EXISTS work_days (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL,
    work_date TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'planning' CHECK(status IN ('planning','active','closed')),
    created_at TEXT NOT NULL,
    activated_at TEXT,
    closed_at TEXT,
    UNIQUE(organization_id, work_date, name),
    FOREIGN KEY(organization_id) REFERENCES organizations(id)
);
CREATE TABLE IF NOT EXISTS packages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL,
    work_day_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    barcode TEXT,
    carrier TEXT,
    tracking_code TEXT,
    postal_code TEXT,
    city TEXT,
    route_zone TEXT,
    route_code TEXT,
    weight_kg REAL,
    quantity INTEGER DEFAULT 1,
    intake_source TEXT,
    intake_driver_id INTEGER,
    intake_scanned_at TEXT,
    intake_confidence REAL,
    intake_status TEXT DEFAULT 'legacy',
    raw_scan_code TEXT,
    delivered_by_driver_id INTEGER,
    tracking_source TEXT,
    ocr_confidence REAL,
    ocr_passes INTEGER DEFAULT 0,
    intake_job_id INTEGER,
    recipient_name TEXT,
    phone TEXT,
    address TEXT NOT NULL,
    lat REAL,
    lon REAL,
    driver_id INTEGER,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','delivered','failed')),
    sequence INTEGER,
    created_at TEXT NOT NULL,
    delivered_at TEXT,
    failure_reason TEXT,
    proof_photo TEXT,
    proof_image BLOB,
    proof_mime TEXT,
    proof_filename TEXT,
    delivery_lat REAL,
    delivery_lon REAL,
    delivery_accuracy REAL,
    notes TEXT,
    UNIQUE(work_day_id, code),
    FOREIGN KEY(organization_id) REFERENCES organizations(id),
    FOREIGN KEY(work_day_id) REFERENCES work_days(id),
    FOREIGN KEY(driver_id) REFERENCES drivers(id)
);
CREATE TABLE IF NOT EXISTS route_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL,
    work_day_id INTEGER NOT NULL,
    driver_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT 'local',
    total_distance_km REAL DEFAULT 0,
    estimated_minutes INTEGER DEFAULT 0,
    stop_count INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'published',
    provider_note TEXT,
    FOREIGN KEY(organization_id) REFERENCES organizations(id),
    FOREIGN KEY(work_day_id) REFERENCES work_days(id),
    FOREIGN KEY(driver_id) REFERENCES drivers(id)
);
CREATE TABLE IF NOT EXISTS settlements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL,
    work_day_id INTEGER NOT NULL,
    driver_id INTEGER NOT NULL,
    delivered_count INTEGER NOT NULL DEFAULT 0,
    amount REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    paid_at TEXT,
    UNIQUE(work_day_id, driver_id),
    FOREIGN KEY(organization_id) REFERENCES organizations(id),
    FOREIGN KEY(work_day_id) REFERENCES work_days(id),
    FOREIGN KEY(driver_id) REFERENCES drivers(id)
);
CREATE TABLE IF NOT EXISTS location_updates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL,
    work_day_id INTEGER NOT NULL,
    driver_id INTEGER NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    accuracy REAL,
    speed REAL,
    heading REAL,
    captured_at TEXT NOT NULL,
    FOREIGN KEY(organization_id) REFERENCES organizations(id),
    FOREIGN KEY(work_day_id) REFERENCES work_days(id),
    FOREIGN KEY(driver_id) REFERENCES drivers(id)
);
CREATE TABLE IF NOT EXISTS scan_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL,
    work_day_id INTEGER NOT NULL,
    driver_id INTEGER,
    raw_code TEXT NOT NULL,
    package_id INTEGER,
    scan_type TEXT NOT NULL DEFAULT 'lookup',
    captured_at TEXT NOT NULL,
    FOREIGN KEY(organization_id) REFERENCES organizations(id),
    FOREIGN KEY(work_day_id) REFERENCES work_days(id),
    FOREIGN KEY(driver_id) REFERENCES drivers(id),
    FOREIGN KEY(package_id) REFERENCES packages(id)
);

CREATE TABLE IF NOT EXISTS intake_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL,
    work_day_id INTEGER NOT NULL,
    driver_id INTEGER NOT NULL,
    package_id INTEGER,
    carrier TEXT,
    source TEXT NOT NULL DEFAULT 'camera',
    confidence REAL,
    status TEXT,
    captured_at TEXT NOT NULL,
    FOREIGN KEY(organization_id) REFERENCES organizations(id),
    FOREIGN KEY(work_day_id) REFERENCES work_days(id),
    FOREIGN KEY(driver_id) REFERENCES drivers(id),
    FOREIGN KEY(package_id) REFERENCES packages(id)
);

CREATE TABLE IF NOT EXISTS intake_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL,
    work_day_id INTEGER NOT NULL,
    driver_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    raw_codes TEXT,
    carrier_hint TEXT,
    image_data BLOB,
    image_mime TEXT,
    image_size INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    package_id INTEGER,
    result_json TEXT,
    error_text TEXT,
    attempts INTEGER DEFAULT 0,
    FOREIGN KEY(organization_id) REFERENCES organizations(id),
    FOREIGN KEY(work_day_id) REFERENCES work_days(id),
    FOREIGN KEY(driver_id) REFERENCES drivers(id),
    FOREIGN KEY(package_id) REFERENCES packages(id)
);
CREATE INDEX IF NOT EXISTS idx_intake_jobs_driver_day ON intake_jobs(work_day_id,driver_id,id);
CREATE INDEX IF NOT EXISTS idx_intake_jobs_status ON intake_jobs(status,id);
CREATE INDEX IF NOT EXISTS idx_packages_workday ON packages(work_day_id);
CREATE INDEX IF NOT EXISTS idx_packages_driver_day ON packages(work_day_id, driver_id);
CREATE INDEX IF NOT EXISTS idx_packages_barcode ON packages(work_day_id, barcode);
CREATE INDEX IF NOT EXISTS idx_locations_driver_day ON location_updates(work_day_id, driver_id, id);
"""

POSTGRES_SCHEMA = r"""
CREATE TABLE IF NOT EXISTS organizations (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    timezone TEXT NOT NULL DEFAULT 'Europe/Madrid',
    currency TEXT NOT NULL DEFAULT 'EUR',
    depot_lat DOUBLE PRECISION,
    depot_lon DOUBLE PRECISION,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS drivers (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL REFERENCES organizations(id),
    name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    pay_per_delivery DOUBLE PRECISION NOT NULL DEFAULT 0.85,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL REFERENCES organizations(id),
    email TEXT,
    username TEXT,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin','driver')),
    driver_id BIGINT REFERENCES drivers(id),
    UNIQUE(organization_id, email),
    UNIQUE(organization_id, username)
);
CREATE TABLE IF NOT EXISTS work_days (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL REFERENCES organizations(id),
    work_date TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'planning' CHECK(status IN ('planning','active','closed')),
    created_at TEXT NOT NULL,
    activated_at TEXT,
    closed_at TEXT,
    UNIQUE(organization_id, work_date, name)
);
CREATE TABLE IF NOT EXISTS packages (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL REFERENCES organizations(id),
    work_day_id BIGINT NOT NULL REFERENCES work_days(id),
    code TEXT NOT NULL,
    barcode TEXT,
    carrier TEXT,
    tracking_code TEXT,
    postal_code TEXT,
    city TEXT,
    route_zone TEXT,
    route_code TEXT,
    weight_kg DOUBLE PRECISION,
    quantity INTEGER DEFAULT 1,
    intake_source TEXT,
    intake_driver_id BIGINT REFERENCES drivers(id),
    intake_scanned_at TEXT,
    intake_confidence DOUBLE PRECISION,
    intake_status TEXT DEFAULT 'legacy',
    raw_scan_code TEXT,
    delivered_by_driver_id BIGINT REFERENCES drivers(id),
    tracking_source TEXT,
    ocr_confidence DOUBLE PRECISION,
    ocr_passes INTEGER DEFAULT 0,
    intake_job_id BIGINT,
    recipient_name TEXT,
    phone TEXT,
    address TEXT NOT NULL,
    lat DOUBLE PRECISION,
    lon DOUBLE PRECISION,
    driver_id BIGINT REFERENCES drivers(id),
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','delivered','failed')),
    sequence INTEGER,
    created_at TEXT NOT NULL,
    delivered_at TEXT,
    failure_reason TEXT,
    proof_photo TEXT,
    proof_image BYTEA,
    proof_mime TEXT,
    proof_filename TEXT,
    delivery_lat DOUBLE PRECISION,
    delivery_lon DOUBLE PRECISION,
    delivery_accuracy DOUBLE PRECISION,
    notes TEXT,
    UNIQUE(work_day_id, code)
);
CREATE TABLE IF NOT EXISTS route_runs (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL REFERENCES organizations(id),
    work_day_id BIGINT NOT NULL REFERENCES work_days(id),
    driver_id BIGINT NOT NULL REFERENCES drivers(id),
    created_at TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT 'local',
    total_distance_km DOUBLE PRECISION DEFAULT 0,
    estimated_minutes INTEGER DEFAULT 0,
    stop_count INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'published',
    provider_note TEXT
);
CREATE TABLE IF NOT EXISTS settlements (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL REFERENCES organizations(id),
    work_day_id BIGINT NOT NULL REFERENCES work_days(id),
    driver_id BIGINT NOT NULL REFERENCES drivers(id),
    delivered_count INTEGER NOT NULL DEFAULT 0,
    amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    paid_at TEXT,
    UNIQUE(work_day_id, driver_id)
);
CREATE TABLE IF NOT EXISTS location_updates (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL REFERENCES organizations(id),
    work_day_id BIGINT NOT NULL REFERENCES work_days(id),
    driver_id BIGINT NOT NULL REFERENCES drivers(id),
    lat DOUBLE PRECISION NOT NULL,
    lon DOUBLE PRECISION NOT NULL,
    accuracy DOUBLE PRECISION,
    speed DOUBLE PRECISION,
    heading DOUBLE PRECISION,
    captured_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scan_events (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL REFERENCES organizations(id),
    work_day_id BIGINT NOT NULL REFERENCES work_days(id),
    driver_id BIGINT REFERENCES drivers(id),
    raw_code TEXT NOT NULL,
    package_id BIGINT REFERENCES packages(id),
    scan_type TEXT NOT NULL DEFAULT 'lookup',
    captured_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS intake_events (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL REFERENCES organizations(id),
    work_day_id BIGINT NOT NULL REFERENCES work_days(id),
    driver_id BIGINT NOT NULL REFERENCES drivers(id),
    package_id BIGINT REFERENCES packages(id),
    carrier TEXT,
    source TEXT NOT NULL DEFAULT 'camera',
    confidence DOUBLE PRECISION,
    status TEXT,
    captured_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS intake_jobs (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL REFERENCES organizations(id),
    work_day_id BIGINT NOT NULL REFERENCES work_days(id),
    driver_id BIGINT NOT NULL REFERENCES drivers(id),
    status TEXT NOT NULL DEFAULT 'queued',
    raw_codes TEXT,
    carrier_hint TEXT,
    image_data BYTEA,
    image_mime TEXT,
    image_size INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    package_id BIGINT REFERENCES packages(id),
    result_json TEXT,
    error_text TEXT,
    attempts INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_intake_jobs_driver_day ON intake_jobs(work_day_id,driver_id,id);
CREATE INDEX IF NOT EXISTS idx_intake_jobs_status ON intake_jobs(status,id);
CREATE INDEX IF NOT EXISTS idx_packages_workday ON packages(work_day_id);
CREATE INDEX IF NOT EXISTS idx_packages_driver_day ON packages(work_day_id, driver_id);
CREATE INDEX IF NOT EXISTS idx_packages_barcode ON packages(work_day_id, barcode);
CREATE INDEX IF NOT EXISTS idx_locations_driver_day ON location_updates(work_day_id, driver_id, id);
"""



PACKAGE_EXTRA_COLUMNS = {
    "carrier": "TEXT",
    "tracking_code": "TEXT",
    "postal_code": "TEXT",
    "city": "TEXT",
    "route_zone": "TEXT",
    "route_code": "TEXT",
    "weight_kg": "DOUBLE PRECISION",
    "quantity": "INTEGER DEFAULT 1",
    "intake_source": "TEXT",
    "intake_driver_id": "BIGINT",
    "intake_scanned_at": "TEXT",
    "intake_confidence": "DOUBLE PRECISION",
    "intake_status": "TEXT DEFAULT 'legacy'",
    "raw_scan_code": "TEXT",
    "delivered_by_driver_id": "BIGINT",
    "tracking_source": "TEXT",
    "ocr_confidence": "DOUBLE PRECISION",
    "ocr_passes": "INTEGER DEFAULT 0",
    "intake_job_id": "BIGINT",
}

def ensure_package_columns(db):
    if db.backend == "postgresql":
        for name, typ in PACKAGE_EXTRA_COLUMNS.items():
            db.execute(f"ALTER TABLE packages ADD COLUMN IF NOT EXISTS {name} {typ}")
        db.commit()
        return
    existing = {row["name"] for row in db.execute("PRAGMA table_info(packages)").fetchall()}
    sqlite_types = {
        "carrier": "TEXT", "tracking_code": "TEXT", "postal_code": "TEXT", "city": "TEXT",
        "route_zone": "TEXT", "route_code": "TEXT", "weight_kg": "REAL", "quantity": "INTEGER DEFAULT 1",
        "intake_source": "TEXT", "intake_driver_id": "INTEGER", "intake_scanned_at": "TEXT",
        "intake_confidence": "REAL", "intake_status": "TEXT DEFAULT 'legacy'", "raw_scan_code": "TEXT",
        "delivered_by_driver_id": "INTEGER",
        "tracking_source": "TEXT",
        "ocr_confidence": "REAL",
        "ocr_passes": "INTEGER DEFAULT 0",
        "intake_job_id": "INTEGER"
    }
    for name, typ in sqlite_types.items():
        if name not in existing:
            db.execute(f"ALTER TABLE packages ADD COLUMN {name} {typ}")
    db.commit()

def init_schema(db=None):
    owns = db is None
    db = db or get_db()
    script = POSTGRES_SCHEMA if db.backend == "postgresql" else SQLITE_SCHEMA
    if db.backend == "postgresql":
        # psycopg accepts multi-statement SQL in a single execute in simple query mode,
        # but splitting is more portable and makes failures easier to locate.
        for statement in [x.strip() for x in script.split(";") if x.strip()]:
            db.execute(statement)
    else:
        db.conn.executescript(script)
    db.commit()
    ensure_package_columns(db)
    if owns:
        db.close()
