import asyncio
import threading
from datetime import timedelta

from fastapi.testclient import TestClient

from app import analytics, config, db, events, main, weather

from .conftest import wait_for


def _harvest(client, **kw):
    body = {"date": "2025-07-01", "crop_name": "Tomato", "weight_g": 200, **kw}
    r = client.post("/api/harvests", json=body)
    assert r.status_code == 201, r.text
    return r.json()


# ---------- settings / weather triggers (ran in a worker thread) ----------

def test_saving_location_starts_backfill(client, fake_weather):
    r = client.patch("/api/settings", json={"lat": 40.0, "lon": -75.0, "location_name": "Somewhere"})
    assert r.status_code == 200, r.text
    assert r.json()["location_name"] == "Somewhere"
    assert wait_for(lambda: db.get_setting("backfill_done") == "1")
    assert db.weather_count() > 0


def test_fresh_install_has_no_location_and_fetches_nothing(fake_weather, monkeypatch):
    for suffix in ("", "-wal", "-shm"):
        p = config.DB_PATH.with_name(config.DB_PATH.name + suffix)
        if p.exists():
            p.unlink()
    monkeypatch.setattr(config, "DEFAULT_LAT", None)
    monkeypatch.setattr(config, "DEFAULT_LON", None)
    monkeypatch.setattr(config, "DEFAULT_LOCATION", "")
    with TestClient(main.app) as c:
        s = c.get("/api/settings").json()
        assert s["lat"] is None and s["lon"] is None and s["location_name"] == ""
        assert c.get("/api/harvests").json() == []
        assert weather.location() is None
    assert fake_weather.calls == []


def test_location_pick_sets_timezone(client, fake_weather):
    r = client.patch("/api/settings", json={"lat": 51.5, "lon": -0.13, "location_name": "London", "timezone": "Europe/London"})
    assert r.status_code == 200, r.text
    assert r.json()["timezone"] == "Europe/London"


def test_bad_timezone_rejected_without_partial_save(client):
    before = client.get("/api/settings").json()
    r = client.patch("/api/settings", json={"location_name": "Nowhere", "timezone": "Mars/Olympus"})
    assert r.status_code == 422
    after = client.get("/api/settings").json()
    assert after["location_name"] == before["location_name"]
    assert after["timezone"] == before["timezone"]


def test_refresh_and_backfill_endpoints(client, fake_weather):
    assert client.post("/api/weather/refresh", json={"days": 3}).status_code == 200
    r = client.post("/api/weather/backfill", json={"start": "2025-09-01"})
    assert r.status_code == 200
    assert r.json()["start"] == "2025-09-01"
    assert wait_for(lambda: db.get_weather("2025-09-01") is not None)


def test_refresh_reaches_back_to_fill_a_gap(client, fake_weather):
    today = weather.today_local()
    old = (today - timedelta(days=20)).isoformat()
    db.upsert_weather_auto([{"date": old, "tmax_c": 1, "tmin_c": 0, "precip_mm": 0, "sunshine_s": 0}])
    fake_weather.calls.clear()
    weather.refresh_recent(7)
    start, end = fake_weather.calls[-1]
    assert start.isoformat() == old and end == today


# ---------- live events ----------

def test_publish_from_worker_thread_wakes_subscriber_immediately():
    async def scenario():
        events.bind_loop(asyncio.get_running_loop())
        q = events.subscribe()
        try:
            threading.Thread(target=events.publish, args=("harvests", {"id": 1})).start()
            return await asyncio.wait_for(q.get(), timeout=1)
        finally:
            events.unsubscribe(q)
    assert '"harvests"' in asyncio.run(scenario())


# ---------- crops & varieties ----------

def test_blank_crop_rename_rejected(client):
    c = client.post("/api/crops", json={"name": "Tomato"}).json()
    assert client.patch(f"/api/crops/{c['id']}", json={"name": "   "}).status_code == 400
    assert client.patch(f"/api/crops/{c['id']}", json={"name": " Roma "}).json()["name"] == "Roma"


def test_crop_rename_collision_is_400(client):
    client.post("/api/crops", json={"name": "Tomato"})
    b = client.post("/api/crops", json={"name": "Pepper"}).json()
    assert client.patch(f"/api/crops/{b['id']}", json={"name": "tomato"}).status_code == 400


def test_variety_rename_validation(client):
    c = client.post("/api/crops", json={"name": "Tomato"}).json()
    v1 = client.post("/api/varieties", json={"crop_id": c["id"], "name": "Roma"}).json()
    client.post("/api/varieties", json={"crop_id": c["id"], "name": "Sungold"})
    assert client.patch(f"/api/varieties/{v1['id']}", json={"name": " "}).status_code == 400
    assert client.patch(f"/api/varieties/{v1['id']}", json={"name": "sungold"}).status_code == 400


# ---------- harvests & plantings ----------

def test_harvest_variety_must_match_crop(client):
    t = client.post("/api/crops", json={"name": "Tomato"}).json()
    p = client.post("/api/crops", json={"name": "Pepper"}).json()
    v = client.post("/api/varieties", json={"crop_id": t["id"], "name": "Roma"}).json()
    r = client.post("/api/harvests", json={"date": "2025-07-01", "crop_id": p["id"], "variety_id": v["id"], "weight_g": 10})
    assert r.status_code == 400


def test_changing_harvest_crop_clears_variety_and_planting(client):
    pl = client.post("/api/plantings", json={"crop_name": "Tomato", "variety_name": "Roma", "season": 2025}).json()
    h = _harvest(client, variety_id=pl["variety_id"], planting_id=pl["id"])
    pepper = client.post("/api/crops", json={"name": "Pepper"}).json()
    h2 = client.patch(f"/api/harvests/{h['id']}", json={"crop_id": pepper["id"]}).json()
    assert h2["variety_id"] is None and h2["planting_id"] is None


