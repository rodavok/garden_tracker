"""Pydantic models for the Garden Tracker API."""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


# ---------- crops & varieties ----------

class Crop(BaseModel):
    id: int
    name: str
    color: int                  # categorical palette slot, 1-8 (0 = "other")
    archived: bool = False
    harvests: int = 0           # count, for sorting the quick-pick
    last_harvest: Optional[str] = None


class CropCreate(BaseModel):
    name: str


class CropUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[int] = None
    archived: Optional[bool] = None


class Variety(BaseModel):
    id: int
    crop_id: int
    name: str


class VarietyCreate(BaseModel):
    crop_id: int
    name: str


class VarietyUpdate(BaseModel):
    name: Optional[str] = None


# ---------- plantings ----------

class Planting(BaseModel):
    id: int
    crop_id: int
    crop_name: str = ""
    variety_id: Optional[int] = None
    variety_name: Optional[str] = None
    season: int
    sow_date: Optional[str] = None
    transplant_date: Optional[str] = None
    plant_count: Optional[int] = None
    location: str = ""
    notes: str = ""
    # computed
    total_g: float = 0
    harvests: int = 0
    first_harvest: Optional[str] = None
    last_harvest: Optional[str] = None
    days_to_first: Optional[int] = None   # from transplant (or sow) to first harvest
    g_per_plant: Optional[float] = None


class PlantingCreate(BaseModel):
    crop_id: Optional[int] = None
    crop_name: Optional[str] = None
    variety_id: Optional[int] = None
    variety_name: Optional[str] = None
    season: Optional[int] = None          # defaults to the year of sow/transplant date
    sow_date: Optional[str] = None
    transplant_date: Optional[str] = None
    plant_count: Optional[int] = None
    location: str = ""
    notes: str = ""


class PlantingUpdate(BaseModel):
    crop_id: Optional[int] = None
    variety_id: Optional[int] = None
    variety_name: Optional[str] = None
    season: Optional[int] = None
    sow_date: Optional[str] = None
    transplant_date: Optional[str] = None
    plant_count: Optional[int] = None
    location: Optional[str] = None
    notes: Optional[str] = None


# ---------- harvests ----------

class Harvest(BaseModel):
    id: int
    date: str
    crop_id: int
    crop_name: str = ""
    variety_id: Optional[int] = None
    variety_name: Optional[str] = None
    planting_id: Optional[int] = None
    weight_g: float
    notes: str = ""
    created_at: Optional[str] = None


class HarvestCreate(BaseModel):
    date: str
    crop_id: Optional[int] = None
    crop_name: Optional[str] = None       # creates the crop if it doesn't exist
    variety_id: Optional[int] = None
    variety_name: Optional[str] = None    # creates the variety if it doesn't exist
    planting_id: Optional[int] = None
    weight_g: float = Field(ge=0)
    notes: str = ""


class HarvestUpdate(BaseModel):
    date: Optional[str] = None
    crop_id: Optional[int] = None
    variety_id: Optional[int] = None
    variety_name: Optional[str] = None
    planting_id: Optional[int] = None
    weight_g: Optional[float] = Field(default=None, ge=0)
    notes: Optional[str] = None


# ---------- weather ----------

class WeatherDay(BaseModel):
    date: str
    tmax_c: Optional[float] = None
    tmin_c: Optional[float] = None
    precip_mm: Optional[float] = None
    sunshine_s: Optional[float] = None
    source: str = "auto"                  # "auto" | "manual"
    notes: str = ""
    fetched_at: Optional[str] = None


class WeatherManual(BaseModel):
    """Manual entry / override for one day. Omitted fields keep the auto value."""
    tmax_c: Optional[float] = None
    tmin_c: Optional[float] = None
    precip_mm: Optional[float] = None
    notes: Optional[str] = None


class WeatherRange(BaseModel):
    start: Optional[str] = None
    end: Optional[str] = None
    days: Optional[int] = None


# ---------- settings ----------

class Settings(BaseModel):
    lat: Optional[float] = None
    lon: Optional[float] = None
    location_name: str = ""
    timezone: str = "America/New_York"
    backfill_start: str = "2025-08-01"
    backfill_done: bool = False
    weather_enabled: bool = True
    weather_last_fetch: Optional[str] = None
    weather_last_error: str = ""


class SettingsUpdate(BaseModel):
    lat: Optional[float] = None
    lon: Optional[float] = None
    location_name: Optional[str] = None
    backfill_start: Optional[str] = None
