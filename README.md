# Garden Tracker

A small self-hosted app for logging garden harvests, recording daily weather,
and comparing yields year over year. Built the same way as `recipe_book`:
FastAPI + SQLite backend, one static vanilla-JS page, systemd in a Debian LXC,
reachable on the LAN as **http://garden.local**. No accounts — local network only.

## What it does

- **Log** — phone-first harvest entry: tap a crop, punch the weight on a big
  keypad (touch screens; a normal input with a mouse), Save. Shows the crop's
  typical pick and warns when a weight looks like a unit slip. Saves and deletes
  show an Undo toast instead of a confirm dialog. "Repeat" copies the previous
  entry's crop/variety/planting.
- **Season so far** (on the Log page) — season total vs last year *by the same
  date*, last 7 days, today, and per-crop bars with days since the last pick.
  Crops overdue against their usual picking interval are flagged "check".
- **Harvests** — day-grouped list with season/crop filters, search, edit/delete, CSV
  export, and CSV import (accepts the Notion export: `Date, Crop, Weight (g)`).
- **Weather** — one row per day: high, low, rain, sunshine, harvest total, notes.
  Fetched automatically from [Open-Meteo](https://open-meteo.com) (free, no key)
  every morning; a one-time backfill fills history. Tap a day to correct values
  or add a note ("frost", "hail"); edited days are marked *manual* and never
  overwritten.
- **Plantings** — sow date, set-out date, plant count, location. Harvests linked
  to a planting give yield per plant and days-to-first-harvest.
- **Analyze** — per-season stat tiles, cumulative yield curves by season (all
  crops or one crop), weekly stacked columns by crop, a crop × season YoY table
  with % change, growing degree days by season, frost dates, monthly weather.
- **Settings** — location search (geocoded), units, backfill, crop colours,
  archive/rename/delete crops, manage varieties.
- Metric ⇄ imperial toggle (g/°C/mm vs oz·lb/°F/in). Everything is stored metric.
- Live updates between devices via server-sent events.

## Layout

```
app/          FastAPI backend
  main.py       routes            db.py        SQLite schema + CRUD
  weather.py    Open-Meteo fetch + daily scheduler
  analytics.py  YoY / season / GDD queries
  importer.py   CSV import/export   seed.py    `python -m app.seed`
web/          index.html + app.js (no build step, no CDN dependencies)
data/         garden.db (created on first run), seed/garden_produce.csv
deploy/       install.sh, garden.service, garden.env.example, backup.sh
```

## Run locally

```bash
python3 -m venv venv && venv/bin/pip install -r requirements.txt
venv/bin/python -m app.seed                      # optional: import data/seed/*.csv
venv/bin/uvicorn app.main:app --reload --timeout-graceful-shutdown 2 --port 8000
```

Open http://localhost:8000. Weather starts backfilling a couple of seconds after
boot (see the Weather tab's status line).

## Deploy to a Proxmox LXC

1. Create an unprivileged Debian 12 (or Ubuntu 24.04) container, hostname
   **garden**, on your LAN bridge. 1 core / 512 MB / 4 GB is plenty. Give it a
   fixed address, either a DHCP reservation on the router or a static IPv4 in
   Proxmox (Network tab), and set IPv6 to static/none unless you use it.
   Make sure it has outbound internet for the weather fetch.
2. Inside the container, as root:

   ```bash
   apt-get update && apt-get install -y git
   git clone https://github.com/rodavok/garden_tracker /opt/garden
   /opt/garden/deploy/install.sh
   systemctl enable --now garden
   ```

   (For a private repo, clone with a token or copy the folder in with `pct push`.)
3. Open **http://garden.local** from anything on the LAN. mDNS is provided by
   `avahi-daemon`, which the installer enables; Windows, macOS, iOS, Android and
   most Linux desktops resolve `.local` names out of the box. If your router or
   Pi-hole does local DNS instead, point `garden.local` (or any name) at the
   container's IP there.

   If `garden.local` stops resolving now and then, run
   `journalctl -u avahi-daemon -n 50` in the container. "fork() failed" means
   the process limit shared with other containers (the installer removes it);
   "host name conflict" means it renamed itself to `garden-2.local`.
4. Settings → confirm the location (defaults to Tonawanda, NY) and let the
   backfill run.

Updating later:

```bash
cd /opt/garden && git pull && venv/bin/pip install -r requirements.txt && systemctl restart garden
```

### Configuration

`/etc/garden/garden.env` (see `deploy/garden.env.example`) — all optional:
`GARDEN_LAT`, `GARDEN_LON`, `GARDEN_LOCATION`, `GARDEN_TZ`,
`GARDEN_BACKFILL_START`, `GARDEN_WEATHER_HOUR`, `GARDEN_WEATHER=0` (disable
fetching), `GARDEN_DATA` / `GARDEN_DB` (store the database elsewhere).

### Backups

`deploy/backup.sh` makes a consistent gzip copy of the SQLite file using the
online-backup API. Nightly at 03:15, keeping 30:

```
15 3 * * * GARDEN_BACKUP_DIR=/mnt/backups/garden /opt/garden/deploy/backup.sh
```

(`crontab -u garden -e`). Restoring is `gunzip -c garden-….db.gz > data/garden.db`
with the service stopped.

## API

All under `/api`, JSON. Useful ones for scripting:

| Method | Path | |
|---|---|---|
| GET/POST | `/harvests` | filters: `season`, `crop_id`, `start`, `end`, `limit` |
| PATCH/DELETE | `/harvests/{id}` | |
| GET | `/harvests/last` | for "repeat last" |
| GET/POST, PATCH/DELETE | `/plantings`, `/plantings/{id}` | includes computed yield stats |
| GET/POST, PATCH/DELETE | `/crops`, `/varieties` | |
| GET | `/weather?start=&end=` | |
| PUT/DELETE | `/weather/{date}` | manual override / reset to auto |
| POST | `/weather/refresh`, `/weather/backfill` | |
| GET | `/stats/overview`, `/stats/season/{year}`, `/stats/cumulative?crop_id=`, `/stats/gdd` | |
| POST | `/import/csv` (multipart `file`) · GET `/export.csv` | |
| GET | `/events` (SSE) · `/health` | |

Interactive docs at `/docs`.

## Notes

- Growing degree days use base 10 °C with the daily max capped at 30 °C.
- "Frost" = a day whose low is ≤ 0 °C. Last spring frost is the latest before
  July 1; first fall frost the earliest on/after July 1.
- The weather backfill starts at `backfill_start` (default 2025-08-01). Run it
  from an earlier date in Settings if you want full-year frost/GDD comparisons.
- Open-Meteo's archive lags ~5 days; the last week is filled from the forecast
  API and corrected on later refreshes. Manually edited days are left alone.
