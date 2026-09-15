"""SQLite persistence for the Garden Tracker.

Tables: crops, varieties, plantings, harvests, weather, settings. Plain sqlite3
with WAL so the phone and the desktop can hit it at once without fuss.
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from . import config
from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS crops (
    id        INTEGER PRIMARY KEY,
    name      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    color     INTEGER NOT NULL DEFAULT 0,      -- palette slot 1-8, 0 = other
    archived  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS varieties (
    id        INTEGER PRIMARY KEY,
    crop_id   INTEGER NOT NULL REFERENCES crops(id) ON DELETE CASCADE,
    name      TEXT NOT NULL COLLATE NOCASE,
    UNIQUE(crop_id, name)
);
CREATE TABLE IF NOT EXISTS plantings (
    id              INTEGER PRIMARY KEY,
    crop_id         INTEGER NOT NULL REFERENCES crops(id) ON DELETE CASCADE,
    variety_id      INTEGER REFERENCES varieties(id) ON DELETE SET NULL,
    season          INTEGER NOT NULL,
    sow_date        TEXT,
    transplant_date TEXT,
    plant_count     INTEGER,
    location        TEXT NOT NULL DEFAULT '',
    notes           TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS harvests (
    id          INTEGER PRIMARY KEY,
    date        TEXT NOT NULL,                   -- YYYY-MM-DD
    crop_id     INTEGER NOT NULL REFERENCES crops(id) ON DELETE CASCADE,
    variety_id  INTEGER REFERENCES varieties(id) ON DELETE SET NULL,
    planting_id INTEGER REFERENCES plantings(id) ON DELETE SET NULL,
    weight_g    REAL NOT NULL,
    notes       TEXT NOT NULL DEFAULT '',
    created_at  TEXT
);
CREATE INDEX IF NOT EXISTS harvests_date ON harvests(date);
CREATE INDEX IF NOT EXISTS harvests_crop ON harvests(crop_id, date);
CREATE TABLE IF NOT EXISTS weather (
    date        TEXT PRIMARY KEY,                -- YYYY-MM-DD
    tmax_c      REAL,
    tmin_c      REAL,
    precip_mm   REAL,
    sunshine_s  REAL,
    source      TEXT NOT NULL DEFAULT 'auto',    -- auto | manual
    notes       TEXT NOT NULL DEFAULT '',
    fetched_at  TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        defaults = {
            "lat": str(config.DEFAULT_LAT),
            "lon": str(config.DEFAULT_LON),
            "location_name": config.DEFAULT_LOCATION,
            "timezone": config.TIMEZONE,
            "backfill_start": config.BACKFILL_START,
            "backfill_done": "0",
        }
        for k, v in defaults.items():
            conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
        conn.commit()


def _rows(rows: Iterable[sqlite3.Row]) -> List[Dict[str, Any]]:
    return [dict(r) for r in rows]


# ---------- settings ----------

def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    with connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: Any) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, None if value is None else str(value)),
        )
        conn.commit()


def all_settings() -> Dict[str, Optional[str]]:
    with connect() as conn:
        return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings")}


# ---------- crops ----------

CROP_SELECT = """
SELECT c.id, c.name, c.color, c.archived,
       COUNT(h.id) AS harvests, MAX(h.date) AS last_harvest