def test_planting_crop_change_blocked_when_harvests_linked(client):
    pl = client.post("/api/plantings", json={"crop_name": "Tomato", "season": 2025}).json()
    _harvest(client, planting_id=pl["id"])
    pepper = client.post("/api/crops", json={"name": "Pepper"}).json()
    r = client.patch(f"/api/plantings/{pl['id']}", json={"crop_id": pepper["id"]})
    assert r.status_code == 400
    # Same crop (as the edit form always sends it) is fine.
    r = client.patch(f"/api/plantings/{pl['id']}", json={"crop_id": pl["crop_id"], "plant_count": 4})
    assert r.status_code == 200 and r.json()["g_per_plant"] == 50


def test_bad_date_is_400(client):
    r = client.post("/api/harvests", json={"date": "07/01/2025", "crop_name": "Tomato", "weight_g": 1})
    assert r.status_code == 400


# ---------- import ----------

CSV = "Date,Crop,Weight (g)\n2025-07-01,Tomato,200\n2025-07-01,Tomato,200\n07/02/2025,Bean,55\n"


def _import(client, text):
    r = client.post("/api/import/csv", files={"file": ("h.csv", text.encode(), "text/csv")})
    assert r.status_code == 200, r.text
    return r.json()


def test_import_keeps_identical_rows_and_is_idempotent(client):
    assert _import(client, CSV) == {"added": 3, "skipped": 0, "errors": []}
    assert _import(client, CSV) == {"added": 0, "skipped": 3, "errors": []}
    assert db.harvest_count() == 3


def test_import_reports_bad_lines(client):
    res = _import(client, "Date,Crop,Weight (g)\nnot-a-date,Tomato,1\n2025-07-01,,5\n")
    assert res["added"] == 0 and len(res["errors"]) == 2


def test_export_round_trip(client):
    _import(client, CSV)
    text = client.get("/api/export.csv").text
    assert text.splitlines()[0].startswith("Date,Crop")
    assert _import(client, text)["skipped"] == 3


# ---------- weather overrides ----------

def test_manual_weather_survives_refresh(client):
    db.upsert_weather_auto([{"date": "2025-07-01", "tmax_c": 20, "tmin_c": 10, "precip_mm": 0, "sunshine_s": 0}])
    client.put("/api/weather/2025-07-01", json={"tmax_c": 25})
    db.upsert_weather_auto([{"date": "2025-07-01", "tmax_c": 21, "tmin_c": 11, "precip_mm": 0, "sunshine_s": 0}])
    w = db.get_weather("2025-07-01")
    assert w["source"] == "manual" and w["tmax_c"] == 25


def test_note_only_keeps_day_auto(client):
    db.upsert_weather_auto([{"date": "2025-07-01", "tmax_c": 20, "tmin_c": 10, "precip_mm": 0, "sunshine_s": 0}])
    client.put("/api/weather/2025-07-01", json={"notes": "hail"})
    w = db.get_weather("2025-07-01")
    assert w["source"] == "auto" and w["notes"] == "hail"


# ---------- analytics ----------

def test_gdd():
    assert analytics._gdd(30, 10) == 10        # (30+10)/2 - 10
    assert analytics._gdd(40, 20) == 15        # max capped at 30
    assert analytics._gdd(20, 0) == 5          # min raised to base
    assert analytics._gdd(8, 2) == 0           # never negative


def test_season_stats(client):
    _harvest(client, date="2025-07-01", weight_g=100)
    _harvest(client, date="2025-07-09", weight_g=300, crop_name="Bean")
    s = client.get("/api/stats/season/2025").json()
    assert s["summary"]["total_g"] == 400
    assert s["summary"]["top_crop"]["name"] == "Bean"
    assert len(s["weekly"]) == 2


def test_pulse_compares_to_same_date_last_year(client):
    from datetime import date
    _harvest(client, date="2024-06-01", weight_g=100)
    _harvest(client, date="2024-09-01", weight_g=900)     # after "today" last year
    _harvest(client, date="2025-05-20", weight_g=50)
    _harvest(client, date="2025-05-28", weight_g=60)
    _harvest(client, date="2025-06-01", weight_g=70)
    _harvest(client, date="2025-06-04", weight_g=80)
    p = analytics.pulse(date(2025, 6, 15))
    assert p["season_g"] == 260 and p["prev_to_date_g"] == 100 and p["prev_total_g"] == 1000
    assert p["week_g"] == 0 and p["today_g"] == 0
    tom = p["crops"][0]
    assert tom["days_since"] == 11 and tom["pick_gap_days"] == 4
    assert tom["due"] is True
    assert p["typical_g"][str(tom["crop_id"])] == 75


def test_season_prev_is_to_date_only_while_in_progress(client):
    from datetime import date
    _harvest(client, date="2024-06-01", weight_g=100)
    _harvest(client, date="2024-09-01", weight_g=900)
    _harvest(client, date="2025-06-01", weight_g=10)
    cur = analytics.season(2025, date(2025, 6, 15))["summary"]["prev"]
    assert cur == {"season": 2024, "total_g": 1000, "to_date_g": 100, "partial": True}
    done = analytics.season(2025, date(2026, 1, 5))["summary"]["prev"]
    assert done["partial"] is False and done["to_date_g"] == 1000


def test_static_files_revalidate(client):
    r = client.get("/app.js")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"
    assert client.get("/app.js", headers={"if-none-match": r.headers["etag"]}).status_code == 304
