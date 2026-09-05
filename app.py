
import csv
import io
import json
import math
import os
import secrets
import sqlite3
from datetime import datetime, date, time, timezone
from functools import wraps
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from flask import (
    Flask, Response, abort, flash, jsonify, redirect, render_template,
    request, send_from_directory, session, url_for
)
from openpyxl import load_workbook
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from lan_utils import get_lan_ip, qr_png_bytes

BASE_DIR = Path(__file__).resolve().parent


def load_env_file():
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


load_env_file()

DATA_DIR = Path(os.environ.get("ROUTEOPS_DATA_DIR", str(BASE_DIR))).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "routeops_v03.db"
UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
TIMEZONE_NAME = os.environ.get("ROUTEOPS_TIMEZONE", "Europe/Madrid")
try:
    APP_TZ = ZoneInfo(TIMEZONE_NAME)
except Exception:
    APP_TZ = timezone.utc

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "routeops-v03-local-" + secrets.token_hex(16))
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
if os.environ.get("ROUTEOPS_SECURE_COOKIES", "0") == "1":
    app.config["SESSION_COOKIE_SECURE"] = True
ALLOWED_IMAGE_EXT = {"png", "jpg", "jpeg", "webp"}


def now_local():
    return datetime.now(APP_TZ)


def now_iso():
    return now_local().isoformat(timespec="seconds")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db():
    db = get_db()
    db.executescript(
        """
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
            status TEXT NOT NULL DEFAULT 'planning'
                CHECK(status IN ('planning','active','closed')),
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
            recipient_name TEXT,
            phone TEXT,
            address TEXT NOT NULL,
            origin_country TEXT,
            carrier TEXT,
            zone TEXT,
            package_type TEXT,
            weight_kg REAL,
            priority TEXT NOT NULL DEFAULT 'normal',
            special_characteristics TEXT,
            lat REAL,
            lon REAL,
            driver_id INTEGER,
            assigned_by TEXT,
            dispatch_rule_id INTEGER,
            dispatch_reason TEXT,
            classification_status TEXT NOT NULL DEFAULT 'unreviewed',
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending','delivered','failed')),
            sequence INTEGER,
            created_at TEXT NOT NULL,
            delivered_at TEXT,
            failure_reason TEXT,
            proof_photo TEXT,
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

        CREATE TABLE IF NOT EXISTS dispatch_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            organization_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            origin_country TEXT,
            carrier TEXT,
            zone TEXT,
            package_type TEXT,
            min_weight_kg REAL,
            max_weight_kg REAL,
            priority_value TEXT,
            characteristic_contains TEXT,
            target_driver_id INTEGER NOT NULL,
            rule_priority INTEGER NOT NULL DEFAULT 100,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            FOREIGN KEY(organization_id) REFERENCES organizations(id),
            FOREIGN KEY(target_driver_id) REFERENCES drivers(id)
        );

        CREATE TABLE IF NOT EXISTS dispatch_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            organization_id INTEGER NOT NULL,
            work_day_id INTEGER NOT NULL,
            package_id INTEGER NOT NULL,
            previous_driver_id INTEGER,
            new_driver_id INTEGER,
            assignment_source TEXT NOT NULL,
            dispatch_rule_id INTEGER,
            reason TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(organization_id) REFERENCES organizations(id),
            FOREIGN KEY(work_day_id) REFERENCES work_days(id),
            FOREIGN KEY(package_id) REFERENCES packages(id),
            FOREIGN KEY(previous_driver_id) REFERENCES drivers(id),
            FOREIGN KEY(new_driver_id) REFERENCES drivers(id),
            FOREIGN KEY(dispatch_rule_id) REFERENCES dispatch_rules(id)
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

        CREATE INDEX IF NOT EXISTS idx_packages_workday ON packages(work_day_id);
        CREATE INDEX IF NOT EXISTS idx_packages_driver_day ON packages(work_day_id, driver_id);
        CREATE INDEX IF NOT EXISTS idx_packages_barcode ON packages(work_day_id, barcode);
        CREATE INDEX IF NOT EXISTS idx_locations_driver_day ON location_updates(work_day_id, driver_id, id);
        CREATE INDEX IF NOT EXISTS idx_dispatch_rules_org ON dispatch_rules(organization_id, active, rule_priority);
        CREATE INDEX IF NOT EXISTS idx_dispatch_history_day ON dispatch_history(work_day_id, package_id);
        """
    )

    if db.execute("SELECT COUNT(*) c FROM organizations").fetchone()["c"] == 0:
        depot_lat = _float_env("DEPOT_LAT")
        depot_lon = _float_env("DEPOT_LON")
        db.execute(
            "INSERT INTO organizations(name,timezone,currency,depot_lat,depot_lon,created_at) VALUES(?,?,?,?,?,?)",
            ("RouteOps Demo", TIMEZONE_NAME, "EUR", depot_lat, depot_lon, now_iso())
        )
        db.commit()

    org_id = db.execute("SELECT id FROM organizations ORDER BY id LIMIT 1").fetchone()["id"]

    if db.execute("SELECT COUNT(*) c FROM drivers").fetchone()["c"] == 0:
        for name in ("Carlos", "Juan", "Miguel"):
            db.execute(
                "INSERT INTO drivers(organization_id,name,email,pay_per_delivery,created_at) VALUES(?,?,?,?,?)",
                (org_id, name, f"{name.lower()}@routeops.local", 0.85, now_iso())
            )
        db.commit()

    if db.execute("SELECT COUNT(*) c FROM users").fetchone()["c"] == 0:
        db.execute(
            "INSERT INTO users(organization_id,email,username,password_hash,role) VALUES(?,?,?,?,?)",
            (org_id, "admin@routeops.local", "admin", generate_password_hash("demo123"), "admin")
        )
        for d in db.execute("SELECT * FROM drivers WHERE organization_id=? ORDER BY id", (org_id,)):
            db.execute(
                "INSERT INTO users(organization_id,email,username,password_hash,role,driver_id) VALUES(?,?,?,?,?,?)",
                (org_id, d["email"], d["name"].lower(), generate_password_hash("1234"), "driver", d["id"])
            )
        db.commit()

    today_s = date.today().isoformat()
    wd = db.execute(
        "SELECT * FROM work_days WHERE organization_id=? AND work_date=? ORDER BY id LIMIT 1",
        (org_id, today_s)
    ).fetchone()
    if not wd:
        cur = db.execute(
            "INSERT INTO work_days(organization_id,work_date,name,status,created_at,activated_at) VALUES(?,?,?,?,?,?)",
            (org_id, today_s, "Jornada Demo", "active", now_iso(), now_iso())
        )
        wd_id = cur.lastrowid
        seed_demo_packages(db, org_id, wd_id)
        db.commit()
    db.close()


def _float_env(key):
    val = os.environ.get(key, "").strip()
    try:
        return float(val) if val else None
    except Exception:
        return None