FROM crops c LEFT JOIN harvests h ON h.crop_id = c.id
"""


def list_crops(include_archived: bool = True) -> List[Dict[str, Any]]:
    where = "" if include_archived else "WHERE c.archived = 0"
    with connect() as conn:
        rows = conn.execute(
            f"{CROP_SELECT} {where} GROUP BY c.id ORDER BY c.archived, c.name COLLATE NOCASE"
        ).fetchall()
    return [dict(r, archived=bool(r["archived"])) for r in rows]


def get_crop(crop_id: int) -> Optional[Dict[str, Any]]:
    with connect() as conn:
        row = conn.execute(f"{CROP_SELECT} WHERE c.id = ? GROUP BY c.id", (crop_id,)).fetchone()
    return dict(row, archived=bool(row["archived"])) if row else None


def _next_color(conn: sqlite3.Connection) -> int:
    """First unused palette slot 1-8; 0 ("other") once all eight are taken."""
    used = {r["color"] for r in conn.execute("SELECT color FROM crops")}
    for slot in range(1, 9):
        if slot not in used:
            return slot
    return 0


def get_or_create_crop(name: str) -> Dict[str, Any]:
    name = name.strip()
    if not name:
        raise ValueError("Crop name is required")
    with connect() as conn:
        row = conn.execute("SELECT id FROM crops WHERE name = ?", (name,)).fetchone()
        if row:
            crop_id = row["id"]
        else:
            cur = conn.execute(
                "INSERT INTO crops(name, color) VALUES (?, ?)", (name, _next_color(conn))
            )
            crop_id = cur.lastrowid
            conn.commit()
    return get_crop(crop_id)


def update_crop(crop_id: int, fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    fields = {k: v for k, v in fields.items() if v is not None}
    if "name" in fields:
        fields["name"] = fields["name"].strip()
    if "archived" in fields:
        fields["archived"] = int(bool(fields["archived"]))
    if fields:
        sets = ", ".join(f"{k} = :{k}" for k in fields)
        with connect() as conn:
            conn.execute(f"UPDATE crops SET {sets} WHERE id = :id", {**fields, "id": crop_id})
            conn.commit()
    return get_crop(crop_id)


def delete_crop(crop_id: int) -> bool:
    """Deletes a crop and (via cascade) its varieties, plantings, and harvests."""
    with connect() as conn:
        cur = conn.execute("DELETE FROM crops WHERE id = ?", (crop_id,))
        conn.commit()
        return cur.rowcount > 0


# ---------- varieties ----------

def list_varieties(crop_id: Optional[int] = None) -> List[Dict[str, Any]]:
    with connect() as conn:
        if crop_id is None:
            rows = conn.execute("SELECT * FROM varieties ORDER BY crop_id, name COLLATE NOCASE").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM varieties WHERE crop_id = ? ORDER BY name COLLATE NOCASE", (crop_id,)
            ).fetchall()
    return _rows(rows)


def get_variety(variety_id: int) -> Optional[Dict[str, Any]]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM varieties WHERE id = ?", (variety_id,)).fetchone()
    return dict(row) if row else None


def get_or_create_variety(crop_id: int, name: str) -> Dict[str, Any]:
    name = name.strip()
    if not name:
        raise ValueError("Variety name is required")
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM varieties WHERE crop_id = ? AND name = ?", (crop_id, name)
        ).fetchone()
        if row:
            return dict(row)
        cur = conn.execute("INSERT INTO varieties(crop_id, name) VALUES (?, ?)", (crop_id, name))
        conn.commit()
        return get_variety(cur.lastrowid)


def update_variety(variety_id: int, name: str) -> Optional[Dict[str, Any]]:
    with connect() as conn:
        conn.execute("UPDATE varieties SET name = ? WHERE id = ?", (name.strip(), variety_id))
        conn.commit()
    return get_variety(variety_id)


def delete_variety(variety_id: int) -> bool:
    with connect() as conn:
        cur = conn.execute("DELETE FROM varieties WHERE id = ?", (variety_id,))
        conn.commit()
        return cur.rowcount > 0


# ---------- plantings ----------

PLANTING_SELECT = """
SELECT p.*, c.name AS crop_name, v.name AS variety_name,
       COALESCE(SUM(h.weight_g), 0) AS total_g, COUNT(h.id) AS harvests,
       MIN(h.date) AS first_harvest, MAX(h.date) AS last_harvest
