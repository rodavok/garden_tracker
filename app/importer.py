"""CSV import/export. The import accepts the Notion export format
(Date, Crop, Weight (g)) plus optional Variety and Notes columns, and skips
rows that already exist (same date, crop, and weight) so re-importing is safe.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any, Dict, Iterable, List, Tuple

from . import db

_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%B %d, %Y", "%b %d, %Y", "%d %B %Y")


def _norm_date(raw: str) -> str:
    raw = (raw or "").strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"Unrecognised date: {raw!r}")


def _find(headers: Iterable[str], *needles: str) -> str | None:
    for h in headers:
        hl = h.strip().lower()
        if any(hl == n or hl.startswith(n) for n in needles):
            return h
    return None


def import_csv(text: str) -> Dict[str, Any]:
    reader = csv.DictReader(io.StringIO(text))
    headers = reader.fieldnames or []
    col_date = _find(headers, "date")
    col_crop = _find(headers, "crop", "plant", "produce")
    col_weight = _find(headers, "weight", "grams", "mass")
    col_variety = _find(headers, "variety", "cultivar")
    col_notes = _find(headers, "notes", "note", "comment")
    if not (col_date and col_crop and col_weight):
        raise ValueError(f"CSV needs Date, Crop and Weight columns; got {headers}")

    added, skipped, errors = 0, 0, []
    for i, row in enumerate(reader, start=2):
        try:
            d = _norm_date(row[col_date])
            crop_name = (row[col_crop] or "").strip()
            weight = float(str(row[col_weight]).replace(",", "").strip() or 0)
            if not crop_name:
                raise ValueError("empty crop")
            crop = db.get_or_create_crop(crop_name)
            if db.harvest_exists(d, crop["id"], weight):
                skipped += 1
                continue
            variety_id = None
            if col_variety and (row.get(col_variety) or "").strip():
                variety_id = db.get_or_create_variety(crop["id"], row[col_variety])["id"]
            db.insert_harvest({
                "date": d, "crop_id": crop["id"], "variety_id": variety_id,
                "weight_g": weight, "notes": (row.get(col_notes) or "").strip() if col_notes else "",
            })
            added += 1
        except Exception as exc:  # keep going; report the bad lines
            errors.append(f"line {i}: {exc}")
    return {"added": added, "skipped": skipped, "errors": errors}


def export_csv() -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Date", "Crop", "Variety", "Weight (g)", "Notes", "Planting"])
    for h in reversed(db.list_harvests()):
        w.writerow([h["date"], h["crop_name"], h.get("variety_name") or "",
                    f"{h['weight_g']:g}", h.get("notes") or "", h.get("planting_id") or ""])
    return buf.getvalue()
