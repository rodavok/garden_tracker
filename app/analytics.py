"""Yield and weather analysis queries. All weights in grams, temps in °C."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from statistics import median
from typing import Any, Dict, List, Optional

from . import db

GDD_BASE_C = 10.0   # growing degree days base (warm-season vegetables)
GDD_CAP_C = 30.0


def _doy(d: str) -> int:
    return date.fromisoformat(d).timetuple().tm_yday


def _week_start(d: str) -> str:
    dt = date.fromisoformat(d)
    return (dt - timedelta(days=dt.weekday())).isoformat()


def overview() -> Dict[str, Any]:
    """Crops × seasons matrix for the YoY table."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT c.id, c.name, c.color, c.archived, substr(h.date,1,4) AS season, "
            "       SUM(h.weight_g) AS total_g, COUNT(h.id) AS harvests, MIN(h.date) AS first, MAX(h.date) AS last "
            "FROM harvests h JOIN crops c ON c.id = h.crop_id "
            "GROUP BY c.id, season ORDER BY c.name COLLATE NOCASE, season"
        ).fetchall()
    seasons = db.seasons()
    crops: Dict[int, Dict[str, Any]] = {}
    season_totals: Dict[str, Dict[str, Any]] = {str(s): {"total_g": 0, "harvests": 0, "crops": 0} for s in seasons}
    for r in rows:
        c = crops.setdefault(r["id"], {
            "id": r["id"], "name": r["name"], "color": r["color"], "archived": bool(r["archived"]),
            "by_season": {}, "total_g": 0, "harvests": 0,
        })
        c["by_season"][r["season"]] = {
            "total_g": r["total_g"], "harvests": r["harvests"], "first": r["first"], "last": r["last"],
        }
        c["total_g"] += r["total_g"]
        c["harvests"] += r["harvests"]
        st = season_totals.setdefault(r["season"], {"total_g": 0, "harvests": 0, "crops": 0})
        st["total_g"] += r["total_g"]
        st["harvests"] += r["harvests"]
        st["crops"] += 1
    crop_list = sorted(crops.values(), key=lambda c: -c["total_g"])
    return {"seasons": seasons, "crops": crop_list, "season_totals": season_totals}


def cumulative(crop_id: Optional[int] = None) -> Dict[str, Any]:
    """Cumulative yield by day-of-year, one series per season (for YoY curves)."""
    where, params = "", []
    if crop_id is not None:
        where, params = "WHERE crop_id = ?", [crop_id]
    with db.connect() as conn:
        rows = conn.execute(
            f"SELECT date, SUM(weight_g) AS g FROM harvests {where} GROUP BY date ORDER BY date", params
        ).fetchall()
    by_season: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    running: Dict[str, float] = defaultdict(float)
    for r in rows:
        s = r["date"][:4]
        running[s] += r["g"]
        by_season[s].append({"date": r["date"], "doy": _doy(r["date"]), "cum_g": round(running[s], 1)})
    return {"seasons": [{"season": int(s), "points": pts} for s, pts in sorted(by_season.items())]}


def gdd_curves(start_doy: int = 1) -> Dict[str, Any]:
    """Cumulative growing degree days per season from the weather table."""
    days = db.list_weather()
    by_season: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    running: Dict[str, float] = defaultdict(float)
    for w in days:
        if w["tmax_c"] is None or w["tmin_c"] is None:
            continue
        s = w["date"][:4]
        running[s] += _gdd(w["tmax_c"], w["tmin_c"])
        doy = _doy(w["date"])
        if doy >= start_doy:
            by_season[s].append({"date": w["date"], "doy": doy, "cum_gdd": round(running[s], 1)})
    return {"seasons": [{"season": int(s), "points": pts} for s, pts in sorted(by_season.items())]}


def _gdd(tmax: float, tmin: float) -> float:
    tmax = min(tmax, GDD_CAP_C)
    tmin = max(tmin, GDD_BASE_C) if tmin < GDD_BASE_C and tmax > GDD_BASE_C else tmin
    return max(0.0, (tmax + tmin) / 2 - GDD_BASE_C)


def _same_day(d: date, year: int) -> date:
    """d's month/day in another year (Feb 29 -> Feb 28)."""
    try:
        return d.replace(year=year)
    except ValueError:
        return d.replace(year=year, day=28)


def _prev_season(year: int, today: date) -> Optional[Dict[str, Any]]:
    """Last season's total, plus its total up to today's date when `year` is
    still in progress, so a half-finished season isn't compared to a full one."""
    prev = year - 1
    with db.connect() as conn:
        total = conn.execute(
            "SELECT SUM(weight_g) AS g FROM harvests WHERE substr(date,1,4) = ?", (str(prev),)
        ).fetchone()["g"]
        if total is None:
            return None
        in_progress = year == today.year
        to_date = total
        if in_progress:
            cutoff = _same_day(today, prev).isoformat()
            to_date = conn.execute(
                "SELECT COALESCE(SUM(weight_g),0) AS g FROM harvests WHERE substr(date,1,4) = ? AND date <= ?",
                (str(prev), cutoff),
            ).fetchone()["g"]
    return {"season": prev, "total_g": round(total, 1), "to_date_g": round(to_date, 1), "partial": in_progress}