def seed_demo_packages(db, org_id, work_day_id):
    centers = {
        "Carlos": (40.4168, -3.7038),
        "Juan": (40.4380, -3.6900),
        "Miguel": (40.4010, -3.7150),
    }
    drivers = {r["name"]: r["id"] for r in db.execute(
        "SELECT * FROM drivers WHERE organization_id=?", (org_id,)
    )}
    profiles = {
        "Carlos": [("Alemania", "Empresa 1", "Centro", "estandar"), ("Francia", "Empresa 2", "Centro", "documento")],
        "Juan": [("Italia", "Empresa 3", "Norte", "estandar"), ("Portugal", "Empresa 2", "Norte", "fragil")],
        "Miguel": [("Países Bajos", "Empresa 1", "Sur", "estandar"), ("Bélgica", "Empresa 3", "Sur", "voluminoso")],
    }
    idx = 1
    for name, (clat, clon) in centers.items():
        for n in range(10):
            angle = (n / 10) * math.tau + drivers[name]
            radius = 0.007 + (n % 4) * 0.0022
            lat = clat + math.sin(angle) * radius
            lon = clon + math.cos(angle) * radius
            country, carrier, zone, ptype = profiles[name][n % len(profiles[name])]
            db.execute(
                """
                INSERT INTO packages(
                    organization_id,work_day_id,code,barcode,recipient_name,phone,address,
                    origin_country,carrier,zone,package_type,weight_kg,priority,special_characteristics,
                    lat,lon,driver_id,assigned_by,dispatch_reason,classification_status,status,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    org_id, work_day_id, f"PK{idx:05d}", f"843700{idx:06d}",
                    f"Cliente {idx}", "", f"Parada demo {idx}, Madrid",
                    country, carrier, zone, ptype, 1.0 + (n % 5) * 1.5,
                    "urgente" if n == 0 else "normal",
                    "manejo especial" if ptype in {"fragil", "voluminoso"} else "",
                    lat, lon, drivers[name], "seed", f"Demo preasignado a {name}", "reviewed",
                    "pending", now_iso()
                )
            )
            idx += 1

    # Reglas demo que ilustran el proceso real de clasificación antes del ruteo.
    if db.execute("SELECT COUNT(*) c FROM dispatch_rules WHERE organization_id=?", (org_id,)).fetchone()["c"] == 0:
        rules = [
            ("Empresa 1 → Carlos", None, "Empresa 1", None, None, None, None, None, None, drivers["Carlos"], 10),
            ("Empresa 3 / Norte → Juan", None, "Empresa 3", "Norte", None, None, None, None, None, drivers["Juan"], 20),
            ("Voluminosos → Miguel", None, None, None, "voluminoso", None, None, None, None, drivers["Miguel"], 30),
        ]
        for r in rules:
            db.execute(
                """INSERT INTO dispatch_rules(
                    organization_id,name,origin_country,carrier,zone,package_type,min_weight_kg,max_weight_kg,
                    priority_value,characteristic_contains,target_driver_id,rule_priority,active,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1,?)""",
                (org_id,*r,now_iso())
            )


def login_required(role=None):
    def deco(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not session.get("user_id"):
                return redirect(url_for("login"))
            if role and session.get("role") != role:
                flash("No tienes permisos para esa sección.", "error")
                return redirect(url_for("home"))
            return fn(*args, **kwargs)
        return wrapped
    return deco


def get_org_id():
    return int(session.get("organization_id") or 1)


def get_workday(db, work_day_id, org_id=None):
    org_id = org_id or get_org_id()
    row = db.execute(
        "SELECT * FROM work_days WHERE id=? AND organization_id=?",
        (work_day_id, org_id)
    ).fetchone()
    if not row:
        abort(404)
    return row


def active_workday_for_driver(db, org_id):
    return db.execute(
        """
        SELECT * FROM work_days
        WHERE organization_id=? AND status='active'
        ORDER BY CASE WHEN work_date=? THEN 0 ELSE 1 END, work_date DESC, id DESC
        LIMIT 1
        """,
        (org_id, date.today().isoformat())
    ).fetchone()


def haversine(a, b):
    lat1, lon1 = a
    lat2, lon2 = b
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    h = math.sin(dphi/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dlambda/2)**2
    return 2 * r * math.asin(math.sqrt(h))


def route_distance(points):
    return sum(haversine(points[i], points[i+1]) for i in range(len(points)-1)) if len(points) > 1 else 0


def nearest_neighbor_order(rows, start=None):
    valid = [dict(r) for r in rows if r["lat"] is not None and r["lon"] is not None]
    if not valid:
        return []
    current = start or (
        sum(r["lat"] for r in valid)/len(valid),
        sum(r["lon"] for r in valid)/len(valid)
    )
    remaining = valid[:]
    ordered = []
    while remaining:
        nxt = min(remaining, key=lambda r: haversine(current, (r["lat"], r["lon"])))
        ordered.append(nxt)
        current = (nxt["lat"], nxt["lon"])
        remaining.remove(nxt)

    improved = True
    loops = 0
    while improved and loops < 5 and len(ordered) < 220:
        improved = False
        loops += 1
        for i in range(1, len(ordered)-2):
            for j in range(i+1, min(len(ordered)-1, i+30)):
                a = (ordered[i-1]["lat"], ordered[i-1]["lon"])
                b = (ordered[i]["lat"], ordered[i]["lon"])
                c = (ordered[j]["lat"], ordered[j]["lon"])
                d = (ordered[j+1]["lat"], ordered[j+1]["lon"])
                if haversine(a,b)+haversine(c,d) > haversine(a,c)+haversine(b,d):
                    ordered[i:j+1] = list(reversed(ordered[i:j+1]))
                    improved = True
    return ordered


def parse_duration_seconds(value):
    if not value:
        return 0
    try:
        if isinstance(value, str) and value.endswith("s"):
            return float(value[:-1] or 0)
        return float(value)
    except Exception:
        return 0


def google_credentials():
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
    cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if not project or not cred_path:
        return None, "Falta GOOGLE_CLOUD_PROJECT o GOOGLE_APPLICATION_CREDENTIALS."
    path = Path(cred_path)
    if not path.is_absolute():
        path = BASE_DIR / path
    if not path.exists():
        return None, f"No existe el archivo de credenciales: {path}"
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request as GoogleAuthRequest
        creds = service_account.Credentials.from_service_account_file(
            str(path), scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        creds.refresh(GoogleAuthRequest())
        return (project, creds.token), None
    except Exception as exc:
        return None, f"Error OAuth Google: {exc}"


def google_route_optimize(rows, org, work_day):
    auth, err = google_credentials()
    if err:
        raise RuntimeError(err)
    project, token = auth

    valid = [dict(r) for r in rows if r["lat"] is not None and r["lon"] is not None]
    if not valid:
        raise RuntimeError("No hay paradas geocodificadas.")

    depot_lat = org["depot_lat"]
    depot_lon = org["depot_lon"]
    if depot_lat is None or depot_lon is None:
        depot_lat = sum(r["lat"] for r in valid) / len(valid)
        depot_lon = sum(r["lon"] for r in valid) / len(valid)

    tzname = org["timezone"] or TIMEZONE_NAME
    try:
        tz = ZoneInfo(tzname)
    except Exception:
        tz = APP_TZ

    d = date.fromisoformat(work_day["work_date"])
    start_local = datetime.combine(d, time(6, 0), tzinfo=tz)
    end_local = datetime.combine(d, time(23, 30), tzinfo=tz)
    start_utc = start_local.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    end_utc = end_local.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    shipments = []
    for r in valid:
        shipments.append({
            "deliveries": [{
                "arrivalWaypoint": {
                    "location": {
                        "latLng": {
                            "latitude": float(r["lat"]),
                            "longitude": float(r["lon"])
                        }
                    }
                },
                "duration": "180s"
            }],
            "label": r["code"]
        })

    waypoint = {
        "location": {
            "latLng": {"latitude": float(depot_lat), "longitude": float(depot_lon)}
        }
    }
    payload = {
        "timeout": "20s",
        "model": {
            "shipments": shipments,
            "vehicles": [{
                "startWaypoint": waypoint,
                "endWaypoint": waypoint,
                "costPerKilometer": 1.0,
                "startTimeWindows": [{"startTime": start_utc, "endTime": start_utc}],
                "endTimeWindows": [{"startTime": start_utc, "endTime": end_utc}]
            }],
            "globalStartTime": start_utc,
            "globalEndTime": end_utc
        }
    }

    url = f"https://routeoptimization.googleapis.com/v1/projects/{project}:optimizeTours"
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload,
        timeout=70
    )
    if not resp.ok:
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text[:800]
        raise RuntimeError(f"Google Route Optimization HTTP {resp.status_code}: {detail}")

    data = resp.json()
    if data.get("skippedShipments"):
        skipped = len(data["skippedShipments"])
    else:
        skipped = 0
    routes = data.get("routes") or []
    if not routes:
        raise RuntimeError("Google no devolvió una ruta.")

    route = routes[0]
    visits = route.get("visits") or []
    ordered = []
    used = set()
    for visit in visits:
        # En entregas, isPickup=false puede omitirse en JSON.
        if visit.get("isPickup", False):
            continue
        idx = int(visit.get("shipmentIndex", 0))
        if 0 <= idx < len(valid) and idx not in used:
            ordered.append(valid[idx])
            used.add(idx)

    # Defensa: si Google omite visitas o devuelve alguna parada sin secuenciar, la añadimos al final.
    for idx, r in enumerate(valid):
        if idx not in used:
            ordered.append(r)

    metrics = route.get("metrics") or {}
    km = float(metrics.get("travelDistanceMeters") or 0) / 1000.0
    total_seconds = parse_duration_seconds(metrics.get("totalDuration"))
    mins = max(1, int(round(total_seconds / 60))) if total_seconds else 0
    note = f"Google Route Optimization · {len(ordered)} visitas"
    if skipped:
        note += f" · {skipped} omitidas por Google"
    return ordered, km, mins, note


def optimize_driver_route(db, org, work_day, driver_id, provider):
    rows = db.execute(
        """
        SELECT * FROM packages
        WHERE work_day_id=? AND driver_id=? AND status IN ('pending','failed')
        ORDER BY id
        """,
        (work_day["id"], driver_id)
    ).fetchall()
    if not rows:
        raise RuntimeError("El repartidor no tiene paquetes pendientes.")

    geocoded = [r for r in rows if r["lat"] is not None and r["lon"] is not None]
    if not geocoded:
        raise RuntimeError("El repartidor no tiene paradas con coordenadas.")

    if provider == "google":
        ordered, km, mins, note = google_route_optimize(geocoded, org, work_day)
        provider_name = "google"
    else:
        start = None
        if org["depot_lat"] is not None and org["depot_lon"] is not None:
            start = (org["depot_lat"], org["depot_lon"])
        ordered = nearest_neighbor_order(geocoded, start=start)
        pts = []
        if start:
            pts.append(start)
        pts.extend((r["lat"], r["lon"]) for r in ordered)
        if start:
            pts.append(start)
        km = route_distance(pts)
        mins = int((km / 24) * 60 + len(ordered) * 3)
        note = "Local NN + 2-opt · distancia geográfica aproximada"
        provider_name = "local"

    for seq, r in enumerate(ordered, start=1):
        db.execute("UPDATE packages SET sequence=? WHERE id=?", (seq, r["id"]))

    db.execute(
        """
        INSERT INTO route_runs(
            organization_id,work_day_id,driver_id,created_at,provider,
            total_distance_km,estimated_minutes,stop_count,status,provider_note
        ) VALUES(?,?,?,?,?,?,?,?,?,?)
        """,
        (
            org["id"], work_day["id"], driver_id, now_iso(), provider_name,
            km, mins, len(ordered), "published", note
        )
    )
    return len(ordered), km, mins, provider_name, note


def geocode_google(address):
    key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if not key:
        return None
    try:
        resp = requests.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={"address": address, "key": key}, timeout=12
        )
        data = resp.json()
        if data.get("status") == "OK" and data.get("results"):
            loc = data["results"][0]["geometry"]["location"]
            return float(loc["lat"]), float(loc["lng"])
    except Exception:
        return None
    return None


def read_import(file_storage):
    name = (file_storage.filename or "").lower()
    raw = file_storage.read()
    if name.endswith(".csv"):
        text = raw.decode("utf-8-sig", errors="replace")
        rows = list(csv.DictReader(io.StringIO(text)))
    elif name.endswith(".xlsx"):
        wb = load_workbook(io.BytesIO(raw), data_only=True)
        ws = wb.active
        values = list(ws.iter_rows(values_only=True))
        if not values:
            return []
        headers = [str(x or "").strip() for x in values[0]]
        rows = [dict(zip(headers, row)) for row in values[1:]]
    else:
        raise ValueError("Formato no soportado. Usa CSV o XLSX.")

    aliases = {
        "code": ["codigo", "código", "code", "paquete", "package_code"],
        "barcode": ["barcode", "codigo_barras", "código_barras", "qr", "tracking"],
        "recipient": ["cliente", "destinatario", "recipient", "recipient_name", "nombre"],
        "phone": ["telefono", "teléfono", "phone", "movil", "móvil"],
        "address": ["direccion", "dirección", "address", "domicilio"],
        "driver": ["conductor", "repartidor", "driver"],
        "origin_country": ["pais_origen", "país_origen", "origin_country", "origen", "pais"],
        "carrier": ["empresa", "transportadora", "carrier", "operador", "empresa_logistica"],
        "zone": ["zona", "zone", "sector", "area"],
        "package_type": ["tipo", "tipo_paquete", "package_type", "categoria"],
        "weight_kg": ["peso", "peso_kg", "weight", "weight_kg"],
        "priority": ["prioridad", "priority"],
        "special": ["caracteristicas", "características", "special_characteristics", "observacion_especial"],
        "lat": ["lat", "latitude", "latitud"],
        "lon": ["lon", "lng", "longitude", "longitud"],
    }

    def pick(row, keys):
        normalized = {str(k).strip().lower(): v for k, v in row.items()}
        for k in keys:
            if k in normalized and normalized[k] not in (None, ""):
                return normalized[k]
        return ""

    items = []
    for row in rows:
        code = str(pick(row, aliases["code"])).strip()
        address = str(pick(row, aliases["address"])).strip()
        if not code or not address:
            continue
        def fval(key):
            v=pick(row,aliases[key])
            try: return float(v) if v not in (None,"") else None
            except Exception: return None
        barcode = str(pick(row, aliases["barcode"])).strip() or code
        items.append({
            "code": code,
            "barcode": barcode,
            "recipient": str(pick(row, aliases["recipient"])).strip(),
            "phone": str(pick(row, aliases["phone"])).strip(),
            "address": address,
            "driver": str(pick(row, aliases["driver"])).strip(),
            "origin_country": str(pick(row, aliases["origin_country"])).strip(),
            "carrier": str(pick(row, aliases["carrier"])).strip(),
            "zone": str(pick(row, aliases["zone"])).strip(),
            "package_type": str(pick(row, aliases["package_type"])).strip(),
            "weight_kg": fval("weight_kg"),
            "priority": str(pick(row, aliases["priority"])).strip().lower() or "normal",
            "special": str(pick(row, aliases["special"])).strip(),
            "lat": fval("lat"),
            "lon": fval("lon"),
        })
    return items


def _norm(value):
    return (str(value).strip().casefold() if value not in (None, "") else "")


def rule_matches(rule, package):
    checks = [
        ("origin_country", "País"), ("carrier", "Empresa"), ("zone", "Zona"),
        ("package_type", "Tipo"), ("priority_value", "Prioridad")
    ]
    reasons=[]
    for key,label in checks:
        expected = rule[key]
        if expected:
            pkg_key = "priority" if key == "priority_value" else key
            if _norm(package[pkg_key]) != _norm(expected):
                return False, []
            reasons.append(f"{label}={expected}")
    w = package["weight_kg"]
    if rule["min_weight_kg"] is not None:
        if w is None or float(w) < float(rule["min_weight_kg"]): return False, []
        reasons.append(f"Peso≥{rule['min_weight_kg']}kg")
    if rule["max_weight_kg"] is not None:
        if w is None or float(w) > float(rule["max_weight_kg"]): return False, []
        reasons.append(f"Peso≤{rule['max_weight_kg']}kg")
    if rule["characteristic_contains"]:
        token=_norm(rule["characteristic_contains"])
        if token not in _norm(package["special_characteristics"]): return False, []
        reasons.append(f"Característica contiene '{rule['characteristic_contains']}'")
    return (len(reasons)>0), reasons


def run_smart_dispatch(db, org_id, work_day_id, overwrite=False):
    rules = db.execute(
        "SELECT r.*,d.name driver_name FROM dispatch_rules r JOIN drivers d ON d.id=r.target_driver_id "
        "WHERE r.organization_id=? AND r.active=1 ORDER BY r.rule_priority ASC,r.id ASC", (org_id,)
    ).fetchall()
    q="SELECT * FROM packages WHERE work_day_id=? AND status='pending'"
    if not overwrite: q += " AND driver_id IS NULL"
    packages=db.execute(q,(work_day_id,)).fetchall()
    assigned=0; unmatched=0; changed=0
    for p in packages:
        match=None; reason=[]
        for r in rules:
            ok, why=rule_matches(r,p)
            if ok: match=r; reason=why; break
        if not match:
            unmatched += 1
            db.execute("UPDATE packages SET classification_status='exception' WHERE id=?",(p["id"],))
            continue
        prev=p["driver_id"]
        db.execute(
            """UPDATE packages SET driver_id=?,assigned_by='rule',dispatch_rule_id=?,dispatch_reason=?,
            classification_status='auto',sequence=NULL WHERE id=?""",
            (match["target_driver_id"],match["id"]," · ".join(reason),p["id"])
        )
        db.execute(
            """INSERT INTO dispatch_history(organization_id,work_day_id,package_id,previous_driver_id,new_driver_id,
            assignment_source,dispatch_rule_id,reason,created_at) VALUES(?,?,?,?,?,?,?,?,?)""",
            (org_id,work_day_id,p["id"],prev,match["target_driver_id"],"rule",match["id"]," · ".join(reason),now_iso())
        )
        assigned += 1
        if prev != match["target_driver_id"]: changed += 1
    return {"processed":len(packages),"assigned":assigned,"unmatched":unmatched,"changed":changed}


def dispatch_suggestions(db, org_id, min_samples=3, min_confidence=0.8):
    rows=db.execute(
        """SELECT p.carrier,p.origin_country,p.zone,p.package_type,h.new_driver_id,d.name driver_name,COUNT(*) n
        FROM dispatch_history h JOIN packages p ON p.id=h.package_id JOIN drivers d ON d.id=h.new_driver_id
        WHERE h.organization_id=? AND h.assignment_source='manual' AND h.new_driver_id IS NOT NULL
        GROUP BY p.carrier,p.origin_country,p.zone,p.package_type,h.new_driver_id""",(org_id,)
    ).fetchall()
    groups={}
    for r in rows:
        key=(r["carrier"] or "",r["origin_country"] or "",r["zone"] or "",r["package_type"] or "")
        groups.setdefault(key,[]).append(dict(r))
    out=[]
    for key,vals in groups.items():
        total=sum(v["n"] for v in vals); best=max(vals,key=lambda x:x["n"])
        conf=best["n"]/total if total else 0
        if total>=min_samples and conf>=min_confidence and any(key):
            out.append({"carrier":key[0],"origin_country":key[1],"zone":key[2],"package_type":key[3],
                        "driver_id":best["new_driver_id"],"driver_name":best["driver_name"],"samples":total,"confidence":conf})
    return sorted(out,key=lambda x:(-x["confidence"],-x["samples"]))[:20]


@app.context_processor
def inject_globals():
    return {
        "today": date.today().isoformat(),
        "routeops_timezone": TIMEZONE_NAME
    }


@app.route("/")
def home():
    if not session.get("user_id"):
        return redirect(url_for("login"))
    return redirect(url_for("admin_dashboard") if session.get("role") == "admin" else url_for("driver_home"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        identity = request.form.get("identity", "").strip().lower()
        password = request.form.get("password", "")
        db = get_db()
        user = db.execute(
            """
            SELECT * FROM users
            WHERE lower(coalesce(email,''))=? OR lower(coalesce(username,''))=?
            ORDER BY id LIMIT 1
            """,
            (identity, identity)
        ).fetchone()
        db.close()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session.update({
                "user_id": user["id"],
                "organization_id": user["organization_id"],
                "role": user["role"],
                "driver_id": user["driver_id"]
            })
            return redirect(url_for("home"))
        flash("Credenciales incorrectas.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/admin")
@login_required("admin")
def admin_dashboard():
    db = get_db()
    org_id = get_org_id()
    workdays = db.execute(
        "SELECT * FROM work_days WHERE organization_id=? ORDER BY work_date DESC,id DESC LIMIT 30",
        (org_id,)
    ).fetchall()
    work_day_id = request.args.get("work_day_id", type=int)
    if work_day_id:
        wd = get_workday(db, work_day_id, org_id)
    else:
        wd = db.execute(
            """
            SELECT * FROM work_days WHERE organization_id=?
            ORDER BY CASE WHEN status='active' THEN 0 ELSE 1 END, work_date DESC,id DESC LIMIT 1
            """, (org_id,)
        ).fetchone()

    stats = {"assigned": 0, "delivered": 0, "pending": 0, "failed": 0}
    drivers = []
    if wd:
        stats_row = db.execute(
            """
            SELECT COUNT(*) assigned,
                   COALESCE(SUM(status='delivered'),0) delivered,
                   COALESCE(SUM(status='pending'),0) pending,
                   COALESCE(SUM(status='failed'),0) failed
            FROM packages WHERE work_day_id=?
            """, (wd["id"],)
        ).fetchone()
        stats = dict(stats_row)
        drivers = db.execute(
            """
            SELECT d.*, COUNT(p.id) assigned,
                   COALESCE(SUM(p.status='delivered'),0) delivered,
                   COALESCE(SUM(p.status='failed'),0) failed,
                   COALESCE(SUM(p.status='pending'),0) pending
            FROM drivers d
            LEFT JOIN packages p ON p.driver_id=d.id AND p.work_day_id=?
            WHERE d.organization_id=? AND d.active=1
            GROUP BY d.id ORDER BY d.name
            """, (wd["id"], org_id)
        ).fetchall()
    db.close()
    return render_template("admin_dashboard.html", stats=stats, drivers=drivers, workdays=workdays, wd=wd)


@app.route("/admin/workdays")
@login_required("admin")
def workdays_page():
    db = get_db()
    org_id = get_org_id()
    workdays = db.execute(
        """
        SELECT w.*,
               COUNT(p.id) packages,
               COALESCE(SUM(p.status='delivered'),0) delivered,
               COALESCE(SUM(p.status='failed'),0) failed
        FROM work_days w
        LEFT JOIN packages p ON p.work_day_id=w.id
        WHERE w.organization_id=?
        GROUP BY w.id ORDER BY w.work_date DESC,w.id DESC
        """, (org_id,)
    ).fetchall()
    db.close()
    return render_template("workdays.html", workdays=workdays)


@app.route("/admin/workdays", methods=["POST"])
@login_required("admin")
def create_workday():
    work_date = request.form.get("work_date") or date.today().isoformat()
    name = request.form.get("name", "").strip() or "Jornada"
    org_id = get_org_id()
    db = get_db()
    try:
        cur = db.execute(
            "INSERT INTO work_days(organization_id,work_date,name,status,created_at) VALUES(?,?,?,?,?)",
            (org_id, work_date, name, "planning", now_iso())
        )
        db.commit()
        flash("Jornada creada.", "success")
        return redirect(url_for("workday_detail", work_day_id=cur.lastrowid))
    except sqlite3.IntegrityError:
        flash("Ya existe una jornada con ese nombre en esa fecha.", "error")
        return redirect(url_for("workdays_page"))
    finally:
        db.close()


@app.route("/admin/workdays/<int:work_day_id>")
@login_required("admin")
def workday_detail(work_day_id):
    db = get_db()
    wd = get_workday(db, work_day_id)
    stats = db.execute(
        """
        SELECT COUNT(*) packages,
               COALESCE(SUM(status='delivered'),0) delivered,
               COALESCE(SUM(status='pending'),0) pending,
               COALESCE(SUM(status='failed'),0) failed,
               COALESCE(SUM(lat IS NULL OR lon IS NULL),0) missing_coords
        FROM packages WHERE work_day_id=?
        """, (work_day_id,)
    ).fetchone()
    drivers = db.execute(
        """
        SELECT d.*, COUNT(p.id) packages
        FROM drivers d LEFT JOIN packages p ON p.driver_id=d.id AND p.work_day_id=?
        WHERE d.organization_id=? AND d.active=1
        GROUP BY d.id ORDER BY d.name
        """, (work_day_id, get_org_id())
    ).fetchall()
    db.close()
    return render_template("workday_detail.html", wd=wd, stats=stats, drivers=drivers)


@app.route("/admin/workdays/<int:work_day_id>/status", methods=["POST"])
@login_required("admin")
def workday_status(work_day_id):
    status = request.form.get("status")
    if status not in {"planning", "active", "closed"}:
        abort(400)
    db = get_db()
    wd = get_workday(db, work_day_id)
    if status == "active":
        db.execute(
            "UPDATE work_days SET status='planning' WHERE organization_id=? AND status='active' AND id<>?",
            (get_org_id(), work_day_id)
        )
        db.execute(
            "UPDATE work_days SET status='active',activated_at=COALESCE(activated_at,?) WHERE id=?",
            (now_iso(), work_day_id)
        )
    elif status == "closed":
        db.execute("UPDATE work_days SET status='closed',closed_at=? WHERE id=?", (now_iso(), work_day_id))
    else:
        db.execute("UPDATE work_days SET status='planning' WHERE id=?", (work_day_id,))
    db.commit()
    db.close()
    flash(f"Jornada actualizada a {status}.", "success")
    return redirect(url_for("workday_detail", work_day_id=work_day_id))


@app.route("/admin/workdays/<int:work_day_id>/packages")
@login_required("admin")
def packages_page(work_day_id):
    db = get_db()
    wd = get_workday(db, work_day_id)
    packages = db.execute(
        """
        SELECT p.*, d.name driver_name FROM packages p
        LEFT JOIN drivers d ON d.id=p.driver_id
        WHERE p.work_day_id=?
        ORDER BY CASE WHEN p.sequence IS NULL THEN 1 ELSE 0 END,p.sequence,p.id
        LIMIT 1500
        """, (work_day_id,)
    ).fetchall()
    drivers = db.execute(
        "SELECT * FROM drivers WHERE organization_id=? AND active=1 ORDER BY name",
        (get_org_id(),)
    ).fetchall()
    missing_coords = db.execute(
        "SELECT COUNT(*) c FROM packages WHERE work_day_id=? AND (lat IS NULL OR lon IS NULL)",
        (work_day_id,)
    ).fetchone()["c"]
    db.close()
    return render_template(
        "packages.html", wd=wd, packages=packages, drivers=drivers, missing_coords=missing_coords
    )


@app.route("/admin/workdays/<int:work_day_id>/packages/import", methods=["POST"])
@login_required("admin")
def import_packages(work_day_id):
    f = request.files.get("file")
    if not f or not f.filename:
        flash("Selecciona un CSV o XLSX.", "error")
        return redirect(url_for("packages_page", work_day_id=work_day_id))
    try:
        items = read_import(f)
    except Exception as exc:
        flash(str(exc), "error")
        return redirect(url_for("packages_page", work_day_id=work_day_id))

    db = get_db()
    wd = get_workday(db, work_day_id)
    drivers = {
        r["name"].lower(): r["id"]
        for r in db.execute("SELECT * FROM drivers WHERE organization_id=?", (get_org_id(),))
    }
    created, duplicated = 0, 0
    for it in items:
        driver_id = drivers.get(it["driver"].lower()) if it["driver"] else None
        try:
            db.execute(
                """
                INSERT INTO packages(
                    organization_id,work_day_id,code,barcode,recipient_name,phone,address,
                    origin_country,carrier,zone,package_type,weight_kg,priority,special_characteristics,
                    lat,lon,driver_id,assigned_by,dispatch_reason,classification_status,status,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    get_org_id(), work_day_id, it["code"], it["barcode"], it["recipient"],
                    it["phone"], it["address"], it["origin_country"], it["carrier"], it["zone"],
                    it["package_type"], it["weight_kg"], it["priority"], it["special"],
                    it["lat"], it["lon"], driver_id,
                    "import" if driver_id else None,
                    ("Preasignado en archivo" if driver_id else None),
                    ("reviewed" if driver_id else "unreviewed"),
                    "pending", now_iso()
                )
            )
            created += 1
        except sqlite3.IntegrityError:
            duplicated += 1
    db.commit()
    db.close()
    flash(f"Importación: {created} nuevos · {duplicated} duplicados omitidos.", "success")
    return redirect(url_for("packages_page", work_day_id=work_day_id))


