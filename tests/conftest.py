"""Test setup: a throwaway data dir and no real network calls.

config.py reads GARDEN_* at import time, so the environment is set here,
before anything imports the app.
"""
import os
import tempfile
import time
from datetime import date, timedelta

os.environ["GARDEN_DATA"] = tempfile.mkdtemp(prefix="garden-test-")
os.environ["GARDEN_WEATHER"] = "1"
# A configured install. test_api.py clears these to test a fresh one.
os.environ["GARDEN_LAT"] = "40.0"
os.environ["GARDEN_LON"] = "-75.0"
os.environ["GARDEN_TZ"] = "America/New_York"

import pytest
from fastapi.testclient import TestClient

from app import config, db, main, weather


class FakeWeather:
    """Stands in for Open-Meteo: returns one mild day per date requested."""

    def __init__(self):
        self.calls = []

    def __call__(self, start: date, end: date):
        self.calls.append((start, end))
        out, d = [], start
        while d <= end:
            out.append({"date": d.isoformat(), "tmax_c": 20.0, "tmin_c": 10.0, "precip_mm": 0.0, "sunshine_s": 3600.0})
            d += timedelta(days=1)
        return out


@pytest.fixture
def fake_weather(monkeypatch):
    fw = FakeWeather()
    monkeypatch.setattr(weather, "fetch_range", fw)
    monkeypatch.setattr(weather, "geocode", lambda q: [])
    return fw


@pytest.fixture
def client(fake_weather):
    for suffix in ("", "-wal", "-shm"):
        p = config.DB_PATH.with_name(config.DB_PATH.name + suffix)
        if p.exists():
            p.unlink()
    with TestClient(main.app) as c:
        yield c


def wait_for(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False