def season(year: int, today: Optional[date] = None) -> Dict[str, Any]:
    today = today or date.today()
    ys = str(year)
    harvests = db.list_harvests(season=year)
    crops = {c["id"]: c for c in db.list_crops()}

    total_g = sum(h["weight_g"] for h in harvests)
    by_crop: Dict[int, Dict[str, Any]] = {}
    weekly: Dict[str, Dict[int, float]] = defaultdict(lambda: defaultdict(float))
    dates = set()
    for h in harvests:
        c = by_crop.setdefault(h["crop_id"], {
            "crop_id": h["crop_id"], "name": h["crop_name"], "color": crops.get(h["crop_id"], {}).get("color", 0),
            "total_g": 0.0, "harvests": 0, "first": h["date"], "last": h["date"], "biggest_g": 0.0,
        })
        c["total_g"] += h["weight_g"]
        c["harvests"] += 1
        c["first"] = min(c["first"], h["date"])
        c["last"] = max(c["last"], h["date"])
        c["biggest_g"] = max(c["biggest_g"], h["weight_g"])
        weekly[_week_start(h["date"])][h["crop_id"]] += h["weight_g"]
        dates.add(h["date"])
    for c in by_crop.values():
        c["share"] = (c["total_g"] / total_g) if total_g else 0
        c["total_g"] = round(c["total_g"], 1)
    crop_rows = sorted(by_crop.values(), key=lambda c: -c["total_g"])

    # Fill empty weeks between first and last so the column chart has a continuous axis.
    weekly_rows = []
    if weekly:
        wk = date.fromisoformat(min(weekly))
        last = date.fromisoformat(max(weekly))
        while wk <= last:
            k = wk.isoformat()
            weekly_rows.append({"week_start": k, "parts": {str(cid): round(g, 1) for cid, g in weekly.get(k, {}).items()}})
            wk += timedelta(days=7)

    summary = {
        "season": year,
        "total_g": round(total_g, 1),
        "harvests": len(harvests),
        "crops": len(by_crop),
        "days_with_harvest": len(dates),
        "first_date": min(dates) if dates else None,
        "last_date": max(dates) if dates else None,
        "top_crop": ({"name": crop_rows[0]["name"], "total_g": crop_rows[0]["total_g"]} if crop_rows else None),
        "prev": _prev_season(year, today),
    }

    return {
        "summary": summary,
        "by_crop": crop_rows,
        "weekly": weekly_rows,
        "weather": weather_summary(f"{ys}-01-01", f"{ys}-12-31"),
    }


def weather_summary(start: str, end: str) -> Dict[str, Any]:
    days = [d for d in db.list_weather(start, end)]
    with_t = [d for d in days if d["tmax_c"] is not None and d["tmin_c"] is not None]
    precip = [d for d in days if d["precip_mm"] is not None]
    mid = f"{start[:4]}-07-01"

    frost = [d["date"] for d in with_t if d["tmin_c"] <= 0]
    last_spring = max((f for f in frost if f < mid), default=None)
    first_fall = min((f for f in frost if f >= mid), default=None)

    monthly: Dict[str, Dict[str, Any]] = {}
    gdd_total = 0.0
    for d in days:
        m = d["date"][:7]
        mo = monthly.setdefault(m, {"month": m, "days": 0, "tmax_sum": 0.0, "tmin_sum": 0.0, "t_days": 0,
                                    "precip_mm": 0.0, "rain_days": 0, "gdd": 0.0, "sun_h": 0.0})
        mo["days"] += 1
        if d["tmax_c"] is not None and d["tmin_c"] is not None:
            mo["tmax_sum"] += d["tmax_c"]; mo["tmin_sum"] += d["tmin_c"]; mo["t_days"] += 1
            g = _gdd(d["tmax_c"], d["tmin_c"]); mo["gdd"] += g; gdd_total += g
        if d["precip_mm"] is not None:
            mo["precip_mm"] += d["precip_mm"]
            if d["precip_mm"] >= 1.0:
                mo["rain_days"] += 1
        if d["sunshine_s"]:
            mo["sun_h"] += d["sunshine_s"] / 3600
    monthly_rows = []
    for mo in monthly.values():
        monthly_rows.append({
            "month": mo["month"], "days": mo["days"],
            "tmax_avg": round(mo["tmax_sum"] / mo["t_days"], 1) if mo["t_days"] else None,
            "tmin_avg": round(mo["tmin_sum"] / mo["t_days"], 1) if mo["t_days"] else None,
            "precip_mm": round(mo["precip_mm"], 1), "rain_days": mo["rain_days"],
            "gdd": round(mo["gdd"]), "sun_h": round(mo["sun_h"]),
        })

    hottest = max(with_t, key=lambda d: d["tmax_c"], default=None)
    coldest = min(with_t, key=lambda d: d["tmin_c"], default=None)
    wettest = max(precip, key=lambda d: d["precip_mm"], default=None)
    return {
        "days": len(days),
        "first_date": days[0]["date"] if days else None,
        "last_date": days[-1]["date"] if days else None,
        "tmax_avg": round(sum(d["tmax_c"] for d in with_t) / len(with_t), 1) if with_t else None,
        "tmin_avg": round(sum(d["tmin_c"] for d in with_t) / len(with_t), 1) if with_t else None,
        "precip_mm": round(sum(d["precip_mm"] for d in precip), 1),
        "rain_days": sum(1 for d in precip if d["precip_mm"] >= 1.0),
        "gdd": round(gdd_total),
        "frost_days": len(frost),
        "last_spring_frost": last_spring,
        "first_fall_frost": first_fall,
        "hottest": {"date": hottest["date"], "tmax_c": hottest["tmax_c"]} if hottest else None,
        "coldest": {"date": coldest["date"], "tmin_c": coldest["tmin_c"]} if coldest else None,
        "wettest": {"date": wettest["date"], "precip_mm": wettest["precip_mm"]} if wettest else None,
        "monthly": monthly_rows,
    }