FROM plantings p
JOIN crops c ON c.id = p.crop_id
LEFT JOIN varieties v ON v.id = p.variety_id
LEFT JOIN harvests h ON h.planting_id = p.id
"""


def _finish_planting(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    start = d.get("transplant_date") or d.get("sow_date")
    d["days_to_first"] = None
    if start and d.get("first_harvest"):
        try:
            d["days_to_first"] = (date.fromisoformat(d["first_harvest"]) - date.fromisoformat(start)).days
        except ValueError:
            pass
    d["g_per_plant"] = (d["total_g"] / d["plant_count"]) if d.get("plant_count") else None
    return d


def list_plantings(season: Optional[int] = None, crop_id: Optional[int] = None) -> List[Dict[str, Any]]:
    where, params = [], []
    if season is not None:
        where.append("p.season = ?"); params.append(season)
    if crop_id is not None:
        where.append("p.crop_id = ?"); params.append(crop_id)
    w = ("WHERE " + " AND ".join(where)) if where else ""
    with connect() as conn:
        rows = conn.execute(
            f"{PLANTING_SELECT} {w} GROUP BY p.id "
            "ORDER BY p.season DESC, c.name COLLATE NOCASE, COALESCE(p.transplant_date, p.sow_date)",
            params,
        ).fetchall()
    return [_finish_planting(r) for r in rows]


def get_planting(planting_id: int) -> Optional[Dict[str, Any]]:
    with connect() as conn:
        row = conn.execute(f"{PLANTING_SELECT} WHERE p.id = ? GROUP BY p.id", (planting_id,)).fetchone()
    return _finish_planting(row) if row else None


def insert_planting(fields: Dict[str, Any]) -> Dict[str, Any]:
    cols = ["crop_id", "variety_id", "season", "sow_date", "transplant_date", "plant_count", "location", "notes"]
    params = {c: fields.get(c) for c in cols}
    params["location"] = params["location"] or ""
    params["notes"] = params["notes"] or ""
    with connect() as conn:
        cur = conn.execute(
            f"INSERT INTO plantings({', '.join(cols)}) VALUES ({', '.join(':' + c for c in cols)})", params
        )
        conn.commit()
    return get_planting(cur.lastrowid)


def update_planting(planting_id: int, fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    allowed = {"crop_id", "variety_id", "season", "sow_date", "transplant_date", "plant_count", "location", "notes"}
    fields = {k: v for k, v in fields.items() if k in allowed}
    if fields:
        sets = ", ".join(f"{k} = :{k}" for k in fields)
        with connect() as conn:
            conn.execute(f"UPDATE plantings SET {sets} WHERE id = :id", {**fields, "id": planting_id})
            conn.commit()
    return get_planting(planting_id)


def delete_planting(planting_id: int) -> bool:
    with connect() as conn:
        cur = conn.execute("DELETE FROM plantings WHERE id = ?", (planting_id,))
        conn.commit()
        return cur.rowcount > 0


# ---------- harvests ----------

HARVEST_SELECT = """
SELECT h.*, c.name AS crop_name, v.name AS variety_name
FROM harvests h
JOIN crops c ON c.id = h.crop_id
LEFT JOIN varieties v ON v.id = h.variety_id
"""


def list_harvests(
    season: Optional[int] = None,
    crop_id: Optional[int] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    where, params = [], []
    if season is not None:
        where.append("substr(h.date, 1, 4) = ?"); params.append(str(season))
    if crop_id is not None:
        where.append("h.crop_id = ?"); params.append(crop_id)
    if start:
        where.append("h.date >= ?"); params.append(start)
    if end:
        where.append("h.date <= ?"); params.append(end)
    w = ("WHERE " + " AND ".join(where)) if where else ""
    lim = f"LIMIT {int(limit)}" if limit else ""
    with connect() as conn:
        rows = conn.execute(
            f"{HARVEST_SELECT} {w} ORDER BY h.date DESC, h.id DESC {lim}", params
        ).fetchall()
    return _rows(rows)


def get_harvest(harvest_id: int) -> Optional[Dict[str, Any]]:
    with connect() as conn:
        row = conn.execute(f"{HARVEST_SELECT} WHERE h.id = ?", (harvest_id,)).fetchone()
    return dict(row) if row else None


def last_harvest() -> Optional[Dict[str, Any]]:
    with connect() as conn:
        row = conn.execute(f"{HARVEST_SELECT} ORDER BY h.created_at DESC, h.id DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def insert_harvest(fields: Dict[str, Any]) -> Dict[str, Any]:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO harvests(date, crop_id, variety_id, planting_id, weight_g, notes, created_at) "
            "VALUES (:date, :crop_id, :variety_id, :planting_id, :weight_g, :notes, :created_at)",
            {
                "date": fields["date"],
                "crop_id": fields["crop_id"],
                "variety_id": fields.get("variety_id"),
                "planting_id": fields.get("planting_id"),
                "weight_g": float(fields["weight_g"]),
                "notes": fields.get("notes") or "",
                "created_at": now_iso(),
            },
        )
        conn.commit()
    return get_harvest(cur.lastrowid)


def update_harvest(harvest_id: int, fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    allowed = {"date", "crop_id", "variety_id", "planting_id", "weight_g", "notes"}
    fields = {k: v for k, v in fields.items() if k in allowed}
    if fields:
        sets = ", ".join(f"{k} = :{k}" for k in fields)
        with connect() as conn:
            conn.execute(f"UPDATE harvests SET {sets} WHERE id = :id", {**fields, "id": harvest_id})
            conn.commit()
    return get_harvest(harvest_id)


def delete_harvest(harvest_id: int) -> bool:
    with connect() as conn:
        cur = conn.execute("DELETE FROM harvests WHERE id = ?", (harvest_id,))
        conn.commit()
        return cur.rowcount > 0


def harvest_exists(d: str, crop_id: int, weight_g: float) -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM harvests WHERE date = ? AND crop_id = ? AND ABS(weight_g - ?) < 0.001 LIMIT 1",
            (d, crop_id, weight_g),
        ).fetchone()
    return row is not None


def harvest_count() -> int:
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) AS c FROM harvests").fetchone()["c"]


def seasons() -> List[int]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT substr(date, 1, 4) AS y FROM harvests "
            "UNION SELECT DISTINCT CAST(season AS TEXT) FROM plantings ORDER BY y"
        ).fetchall()
    return [int(r["y"]) for r in rows if r["y"]]


# ---------- weather ----------

def list_weather(start: Optional[str] = None, end: Optional[str] = None) -> List[Dict[str, Any]]:
    where, params = [], []
    if start:
        where.append("date >= ?"); params.append(start)
    if end:
        where.append("date <= ?"); params.append(end)
    w = ("WHERE " + " AND ".join(where)) if where else ""
    with connect() as conn:
        rows = conn.execute(f"SELECT * FROM weather {w} ORDER BY date", params).fetchall()
    return _rows(rows)


def get_weather(d: str) -> Optional[Dict[str, Any]]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM weather WHERE date = ?", (d,)).fetchone()
    return dict(row) if row else None


def upsert_weather_auto(days: List[Dict[str, Any]]) -> int:
    """Insert/refresh fetched days. Never touches rows the user set manually."""
    stamp = now_iso()
    n = 0
    with connect() as conn:
        for d in days:
            cur = conn.execute(
                "INSERT INTO weather(date, tmax_c, tmin_c, precip_mm, sunshine_s, source, notes, fetched_at) "
                "VALUES (:date, :tmax_c, :tmin_c, :precip_mm, :sunshine_s, 'auto', '', :fetched_at) "
                "ON CONFLICT(date) DO UPDATE SET "
                "  tmax_c = excluded.tmax_c, tmin_c = excluded.tmin_c, precip_mm = excluded.precip_mm, "
                "  sunshine_s = excluded.sunshine_s, fetched_at = excluded.fetched_at "
                "WHERE weather.source = 'auto'",
                {**d, "fetched_at": stamp},
            )
            n += cur.rowcount
        conn.commit()
    return n


def set_weather_manual(d: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    """Manual override. Supplied numeric fields replace the auto values; notes always saved."""
    existing = get_weather(d) or {"date": d}
    row = {
        "date": d,
        "tmax_c": fields.get("tmax_c", existing.get("tmax_c")),
        "tmin_c": fields.get("tmin_c", existing.get("tmin_c")),
        "precip_mm": fields.get("precip_mm", existing.get("precip_mm")),
        "sunshine_s": existing.get("sunshine_s"),
        "notes": fields.get("notes") if fields.get("notes") is not None else existing.get("notes", ""),
        "fetched_at": existing.get("fetched_at"),
    }
    # A note alone (no numeric change) keeps the row as auto so refreshes still update it.
    numeric_changed = any(
        fields.get(k) is not None and fields.get(k) != existing.get(k)
        for k in ("tmax_c", "tmin_c", "precip_mm")
    )
    row["source"] = "manual" if (numeric_changed or existing.get("source") == "manual") else "auto"
    with connect() as conn:
        conn.execute(
            "INSERT INTO weather(date, tmax_c, tmin_c, precip_mm, sunshine_s, source, notes, fetched_at) "
            "VALUES (:date, :tmax_c, :tmin_c, :precip_mm, :sunshine_s, :source, :notes, :fetched_at) "
            "ON CONFLICT(date) DO UPDATE SET tmax_c = excluded.tmax_c, tmin_c = excluded.tmin_c, "
            "  precip_mm = excluded.precip_mm, source = excluded.source, notes = excluded.notes",
            row,
        )
        conn.commit()
    return get_weather(d)


def delete_weather(d: str) -> bool:
    with connect() as conn:
        cur = conn.execute("DELETE FROM weather WHERE date = ?", (d,))
        conn.commit()
        return cur.rowcount > 0


def weather_count() -> int:
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) AS c FROM weather").fetchone()["c"]