@app.route("/admin/workdays/<int:work_day_id>/packages/manual", methods=["POST"])
@login_required("admin")
def add_package_manual(work_day_id):
    code = request.form.get("code", "").strip()
    barcode = request.form.get("barcode", "").strip() or code
    address = request.form.get("address", "").strip()
    if not code or not address:
        flash("Código y dirección son obligatorios.", "error")
        return redirect(url_for("packages_page", work_day_id=work_day_id))
    driver_id = request.form.get("driver_id", type=int)
    lat = request.form.get("lat", type=float)
    lon = request.form.get("lon", type=float)
    db = get_db()
    get_workday(db, work_day_id)
    try:
        db.execute(
            """
            INSERT INTO packages(
                organization_id,work_day_id,code,barcode,recipient_name,phone,address,
                origin_country,carrier,zone,package_type,weight_kg,priority,special_characteristics,
                lat,lon,driver_id,assigned_by,dispatch_reason,classification_status,status,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                get_org_id(), work_day_id, code, barcode,
                request.form.get("recipient_name", "").strip(),
                request.form.get("phone", "").strip(), address,
                request.form.get("origin_country", "").strip(),
                request.form.get("carrier", "").strip(),
                request.form.get("zone", "").strip(),
                request.form.get("package_type", "").strip(),
                request.form.get("weight_kg", type=float),
                request.form.get("priority", "normal").strip().lower() or "normal",
                request.form.get("special_characteristics", "").strip(),
                lat, lon, driver_id,
                "manual" if driver_id else None,
                "Asignación manual al crear paquete" if driver_id else None,
                "reviewed" if driver_id else "unreviewed",
                "pending", now_iso()
            )
        )
        db.commit()
        flash("Paquete añadido.", "success")
    except sqlite3.IntegrityError:
        flash("Ese código ya existe en la jornada.", "error")
    finally:
        db.close()
    return redirect(url_for("packages_page", work_day_id=work_day_id))


@app.route("/admin/workdays/<int:work_day_id>/packages/<int:package_id>/assign", methods=["POST"])
@login_required("admin")
def assign_package(work_day_id, package_id):
    driver_id = request.form.get("driver_id", type=int)
    db = get_db()
    get_workday(db, work_day_id)
    p = db.execute("SELECT * FROM packages WHERE id=? AND work_day_id=?", (package_id, work_day_id)).fetchone()
    if not p:
        db.close(); abort(404)
    db.execute(
        """UPDATE packages SET driver_id=?,sequence=NULL,assigned_by=?,dispatch_rule_id=NULL,
        dispatch_reason=?,classification_status=? WHERE id=? AND work_day_id=?""",
        (driver_id, "manual" if driver_id else None, "Asignación manual" if driver_id else None,
         "reviewed" if driver_id else "unreviewed", package_id, work_day_id)
    )
    db.execute(
        """INSERT INTO dispatch_history(organization_id,work_day_id,package_id,previous_driver_id,new_driver_id,
        assignment_source,dispatch_rule_id,reason,created_at) VALUES(?,?,?,?,?,?,?,?,?)""",
        (get_org_id(),work_day_id,package_id,p["driver_id"],driver_id,"manual",None,"Asignación manual",now_iso())
    )
    db.commit(); db.close()
    return redirect(request.referrer or url_for("packages_page", work_day_id=work_day_id))


@app.route("/admin/workdays/<int:work_day_id>/geocode", methods=["POST"])
@login_required("admin")
def geocode_missing(work_day_id):
    if not os.environ.get("GOOGLE_MAPS_API_KEY", "").strip():
        flash("Configura GOOGLE_MAPS_API_KEY en .env.", "error")
        return redirect(url_for("packages_page", work_day_id=work_day_id))
    db = get_db()
    get_workday(db, work_day_id)
    rows = db.execute(
        "SELECT id,address FROM packages WHERE work_day_id=? AND (lat IS NULL OR lon IS NULL) LIMIT 300",
        (work_day_id,)
    ).fetchall()
    ok = 0
    for r in rows:
        loc = geocode_google(r["address"])
        if loc:
            db.execute("UPDATE packages SET lat=?,lon=? WHERE id=?", (loc[0], loc[1], r["id"]))
            db.commit()
            ok += 1
    db.close()
    flash(f"Geocodificación: {ok}/{len(rows)} resueltas.", "success")
    return redirect(url_for("packages_page", work_day_id=work_day_id))


@app.route("/admin/workdays/<int:work_day_id>/dispatch")
@login_required("admin")
def dispatch_page(work_day_id):
    db=get_db(); wd=get_workday(db,work_day_id)
    drivers=db.execute("SELECT * FROM drivers WHERE organization_id=? AND active=1 ORDER BY name",(get_org_id(),)).fetchall()
    rules=db.execute("""SELECT r.*,d.name driver_name FROM dispatch_rules r JOIN drivers d ON d.id=r.target_driver_id
        WHERE r.organization_id=? ORDER BY r.rule_priority,r.id""",(get_org_id(),)).fetchall()
    packages=db.execute("""SELECT p.*,d.name driver_name,r.name rule_name FROM packages p
        LEFT JOIN drivers d ON d.id=p.driver_id LEFT JOIN dispatch_rules r ON r.id=p.dispatch_rule_id
        WHERE p.work_day_id=? ORDER BY p.id""",(work_day_id,)).fetchall()
    summary=db.execute("""SELECT COUNT(*) total,COALESCE(SUM(driver_id IS NOT NULL),0) assigned,
        COALESCE(SUM(driver_id IS NULL),0) unassigned,COALESCE(SUM(classification_status='exception'),0) exceptions,
        COALESCE(SUM(assigned_by='rule'),0) automatic FROM packages WHERE work_day_id=?""",(work_day_id,)).fetchone()
    by_driver=db.execute("""SELECT d.id,d.name,COUNT(p.id) packages FROM drivers d
        LEFT JOIN packages p ON p.driver_id=d.id AND p.work_day_id=? WHERE d.organization_id=? AND d.active=1
        GROUP BY d.id ORDER BY d.name""",(work_day_id,get_org_id())).fetchall()
    suggestions=dispatch_suggestions(db,get_org_id())
    db.close()
    return render_template("dispatch.html",wd=wd,drivers=drivers,rules=rules,packages=packages,summary=summary,by_driver=by_driver,suggestions=suggestions)


@app.route("/admin/workdays/<int:work_day_id>/dispatch/run",methods=["POST"])
@login_required("admin")
def dispatch_run(work_day_id):
    db=get_db(); get_workday(db,work_day_id)
    overwrite=request.form.get("overwrite")=="1"
    result=run_smart_dispatch(db,get_org_id(),work_day_id,overwrite=overwrite)
    db.commit(); db.close()
    flash(f"Smart Dispatch: {result['assigned']} asignados · {result['unmatched']} excepciones · {result['processed']} procesados.","success")
    return redirect(url_for("dispatch_page",work_day_id=work_day_id))


@app.route("/admin/dispatch/rules",methods=["POST"])
@login_required("admin")
def dispatch_rule_create():
    work_day_id=request.form.get("work_day_id",type=int)
    driver_id=request.form.get("target_driver_id",type=int)
    if not driver_id:
        flash("Selecciona un repartidor destino.","error"); return redirect(url_for("dispatch_page",work_day_id=work_day_id))
    fields={k:(request.form.get(k," ").strip() or None) for k in ["origin_country","carrier","zone","package_type","priority_value","characteristic_contains"]}
    if not any(fields.values()) and request.form.get("min_weight_kg","").strip()=="" and request.form.get("max_weight_kg","").strip()=="":
        flash("La regla necesita al menos una condición.","error"); return redirect(url_for("dispatch_page",work_day_id=work_day_id))
    db=get_db()
    d=db.execute("SELECT name FROM drivers WHERE id=? AND organization_id=?",(driver_id,get_org_id())).fetchone()
    if not d: db.close(); abort(404)
    name=request.form.get("name","").strip() or f"Regla → {d['name']}"
    db.execute("""INSERT INTO dispatch_rules(organization_id,name,origin_country,carrier,zone,package_type,min_weight_kg,max_weight_kg,
        priority_value,characteristic_contains,target_driver_id,rule_priority,active,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1,?)""",
        (get_org_id(),name,fields["origin_country"],fields["carrier"],fields["zone"],fields["package_type"],
         request.form.get("min_weight_kg",type=float),request.form.get("max_weight_kg",type=float),fields["priority_value"],
         fields["characteristic_contains"],driver_id,request.form.get("rule_priority",type=int) or 100,now_iso()))
    db.commit(); db.close(); flash("Regla creada.","success")
    return redirect(url_for("dispatch_page",work_day_id=work_day_id))


@app.route("/admin/dispatch/rules/<int:rule_id>/toggle",methods=["POST"])
@login_required("admin")
def dispatch_rule_toggle(rule_id):
    work_day_id=request.form.get("work_day_id",type=int)
    db=get_db(); r=db.execute("SELECT * FROM dispatch_rules WHERE id=? AND organization_id=?",(rule_id,get_org_id())).fetchone()
    if not r: db.close(); abort(404)
    db.execute("UPDATE dispatch_rules SET active=? WHERE id=?",(0 if r["active"] else 1,rule_id)); db.commit(); db.close()
    return redirect(url_for("dispatch_page",work_day_id=work_day_id))


@app.route("/admin/dispatch/rules/<int:rule_id>/delete",methods=["POST"])
@login_required("admin")
def dispatch_rule_delete(rule_id):
    work_day_id=request.form.get("work_day_id",type=int)
    db=get_db(); db.execute("DELETE FROM dispatch_rules WHERE id=? AND organization_id=?",(rule_id,get_org_id())); db.commit(); db.close()
    flash("Regla eliminada.","success"); return redirect(url_for("dispatch_page",work_day_id=work_day_id))


@app.route("/admin/dispatch/suggestion",methods=["POST"])
@login_required("admin")
def dispatch_accept_suggestion():
    work_day_id=request.form.get("work_day_id",type=int); driver_id=request.form.get("driver_id",type=int)
    db=get_db(); d=db.execute("SELECT name FROM drivers WHERE id=? AND organization_id=?",(driver_id,get_org_id())).fetchone()
    if not d: db.close(); abort(404)
    vals={k:(request.form.get(k,"").strip() or None) for k in ["carrier","origin_country","zone","package_type"]}
    parts=[f"{k}={v}" for k,v in vals.items() if v]
    db.execute("""INSERT INTO dispatch_rules(organization_id,name,origin_country,carrier,zone,package_type,target_driver_id,rule_priority,active,created_at)
        VALUES(?,?,?,?,?,?,?,?,1,?)""",(get_org_id(),"Aprendida: "+" · ".join(parts)+f" → {d['name']}",vals["origin_country"],vals["carrier"],vals["zone"],vals["package_type"],driver_id,80,now_iso()))
    db.commit(); db.close(); flash("Sugerencia convertida en regla.","success")
    return redirect(url_for("dispatch_page",work_day_id=work_day_id))


@app.route("/admin/workdays/<int:work_day_id>/routes")
@login_required("admin")
def routes_page(work_day_id):
    db = get_db()
    wd = get_workday(db, work_day_id)
    drivers = db.execute(
        """
        SELECT d.*, COUNT(p.id) stops,
               COALESCE(SUM(p.lat IS NOT NULL AND p.lon IS NOT NULL),0) geocoded,
               COALESCE(SUM(p.status='delivered'),0) delivered
        FROM drivers d
        LEFT JOIN packages p ON p.driver_id=d.id AND p.work_day_id=?
        WHERE d.organization_id=? AND d.active=1
        GROUP BY d.id ORDER BY d.name
        """, (work_day_id, get_org_id())
    ).fetchall()
    runs = db.execute(
        """
        SELECT rr.*, d.name driver_name
        FROM route_runs rr JOIN drivers d ON d.id=rr.driver_id
        WHERE rr.work_day_id=? ORDER BY rr.id DESC LIMIT 100
        """, (work_day_id,)
    ).fetchall()
    google_ready = bool(os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
                        and os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip())
    db.close()
    return render_template(
        "routes.html", wd=wd, drivers=drivers, runs=runs, google_ready=google_ready
    )


@app.route("/admin/workdays/<int:work_day_id>/routes/optimize/<int:driver_id>", methods=["POST"])
@login_required("admin")
def optimize_route(work_day_id, driver_id):
    provider = request.form.get("provider", "local")
    if provider not in {"local", "google"}:
        provider = "local"
    db = get_db()
    wd = get_workday(db, work_day_id)
    org = db.execute("SELECT * FROM organizations WHERE id=?", (get_org_id(),)).fetchone()
    try:
        count, km, mins, provider_name, note = optimize_driver_route(
            db, org, wd, driver_id, provider
        )
        db.commit()
        flash(
            f"Ruta {provider_name}: {count} paradas · {km:.1f} km · {mins} min.",
            "success"
        )
    except Exception as exc:
        db.rollback()
        flash(f"No se pudo optimizar: {exc}", "error")
    finally:
        db.close()
    return redirect(url_for("routes_page", work_day_id=work_day_id))


@app.route("/admin/drivers")
@login_required("admin")
def drivers_page():
    db = get_db()
    drivers = db.execute(
        """
        SELECT d.*, u.username
        FROM drivers d LEFT JOIN users u ON u.driver_id=d.id
        WHERE d.organization_id=?
        ORDER BY d.name
        """, (get_org_id(),)
    ).fetchall()
    db.close()
    return render_template("drivers.html", drivers=drivers)


@app.route("/admin/drivers", methods=["POST"])
@login_required("admin")
def create_driver():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    try:
        pay = float(request.form.get("pay_per_delivery") or 0.85)
    except Exception:
        pay = 0.85
    if not name:
        flash("Nombre requerido.", "error")
        return redirect(url_for("drivers_page"))

    db = get_db()
    cur = db.execute(
        "INSERT INTO drivers(organization_id,name,email,pay_per_delivery,created_at) VALUES(?,?,?,?,?)",
        (get_org_id(), name, email, pay, now_iso())
    )
    driver_id = cur.lastrowid
    stem = "".join(c for c in name.lower().replace(" ", "") if c.isalnum()) or "driver"
    username = stem
    n = 1
    while db.execute(
        "SELECT 1 FROM users WHERE organization_id=? AND username=?",
        (get_org_id(), username)
    ).fetchone():
        n += 1
        username = f"{stem}{n}"
    db.execute(
        "INSERT INTO users(organization_id,email,username,password_hash,role,driver_id) VALUES(?,?,?,?,?,?)",
        (get_org_id(), email or None, username, generate_password_hash("1234"), "driver", driver_id)
    )
    db.commit()
    db.close()
    flash(f"Repartidor creado · usuario {username} · clave temporal 1234.", "success")
    return redirect(url_for("drivers_page"))


@app.route("/admin/workdays/<int:work_day_id>/map")
@login_required("admin")
def live_map(work_day_id):
    db = get_db()
    wd = get_workday(db, work_day_id)
    points = db.execute(
        """
        SELECT p.id,p.code,p.address,p.lat,p.lon,p.status,p.sequence,
               d.name driver_name,d.id driver_id
        FROM packages p LEFT JOIN drivers d ON d.id=p.driver_id
        WHERE p.work_day_id=? AND p.lat IS NOT NULL AND p.lon IS NOT NULL
        ORDER BY d.id,p.sequence,p.id
        """, (work_day_id,)
    ).fetchall()
    drivers = db.execute(
        "SELECT * FROM drivers WHERE organization_id=? AND active=1 ORDER BY name",
        (get_org_id(),)
    ).fetchall()
    db.close()
    return render_template(
        "map.html", wd=wd, drivers=drivers, points=[dict(x) for x in points]
    )


@app.route("/api/admin/workdays/<int:work_day_id>/tracking")
@login_required("admin")
def api_admin_tracking(work_day_id):
    db = get_db()
    get_workday(db, work_day_id)
    drivers = db.execute(
        "SELECT id,name FROM drivers WHERE organization_id=? AND active=1 ORDER BY name",
        (get_org_id(),)
    ).fetchall()
    output = []
    for d in drivers:
        rows = db.execute(
            """
            SELECT lat,lon,accuracy,speed,heading,captured_at
            FROM location_updates
            WHERE work_day_id=? AND driver_id=?
            ORDER BY id DESC LIMIT 120
            """, (work_day_id, d["id"])
        ).fetchall()
        rows = list(reversed([dict(r) for r in rows]))
        output.append({
            "driver_id": d["id"],
            "name": d["name"],
            "track": rows,
            "last": rows[-1] if rows else None
        })
    db.close()
    return jsonify({"ok": True, "drivers": output, "server_time": now_iso()})


@app.route("/admin/workdays/<int:work_day_id>/settlements")
@login_required("admin")
def settlements_page(work_day_id):
    db = get_db()
    wd = get_workday(db, work_day_id)
    drivers = db.execute(
        "SELECT * FROM drivers WHERE organization_id=? AND active=1 ORDER BY name",
        (get_org_id(),)
    ).fetchall()
    for drv in drivers:
        count = db.execute(
            """
            SELECT COUNT(*) c FROM packages
            WHERE work_day_id=? AND driver_id=? AND status='delivered'
            """, (work_day_id, drv["id"])
        ).fetchone()["c"]
        amount = count * drv["pay_per_delivery"]
        db.execute(
            """
            INSERT INTO settlements(
                organization_id,work_day_id,driver_id,delivered_count,amount,status
            ) VALUES(?,?,?,?,?,'pending')
            ON CONFLICT(work_day_id,driver_id) DO UPDATE SET
                delivered_count=excluded.delivered_count,
                amount=excluded.amount
            """, (get_org_id(), work_day_id, drv["id"], count, amount)
        )
    db.commit()
    settlements = db.execute(
        """
        SELECT s.*,d.name driver_name,d.pay_per_delivery
        FROM settlements s JOIN drivers d ON d.id=s.driver_id
        WHERE s.work_day_id=? ORDER BY d.name
        """, (work_day_id,)
    ).fetchall()
    total = sum(float(r["amount"] or 0) for r in settlements)
    db.close()
    return render_template(
        "settlements.html", wd=wd, settlements=settlements, total=total
    )


@app.route("/admin/settlements/<int:settlement_id>/paid", methods=["POST"])
@login_required("admin")
def mark_settlement_paid(settlement_id):
    db = get_db()
    row = db.execute(
        "SELECT * FROM settlements WHERE id=? AND organization_id=?",
        (settlement_id, get_org_id())
    ).fetchone()
    if not row:
        abort(404)
    db.execute(
        "UPDATE settlements SET status='paid',paid_at=? WHERE id=?",
        (now_iso(), settlement_id)
    )
    db.commit()
    db.close()
    return redirect(request.referrer or url_for("admin_dashboard"))


@app.route("/admin/workdays/<int:work_day_id>/settlements/export")
@login_required("admin")
def export_settlements(work_day_id):
    db = get_db()
    wd = get_workday(db, work_day_id)
    rows = db.execute(
        """
        SELECT d.name,s.delivered_count,d.pay_per_delivery,s.amount,s.status
        FROM settlements s JOIN drivers d ON d.id=s.driver_id
        WHERE s.work_day_id=? ORDER BY d.name
        """, (work_day_id,)
    ).fetchall()
    db.close()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Jornada","Fecha","Repartidor","Entregados","Pago por entrega","Total","Estado"])
    for r in rows:
        w.writerow([
            wd["name"], wd["work_date"], r["name"], r["delivered_count"],
            r["pay_per_delivery"], r["amount"], r["status"]
        ])
    return Response(
        out.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=liquidacion_{wd['work_date']}_{work_day_id}.csv"}
    )


@app.route("/admin/reports")
@login_required("admin")
def reports_page():
    db = get_db()
    workdays = db.execute(
        """
        SELECT w.id,w.work_date,w.name,w.status,
               COUNT(p.id) total,
               COALESCE(SUM(p.status='delivered'),0) delivered,
               COALESCE(SUM(p.status='failed'),0) failed
        FROM work_days w LEFT JOIN packages p ON p.work_day_id=w.id
        WHERE w.organization_id=?
        GROUP BY w.id ORDER BY w.work_date DESC,w.id DESC LIMIT 60
        """, (get_org_id(),)
    ).fetchall()
    db.close()
    return render_template("reports.html", workdays=workdays)


@app.route("/admin/settings", methods=["GET", "POST"])
@login_required("admin")
def settings_page():
    db = get_db()
    org = db.execute("SELECT * FROM organizations WHERE id=?", (get_org_id(),)).fetchone()
    if request.method == "POST":
        name = request.form.get("name", "").strip() or org["name"]
        currency = request.form.get("currency", "").strip().upper() or "EUR"
        timezone_name = request.form.get("timezone", "").strip() or TIMEZONE_NAME
        depot_lat = request.form.get("depot_lat", type=float)
        depot_lon = request.form.get("depot_lon", type=float)
        db.execute(
            """
            UPDATE organizations
            SET name=?,currency=?,timezone=?,depot_lat=?,depot_lon=?
            WHERE id=?
            """, (name, currency, timezone_name, depot_lat, depot_lon, get_org_id())
        )
        db.commit()
        flash("Configuración guardada.", "success")
        org = db.execute("SELECT * FROM organizations WHERE id=?", (get_org_id(),)).fetchone()
    google_ready = bool(os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
                        and os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip())
    geocode_ready = bool(os.environ.get("GOOGLE_MAPS_API_KEY", "").strip())
    db.close()
    return render_template(
        "settings.html", org=org, google_ready=google_ready, geocode_ready=geocode_ready
    )


@app.route("/admin/lan")
@login_required("admin")
def lan_connect_page():
    lan_ip = get_lan_ip()
    return render_template(
        "lan.html",
        lan_ip=lan_ip,
        bootstrap_url=f"http://{lan_ip}:5000",
        secure_url=f"https://{lan_ip}:5443",
    )


@app.route("/admin/lan/qr.png")
@login_required("admin")
def lan_connect_qr():
    lan_ip = get_lan_ip()
    return Response(qr_png_bytes(f"http://{lan_ip}:5000"), mimetype="image/png")


@app.route("/health")
def health():
    return jsonify({"ok": True, "version": "0.2.1", "mode": "app"})


@app.route("/driver")
@login_required("driver")
def driver_home():
    db = get_db()
    did = session["driver_id"]
    org_id = get_org_id()
    drv = db.execute("SELECT * FROM drivers WHERE id=? AND organization_id=?", (did, org_id)).fetchone()
    wd = active_workday_for_driver(db, org_id)
    stats = {"assigned": 0, "delivered": 0, "pending": 0, "failed": 0}
    latest = None
    if wd:
        stats = dict(db.execute(
            """
            SELECT COUNT(*) assigned,
                   COALESCE(SUM(status='delivered'),0) delivered,
                   COALESCE(SUM(status='pending'),0) pending,
                   COALESCE(SUM(status='failed'),0) failed
            FROM packages WHERE work_day_id=? AND driver_id=?
            """, (wd["id"], did)
        ).fetchone())
        latest = db.execute(
            """
            SELECT * FROM route_runs
            WHERE work_day_id=? AND driver_id=?
            ORDER BY id DESC LIMIT 1
            """, (wd["id"], did)
        ).fetchone()
    db.close()
    return render_template("driver_home.html", driver=drv, wd=wd, stats=stats, latest=latest)


@app.route("/driver/route")
@login_required("driver")
def driver_route():
    db = get_db()
    did = session["driver_id"]
    wd = active_workday_for_driver(db, get_org_id())
    if not wd:
        db.close()
        flash("No hay una jornada activa.", "error")
        return redirect(url_for("driver_home"))
    packages = db.execute(
        """
        SELECT * FROM packages
        WHERE work_day_id=? AND driver_id=? AND status!='delivered'
        ORDER BY CASE WHEN sequence IS NULL THEN 1 ELSE 0 END,sequence,id
        """, (wd["id"], did)
    ).fetchall()
    db.close()
    return render_template("driver_route.html", wd=wd, packages=packages)


@app.route("/driver/scan")
@login_required("driver")
def driver_scan():
    db = get_db()
    wd = active_workday_for_driver(db, get_org_id())
    db.close()
    if not wd:
        flash("No hay una jornada activa.", "error")
        return redirect(url_for("driver_home"))
    return render_template("driver_scan.html", wd=wd)


@app.route("/driver/scan/lookup", methods=["POST"])
@login_required("driver")
def driver_scan_lookup():
    raw_code = (request.form.get("code") or "").strip()
    if not raw_code:
        flash("No se recibió ningún código.", "error")
        return redirect(url_for("driver_scan"))
    db = get_db()
    wd = active_workday_for_driver(db, get_org_id())
    if not wd:
        db.close()
        return redirect(url_for("driver_home"))
    p = db.execute(
        """
        SELECT * FROM packages
        WHERE work_day_id=? AND driver_id=? AND (code=? OR barcode=?)
        ORDER BY id LIMIT 1
        """, (wd["id"], session["driver_id"], raw_code, raw_code)
    ).fetchone()
    db.execute(
        """
        INSERT INTO scan_events(
            organization_id,work_day_id,driver_id,raw_code,package_id,scan_type,captured_at
        ) VALUES(?,?,?,?,?,?,?)
        """, (
            get_org_id(), wd["id"], session["driver_id"], raw_code,
            p["id"] if p else None, "lookup", now_iso()
        )
    )
    db.commit()
    db.close()
    if not p:
        flash("Código no encontrado en tu jornada.", "error")
        return redirect(url_for("driver_scan"))
    return redirect(url_for("driver_package", package_id=p["id"]))


@app.route("/driver/package/<int:package_id>")
@login_required("driver")
def driver_package(package_id):
    db = get_db()
    did = session["driver_id"]
    p = db.execute(
        """
        SELECT p.*,w.name workday_name,w.work_date
        FROM packages p JOIN work_days w ON w.id=p.work_day_id
        WHERE p.id=? AND p.driver_id=? AND p.organization_id=?
        """, (package_id, did, get_org_id())
    ).fetchone()
    db.close()
    if not p:
        flash("Paquete no disponible.", "error")
        return redirect(url_for("driver_route"))
    return render_template("driver_package.html", p=p)


@app.route("/driver/package/<int:package_id>/deliver", methods=["POST"])
@login_required("driver")
def deliver_package(package_id):
    did = session["driver_id"]
    photo = request.files.get("photo")
    photo_name = None
    if photo and photo.filename:
        ext = photo.filename.rsplit(".", 1)[-1].lower() if "." in photo.filename else ""
        if ext not in ALLOWED_IMAGE_EXT:
            flash("La evidencia debe ser PNG, JPG, JPEG o WEBP.", "error")
            return redirect(url_for("driver_package", package_id=package_id))
        photo_name = f"{did}_{package_id}_{int(datetime.now().timestamp())}_{secure_filename(photo.filename)}"
        photo.save(UPLOAD_DIR / photo_name)

    lat = request.form.get("lat", type=float)
    lon = request.form.get("lon", type=float)
    accuracy = request.form.get("accuracy", type=float)
    notes = request.form.get("notes", "").strip()
    db = get_db()
    p = db.execute(
        "SELECT * FROM packages WHERE id=? AND driver_id=? AND organization_id=?",
        (package_id, did, get_org_id())
    ).fetchone()
    if not p:
        db.close()
        abort(404)
    db.execute(
        """
        UPDATE packages
        SET status='delivered',delivered_at=?,failure_reason=NULL,
            proof_photo=COALESCE(?,proof_photo),delivery_lat=?,delivery_lon=?,
            delivery_accuracy=?,notes=?
        WHERE id=?
        """, (now_iso(), photo_name, lat, lon, accuracy, notes, package_id)
    )
    db.commit()
    db.close()
    flash("Entrega registrada.", "success")
    return redirect(url_for("driver_route"))


@app.route("/driver/package/<int:package_id>/fail", methods=["POST"])
@login_required("driver")
def fail_package(package_id):
    did = session["driver_id"]
    reason = request.form.get("reason", "Otro")
    notes = request.form.get("notes", "").strip()
    db = get_db()
    db.execute(
        """
        UPDATE packages SET status='failed',failure_reason=?,notes=?
        WHERE id=? AND driver_id=? AND organization_id=?
        """, (reason, notes, package_id, did, get_org_id())
    )
    db.commit()
    db.close()
    flash("Incidencia registrada.", "success")
    return redirect(url_for("driver_route"))


@app.route("/api/driver/location", methods=["POST"])
@login_required("driver")
def api_driver_location():
    data = request.get_json(silent=True) or {}
    try:
        lat = float(data["lat"])
        lon = float(data["lon"])
    except Exception:
        return jsonify({"ok": False, "error": "lat/lon invalid"}), 400

    db = get_db()
    wd = active_workday_for_driver(db, get_org_id())
    if not wd:
        db.close()
        return jsonify({"ok": False, "error": "no active workday"}), 409

    def num(name):
        try:
            value = data.get(name)
            return float(value) if value is not None else None
        except Exception:
            return None

    db.execute(
        """
        INSERT INTO location_updates(
            organization_id,work_day_id,driver_id,lat,lon,accuracy,speed,heading,captured_at
        ) VALUES(?,?,?,?,?,?,?,?,?)
        """,
        (
            get_org_id(), wd["id"], session["driver_id"], lat, lon,
            num("accuracy"), num("speed"), num("heading"), now_iso()
        )
    )
    db.commit()
    db.close()
    return jsonify({"ok": True, "captured_at": now_iso()})


@app.route("/uploads/<path:name>")
@login_required()
def uploads(name):
    return send_from_directory(UPLOAD_DIR, name)


@app.route("/manifest.webmanifest")
def manifest():
    return send_from_directory(BASE_DIR / "static", "manifest.webmanifest")


@app.route("/sw.js")
def service_worker():
    return send_from_directory(BASE_DIR / "static", "sw.js", mimetype="application/javascript")


@app.errorhandler(413)
def too_large(_e):
    flash("Archivo demasiado grande (máximo 16 MB).", "error")
    return redirect(request.referrer or url_for("home"))


if __name__ == "__main__":
    init_db()
    print("\\nRouteOps V0.3 local listo en http://127.0.0.1:5000")
    print("Admin: admin@routeops.local / demo123")
    print("Repartidor: carlos / 1234")
    print(f"Zona horaria: {TIMEZONE_NAME}\\n")
    app.run(host="127.0.0.1", port=5000, debug=False)
