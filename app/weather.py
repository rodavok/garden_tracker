"""Daily weather from Open-Meteo (free, no API key).

Historical days come from the archive API (which lags ~5 days); recent days
come from the forecast API's past_days window so the current week is covered.
Everything is stored in metric; the UI converts for display.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import requests

from . import config, db, events

log = logging.getLogger("garden.weather")

DAILY_VARS = "temperature_2m_max,temperature_2m_min,precipitation_sum,sunshine_duration"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
ARCHIVE_LAG_DAYS = 6          # archive API is complete up to roughly today - 5
FORECAST_PAST_MAX = 92        # forecast API's past_days ceiling


def _tz() -> ZoneInfo:
    try:
        return ZoneInfo(db.get_setting("timezone", config.TIMEZONE) or config.TIMEZONE)
    except Exception:
        return ZoneInfo("UTC")


def today_local() -> date:
    return datetime.now(_tz()).date()


def location() -> Optional[Dict[str, Any]]:
    s = db.all_settings()
    try:
        lat, lon = float(s.get("lat")), float(s.get("lon"))
    except (TypeError, ValueError):
        return None
    return {"lat": lat, "lon": lon, "tz": s.get("timezone") or config.TIMEZONE}


def _parse(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    d = payload.get("daily") or {}
    out = []
    for i, day in enumerate(d.get("time", [])):
        def pick(key):
            vals = d.get(key) or []
            return vals[i] if i < len(vals) else None
        row = {
            "date": day,
            "tmax_c": pick("temperature_2m_max"),
            "tmin_c": pick("temperature_2m_min"),
            "precip_mm": pick("precipitation_sum"),
            "sunshine_s": pick("sunshine_duration"),
        }
        if row["tmax_c"] is None and row["tmin_c"] is None:
            continue  # archive returns nulls for days it hasn't processed yet
        out.append(row)
    return out


def _get(url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_range(start: date, end: date) -> List[Dict[str, Any]]:
    """Fetch daily rows for [start, end] using the archive + forecast split."""
    loc = location()
    if not loc:
        raise RuntimeError("No location set")
    today = today_local()
    end = min(end, today)
    if start > end:
        return []
    base = {"latitude": loc["lat"], "longitude": loc["lon"], "daily": DAILY_VARS, "timezone": loc["tz"]}
    rows: Dict[str, Dict[str, Any]] = {}

    archive_end = min(end, today - timedelta(days=ARCHIVE_LAG_DAYS))
    if start <= archive_end:
        payload = _get(ARCHIVE_URL, {**base, "start_date": start.isoformat(), "end_date": archive_end.isoformat()})
        for r in _parse(payload):
            rows[r["date"]] = r

    recent_start = max(start, today - timedelta(days=FORECAST_PAST_MAX - 1))
    if recent_start <= end and end > archive_end:
        past_days = (today - recent_start).days
        payload = _get(FORECAST_URL, {**base, "past_days": max(past_days, 0), "forecast_days": 1})
        for r in _parse(payload):
            if start.isoformat() <= r["date"] <= end.isoformat() and r["date"] not in rows:
                rows[r["date"]] = r
    return [rows[k] for k in sorted(rows)]


def refresh_recent(days: int = 7) -> int:
    """Refresh the last `days` days, reaching further back if there's a gap
    since the newest stored day (e.g. the box was off for a fortnight)."""
    today = today_local()
    start = today - timedelta(days=days)
    newest = db.latest_weather_date()
    if newest and date.fromisoformat(newest) < start:
        start = date.fromisoformat(newest)
    rows = fetch_range(start, today)
    n = db.upsert_weather_auto(rows)
    db.set_setting("weather_last_fetch", db.now_iso())
    db.set_setting("weather_last_error", "")
    return n


def backfill(start: Optional[str] = None) -> int:
    start_d = date.fromisoformat(start or db.get_setting("backfill_start", config.BACKFILL_START))
    rows = fetch_range(start_d, today_local())
    n = db.upsert_weather_auto(rows)
    db.set_setting("backfill_done", "1")
    db.set_setting("weather_last_fetch", db.now_iso())
    db.set_setting("weather_last_error", "")
    return n


def refetch_day(d: str) -> Optional[Dict[str, Any]]:
    day = date.fromisoformat(d)
    rows = fetch_range(day, day)
    if rows:
        db.upsert_weather_auto(rows)
    return db.get_weather(d)


def geocode(query: str) -> List[Dict[str, Any]]:
    payload = _get(GEOCODE_URL, {"name": query, "count": 8, "language": "en", "format": "json"})
    out = []
    for r in payload.get("results", []) or []:
        parts = [r.get("name"), r.get("admin1"), r.get("country_code")]
        out.append({
            "name": ", ".join(p for p in parts if p),
            "lat": r.get("latitude"),
            "lon": r.get("longitude"),
            "timezone": r.get("timezone"),
        })
    return out


# ---------- background scheduler ----------

async def _run(fn, *args):
    try:
        n = await asyncio.to_thread(fn, *args)
        log.info("weather: %s -> %s rows", fn.__name__, n)
        events.publish("weather", {})
        return n
    except Exception as exc:  # network down, API hiccup, etc. Never crash the app.
        log.warning("weather: %s failed: %s", fn.__name__, exc)
        db.set_setting("weather_last_error", f"{db.now_iso()}: {exc}")
        return None


async def _catch_up() -> Optional[int]:
    """Backfill if that hasn't completed yet, otherwise refresh the recent days."""
    if not location():
        return 0
    if db.get_setting("backfill_done") != "1":
        return await _run(backfill)
    return await _run(refresh_recent, 7)


RETRY_SECONDS = 30 * 60


async def scheduler():
    """Catch up at boot, then every morning. A failed fetch (network not up yet,
    API down) is retried every half hour rather than waiting for tomorrow."""
    if not config.WEATHER_ENABLED:
        return
    await asyncio.sleep(2)  # let uvicorn finish booting first
    ok = await _catch_up() is not None
    while True:
        now = datetime.now(_tz())
        nxt = now.replace(hour=config.WEATHER_REFRESH_HOUR, minute=5, second=0, microsecond=0)
        if nxt <= now:
            nxt += timedelta(days=1)
        wait = (nxt - now).total_seconds()
        if not ok:
            wait = min(wait, RETRY_SECONDS)
        await asyncio.sleep(wait)
        ok = await _catch_up() is not None


def kick(fn, *args) -> None:
    """Fire-and-forget a fetch from a request handler (any thread)."""
    events.spawn(_run(fn, *args))
