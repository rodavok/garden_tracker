"""Central configuration and filesystem paths for the Garden Tracker backend.

Everything is overridable through GARDEN_* environment variables (see
deploy/garden.env.example). Location values here are only the first-run
defaults; once the app has started they live in the settings table and are
edited from the Settings page.
"""
import os
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = Path(os.environ.get("GARDEN_DATA", ROOT / "data"))
DB_PATH = Path(os.environ.get("GARDEN_DB", DATA_DIR / "garden.db"))
WEB_DIR = ROOT / "web"


def _float_env(name: str):
    v = os.environ.get(name, "").strip()
    return float(v) if v else None


# Optional first-run location. Unset by default: the app asks for a location
# on first open (Settings), and weather fetching waits until one is chosen.
DEFAULT_LAT = _float_env("GARDEN_LAT")
DEFAULT_LON = _float_env("GARDEN_LON")
DEFAULT_LOCATION = os.environ.get("GARDEN_LOCATION", "")
# Picking a place in Settings replaces this with that place's time zone.
TIMEZONE = os.environ.get("GARDEN_TZ", "UTC")

# Earliest date the one-time weather backfill reaches back to
# (default: January 1 of last year, so there's a full season to compare).
BACKFILL_START = os.environ.get("GARDEN_BACKFILL_START", f"{date.today().year - 1}-01-01")
# Local hour (0-23) at which the daily weather refresh runs.
WEATHER_REFRESH_HOUR = int(os.environ.get("GARDEN_WEATHER_HOUR", "6"))
# Set to 0 to disable all outbound weather fetching (manual entry still works).
WEATHER_ENABLED = os.environ.get("GARDEN_WEATHER", "1") not in ("0", "false", "no")

DATA_DIR.mkdir(parents=True, exist_ok=True)
