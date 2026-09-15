"""Central configuration and filesystem paths for the Garden Tracker backend.

Everything is overridable through GARDEN_* environment variables (see
deploy/garden.env.example). Location values here are only the first-run
defaults; once the app has started they live in the settings table and are
edited from the Settings page.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = Path(os.environ.get("GARDEN_DATA", ROOT / "data"))
DB_PATH = Path(os.environ.get("GARDEN_DB", DATA_DIR / "garden.db"))
WEB_DIR = ROOT / "web"
SEED_CSV = DATA_DIR / "seed" / "garden_produce.csv"

# First-run defaults for the weather location (City of Tonawanda, NY).
DEFAULT_LAT = float(os.environ.get("GARDEN_LAT", "43.0203"))
DEFAULT_LON = float(os.environ.get("GARDEN_LON", "-78.8803"))
DEFAULT_LOCATION = os.environ.get("GARDEN_LOCATION", "Tonawanda, New York")
TIMEZONE = os.environ.get("GARDEN_TZ", "America/New_York")

# Earliest date the one-time weather backfill reaches back to.
BACKFILL_START = os.environ.get("GARDEN_BACKFILL_START", "2025-08-01")
# Local hour (0-23) at which the daily weather refresh runs.
WEATHER_REFRESH_HOUR = int(os.environ.get("GARDEN_WEATHER_HOUR", "6"))
# Set to 0 to disable all outbound weather fetching (manual entry still works).
WEATHER_ENABLED = os.environ.get("GARDEN_WEATHER", "1") not in ("0", "false", "no")

DATA_DIR.mkdir(parents=True, exist_ok=True)
