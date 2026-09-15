"""Garden Tracker backend — FastAPI app.

Serves the static front-end plus a JSON API over SQLite. Weather is fetched
from Open-Meteo by a background task (see weather.py). Local network only:
no auth by design.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import date
from typing import Optional

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import analytics, db, events, importer, weather
from .config import WEB_DIR, WEATHER_ENABLED
from .models import (
    Crop, CropCreate, CropUpdate, Harvest, HarvestCreate, HarvestUpdate,
    Planting, PlantingCreate, PlantingUpdate, Settings, SettingsUpdate,
    Variety, VarietyCreate, VarietyUpdate, WeatherDay, WeatherManual, WeatherRange,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    task = asyncio.create_task(weather.scheduler())
    yield
    task.cancel()


app = FastAPI(title="Garden Tracker", lifespan=lifespan)


def _date(s: str) -> str:
    try:
        return date.fromisoformat(s).isoformat()
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Bad date: {s!r} (use YYYY-MM-DD)")


def _resolve_crop(crop_id: Optional[int], crop_name: Optional[str]) -> int:
    if crop_id is not None:
        if not db.get_crop(crop_id):
            raise HTTPException(status_code=404, detail="Crop not found")
        return crop_id
    if crop_name and crop_name.strip():
        return db.get_or_create_crop(crop_name)["id"]
    raise HTTPException(status_code=400, detail="crop_id or crop_name is required")


def _resolve_variety(crop_id: int, variety_id: Optional[int], variety_name: Optional[str]) -> Optional[int]:
    if variety_id is not None:
        v = db.get_variety(variety_id)
        if not v or v["crop_id"] != crop_id:
            raise HTTPException(status_code=400, detail="Variety does not belong to that crop")
        return variety_id
    if variety_name and variety_name.strip():
        return db.get_or_create_variety(crop_id, variety_name)["id"]
    return None


# ---------- settings ----------

def _settings() -> Settings:
    s = db.all_settings()
    def f(k):
        try:
            return float(s[k]) if s.get(k) not in (None, "") else None
        except ValueError:
            return None
    return Settings(
        lat=f("lat"), lon=f("lon"), location_name=s.get("location_name") or "",
        timezone=s.get("timezone") or "America/New_York",
        backfill_start=s.get("backfill_start") or "2025-08-01",
        backfill_done=s.get("backfill_done") == "1",
        weather_enabled=WEATHER_ENABLED,
        weather_last_fetch=s.get("weather_last_fetch"),
        weather_last_error=s.get("weather_last_error") or "",
    )


@app.get("/api/settings", response_model=Settings)
def get_settings():
    return _settings()


@app.patch("/api/settings", response_model=Settings)
def update_settings(patch: SettingsUpdate):
    data = patch.model_dump(exclude_unset=True)
    moved = False
    for k, v in data.items():
        if k == "backfill_start" and v:
            v = _date(v)
        if k in ("lat", "lon") and v is not None:
            moved = True
        db.set_setting(k, v)
    if moved and WEATHER_ENABLED:
        db.set_setting("backfill_done", "0")
        weather.kick(weather.backfill)
    return _settings()


@app.get("/api/geocode")
def geocode(q: str = Query(min_length=2)):
    try:
        return weather.geocode(q)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Geocoding failed: {exc}")


# ---------- crops ----------

@app.get("/api/crops", response_model=list[Crop])
def list_crops(include_archived: bool = True):
    return db.list_crops(include_archived)


@app.post("/api/crops", response_model=Crop, status_code=201)
def create_crop(payload: CropCreate):
    try:
        c = db.get_or_create_crop(payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    events.publish("crops", {})
    return c


@app.patch("/api/crops/{crop_id}", response_model=Crop)
def update_crop(crop_id: int, patch: CropUpdate):
    if not db.get_crop(crop_id):
        raise HTTPException(status_code=404, detail="Crop not found")
    try:
        c = db.update_crop(crop_id, patch.model_dump(exclude_unset=True))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not update crop: {exc}")
    events.publish("crops", {})
    return c


@app.delete("/api/crops/{crop_id}", status_code=204)
def delete_crop(crop_id: int):
    if not db.delete_crop(crop_id):
        raise HTTPException(status_code=404, detail="Crop not found")
    events.publish("crops", {})
    events.publish("harvests", {})


# ---------- varieties ----------

@app.get("/api/varieties", response_model=list[Variety])
def list_varieties(crop_id: Optional[int] = None):
    return db.list_varieties(crop_id)


@app.post("/api/varieties", response_model=Variety, status_code=201)
def create_variety(payload: VarietyCreate):
    if not db.get_crop(payload.crop_id):
        raise HTTPException(status_code=404, detail="Crop not found")
    try:
        v = db.get_or_create_variety(payload.crop_id, payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    events.publish("crops", {})
    return v


@app.patch("/api/varieties/{variety_id}", response_model=Variety)
def update_variety(variety_id: int, patch: VarietyUpdate):
    if not db.get_variety(variety_id):
        raise HTTPException(status_code=404, detail="Variety not found")
    if patch.name is not None:
        db.update_variety(variety_id, patch.name)
    events.publish("crops", {})
    return db.get_variety(variety_id)


@app.delete("/api/varieties/{variety_id}", status_code=204)
def delete_variety(variety_id: int):
    if not db.delete_variety(variety_id):
        raise HTTPException(status_code=404, detail="Variety not found")
    events.publish("crops", {})


# ---------- plantings ----------

@app.get("/api/plantings", response_model=list[Planting])
def list_plantings(season: Optional[int] = None, crop_id: Optional[int] = None):
    return db.list_plantings(season, crop_id)


@app.post("/api/plantings", response_model=Planting, status_code=201)
def create_planting(payload: PlantingCreate):
    crop_id = _resolve_crop(payload.crop_id, payload.crop_name)
    variety_id = _resolve_variety(crop_id, payload.variety_id, payload.variety_name)
    sow = _date(payload.sow_date) if payload.sow_date else None
    tp = _date(payload.transplant_date) if payload.transplant_date else None
    season = payload.season or int((tp or sow or date.today().isoformat())[:4])
    p = db.insert_planting({
        "crop_id": crop_id, "variety_id": variety_id, "season": season, "sow_date": sow,
        "transplant_date": tp, "plant_count": payload.plant_count,
        "location": payload.location, "notes": payload.notes,
    })
    events.publish("plantings", {})
    return p


@app.patch("/api/plantings/{planting_id}", response_model=Planting)
def update_planting(planting_id: int, patch: PlantingUpdate):
    p = db.get_planting(planting_id)
    if not p:
        raise HTTPException(status_code=404, detail="Planting not found")
    data = patch.model_dump(exclude_unset=True)
    crop_id = data.get("crop_id", p["crop_id"])
    if "crop_id" in data:
        _resolve_crop(crop_id, None)
        if crop_id != p["crop_id"] and "variety_id" not in data and "variety_name" not in data:
            data["variety_id"] = None
    vname = data.pop("variety_name", None)
    if vname is not None or "variety_id" in data:
        data["variety_id"] = _resolve_variety(crop_id, data.get("variety_id"), vname)
    for k in ("sow_date", "transplant_date"):
        if data.get(k):
            data[k] = _date(data[k])
    p = db.update_planting(planting_id, data)
    events.publish("plantings", {})
    return p


@app.delete("/api/plantings/{planting_id}", status_code=204)
def delete_planting(planting_id: int):
    if not db.delete_planting(planting_id):
        raise HTTPException(status_code=404, detail="Planting not found")
    events.publish("plantings", {})


# ---------- harvests ----------

@app.get("/api/harvests", response_model=list[Harvest])
def list_harvests(
    season: Optional[int] = None, crop_id: Optional[int] = None,
    start: Optional[str] = None, end: Optional[str] = None, limit: Optional[int] = None,
):
    return db.list_harvests(season, crop_id, start, end, limit)


@app.get("/api/harvests/last", response_model=Optional[Harvest])
def get_last_harvest():
    return db.last_harvest()


@app.get("/api/harvests/{harvest_id}", response_model=Harvest)
def get_harvest(harvest_id: int):
    h = db.get_harvest(harvest_id)
    if not h:
        raise HTTPException(status_code=404, detail="Harvest not found")
    return h


@app.post("/api/harvests", response_model=Harvest, status_code=201)
def create_harvest(payload: HarvestCreate):
    crop_id = _resolve_crop(payload.crop_id, payload.crop_name)
    variety_id = _resolve_variety(crop_id, payload.variety_id, payload.variety_name)
    if payload.planting_id is not None:
        p = db.get_planting(payload.planting_id)
        if not p or p["crop_id"] != crop_id:
            raise HTTPException(status_code=400, detail="Planting does not belong to that crop")
    h = db.insert_harvest({
        "date": _date(payload.date), "crop_id": crop_id, "variety_id": variety_id,
        "planting_id": payload.planting_id, "weight_g": payload.weight_g, "notes": payload.notes,
    })
    events.publish("harvests", {"id": h["id"]})
    return h


@app.patch("/api/harvests/{harvest_id}", response_model=Harvest)
def update_harvest(harvest_id: int, patch: HarvestUpdate):
    h = db.get_harvest(harvest_id)
    if not h:
        raise HTTPException(status_code=404, detail="Harvest not found")
    data = patch.model_dump(exclude_unset=True)
    crop_id = data.get("crop_id", h["crop_id"])
    if "crop_id" in data:
        _resolve_crop(crop_id, None)
        if crop_id != h["crop_id"]:
            data.setdefault("variety_id", None)
            data.setdefault("planting_id", None)
    vname = data.pop("variety_name", None)
    if vname is not None or "variety_id" in data:
        data["variety_id"] = _resolve_variety(crop_id, data.get("variety_id"), vname)
    if data.get("planting_id") is not None:
        p = db.get_planting(data["planting_id"])
        if not p or p["crop_id"] != crop_id:
            raise HTTPException(status_code=400, detail="Planting does not belong to that crop")
    if "date" in data:
        data["date"] = _date(data["date"])
    h = db.update_harvest(harvest_id, data)
    events.publish("harvests", {"id": harvest_id})
    return h


@app.delete("/api/harvests/{harvest_id}", status_code=204)
def delete_harvest(harvest_id: int):
    if not db.delete_harvest(harvest_id):
        raise HTTPException(status_code=404, detail="Harvest not found")
    events.publish("harvests", {"id": harvest_id})


# ---------- weather ----------

@app.get("/api/weather", response_model=list[WeatherDay])
def list_weather(start: Optional[str] = None, end: Optional[str] = None):
    return db.list_weather(_date(start) if start else None, _date(end) if end else None)


@app.get("/api/weather/{day}", response_model=Optional[WeatherDay])
def get_weather(day: str):
    return db.get_weather(_date(day))


@app.put("/api/weather/{day}", response_model=WeatherDay)
def set_weather(day: str, payload: WeatherManual):
    w = db.set_weather_manual(_date(day), payload.model_dump(exclude_unset=True))
    events.publish("weather", {"date": day})
    return w


@app.delete("/api/weather/{day}", response_model=Optional[WeatherDay])
def reset_weather(day: str):
    """Drop a manual override and re-fetch that day from Open-Meteo."""
    d = _date(day)
    db.delete_weather(d)
    if WEATHER_ENABLED and weather.location():
        try:
            w = weather.refetch_day(d)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Cleared, but re-fetch failed: {exc}")
    else:
        w = None
    events.publish("weather", {"date": d})
    return w


@app.post("/api/weather/refresh")
def refresh_weather(payload: WeatherRange | None = None):
    if not WEATHER_ENABLED:
        raise HTTPException(status_code=400, detail="Weather fetching is disabled (GARDEN_WEATHER=0)")
    if not weather.location():
        raise HTTPException(status_code=400, detail="Set a location in Settings first")
    days = (payload.days if payload and payload.days else 7)
    weather.kick(weather.refresh_recent, days)
    return {"started": True, "days": days}


@app.post("/api/weather/backfill")
def backfill_weather(payload: WeatherRange | None = None):
    if not WEATHER_ENABLED:
        raise HTTPException(status_code=400, detail="Weather fetching is disabled (GARDEN_WEATHER=0)")
    if not weather.location():
        raise HTTPException(status_code=400, detail="Set a location in Settings first")
    start = _date(payload.start) if payload and payload.start else None
    if start:
        db.set_setting("backfill_start", start)
    weather.kick(weather.backfill, start)
    return {"started": True, "start": start or db.get_setting("backfill_start")}


# ---------- analysis ----------

@app.get("/api/stats/overview")
def stats_overview():
    return analytics.overview()


@app.get("/api/stats/season/{year}")
def stats_season(year: int):
    return analytics.season(year)


@app.get("/api/stats/cumulative")
def stats_cumulative(crop_id: Optional[int] = None):
    return analytics.cumulative(crop_id)


@app.get("/api/stats/gdd")
def stats_gdd():
    return analytics.gdd_curves()


@app.get("/api/seasons")
def list_seasons():
    return db.seasons()


# ---------- import / export ----------

@app.post("/api/import/csv")
async def import_csv(file: UploadFile = File(...)):
    raw = await file.read()
    try:
        result = importer.import_csv(raw.decode("utf-8-sig"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    events.publish("harvests", {})
    events.publish("crops", {})
    return result


@app.get("/api/export.csv")
def export_csv():
    return PlainTextResponse(
        importer.export_csv(), media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="garden_harvests.csv"'},
    )


# ---------- live updates (SSE) ----------

@app.get("/api/events")
async def stream_events(request: Request):
    async def gen():
        q = events.subscribe()
        try:
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=20)
                    yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            events.unsubscribe(q)
    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/health")
def health():
    return {"ok": True, "harvests": db.harvest_count(), "weather_days": db.weather_count()}


# ---------- static files (mounted last so /api wins) ----------
if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