def pulse(today: date) -> Dict[str, Any]:
    """Season-so-far snapshot for the Log page: totals vs last year to the same
    date, plus per-crop recency so you know what's due for a look."""
    year, prev = today.year, today.year - 1
    cutoff_prev = _same_day(today, prev).isoformat()
    t = today.isoformat()
    week_start = (today - timedelta(days=6)).isoformat()
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT h.crop_id, h.date, h.weight_g, c.name, c.color, c.archived FROM harvests h "
            "JOIN crops c ON c.id = h.crop_id WHERE substr(h.date,1,4) IN (?, ?) ORDER BY h.date",
            (str(year), str(prev)),
        ).fetchall()
        recent = conn.execute(
            "SELECT crop_id, weight_g FROM ("
            "  SELECT crop_id, weight_g, ROW_NUMBER() OVER (PARTITION BY crop_id ORDER BY date DESC, id DESC) AS rn"
            "  FROM harvests) WHERE rn <= 12"
        ).fetchall()

    typical: Dict[int, List[float]] = defaultdict(list)
    for r in recent:
        typical[r["crop_id"]].append(r["weight_g"])

    crops: Dict[int, Dict[str, Any]] = {}
    tot = {"season_g": 0.0, "prev_to_date_g": 0.0, "prev_total_g": 0.0, "week_g": 0.0, "today_g": 0.0, "today_picks": 0}
    dates_by_crop: Dict[int, List[str]] = defaultdict(list)
    for r in rows:
        c = crops.setdefault(r["crop_id"], {
            "crop_id": r["crop_id"], "name": r["name"], "color": r["color"], "archived": bool(r["archived"]),
            "season_g": 0.0, "picks": 0, "prev_to_date_g": 0.0, "prev_total_g": 0.0, "last_date": None,
        })
        g = r["weight_g"]
        if r["date"][:4] == str(year):
            c["season_g"] += g; c["picks"] += 1; c["last_date"] = r["date"]
            tot["season_g"] += g
            if r["date"] >= week_start:
                tot["week_g"] += g
            if r["date"] == t:
                tot["today_g"] += g; tot["today_picks"] += 1
            if not dates_by_crop[r["crop_id"]] or dates_by_crop[r["crop_id"]][-1] != r["date"]:
                dates_by_crop[r["crop_id"]].append(r["date"])
        else:
            c["prev_total_g"] += g; tot["prev_total_g"] += g
            if r["date"] <= cutoff_prev:
                c["prev_to_date_g"] += g; tot["prev_to_date_g"] += g

    out = []
    for cid, c in crops.items():
        ds = dates_by_crop.get(cid, [])
        gaps = [(date.fromisoformat(b) - date.fromisoformat(a)).days for a, b in zip(ds, ds[1:])]
        c["pick_gap_days"] = median(gaps) if len(gaps) >= 2 else None
        c["days_since"] = (today - date.fromisoformat(c["last_date"])).days if c["last_date"] else None
        # "Due" = picked in the last fortnight (so probably still producing), and it's been
        # noticeably longer than this crop's usual interval between picks.
        c["due"] = bool(
            c["pick_gap_days"] and c["days_since"] is not None
            and c["days_since"] <= 14 and c["days_since"] >= max(2, 1.5 * c["pick_gap_days"])
        )
        w = typical.get(cid)
        c["typical_g"] = round(median(w), 1) if w else None
        for k in ("season_g", "prev_to_date_g", "prev_total_g"):
            c[k] = round(c[k], 1)
        out.append(c)
    out.sort(key=lambda c: (-c["season_g"], -c["prev_to_date_g"]))
    typical_all = {str(cid): round(median(w), 1) for cid, w in typical.items()}
    return {
        "season": year, "prev_season": prev, "today": t,
        **{k: round(v, 1) if isinstance(v, float) else v for k, v in tot.items()},
        "crops": out, "typical_g": typical_all,
    }
