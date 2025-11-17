"""
Ampora Database Schemas

Define MongoDB collection schemas for the Ampora EV trip planner and intelligent charging system.
Each Pydantic model corresponds to a collection. Collection name is the lowercase class name.
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class User(BaseModel):
    name: str = Field(..., description="Full name")
    email: str = Field(..., description="Email address")
    role: str = Field("user", description="Role: user | operator | admin")

class Vehicle(BaseModel):
    user_email: str = Field(..., description="Owner email")
    make: str
    model: str
    battery_kwh: float = Field(..., gt=0)
    efficiency_kwh_per_100km: float = Field(..., gt=0)
    max_range_km: float = Field(..., gt=0)

class ChargingStation(BaseModel):
    name: str
    operator: str
    latitude: float
    longitude: float
    power_kw: float = Field(..., gt=0)
    price_per_kwh: float = Field(..., gt=0)
    available_ports: int = Field(..., ge=0)
    address: Optional[str] = None
    city: Optional[str] = None

class Booking(BaseModel):
    user_email: str
    station_id: str
    vehicle_make: Optional[str] = None
    vehicle_model: Optional[str] = None
    start_time: datetime
    duration_minutes: int = Field(..., gt=0)
    status: str = Field("reserved", description="reserved | completed | cancelled")

class Session(BaseModel):
    user_email: str
    station_id: str
    energy_kwh: float = Field(..., gt=0)
    cost_usd: float = Field(..., ge=0)
    started_at: datetime
    ended_at: Optional[datetime] = None

class Plan(BaseModel):
    name: str
    monthly_fee_usd: float = Field(..., ge=0)
    kwh_included: float = Field(..., ge=0)
    overage_price_per_kwh: float = Field(..., ge=0)

class RoutePlanStop(BaseModel):
    station_id: str
    station_name: str
    latitude: float
    longitude: float
    charge_minutes: int
    notes: Optional[str] = None

class RoutePlan(BaseModel):
    origin_lat: float
    origin_lng: float
    dest_lat: float
    dest_lng: float
    vehicle_battery_kwh: float
    vehicle_efficiency_kwh_per_100km: float
    current_soc_percent: float
    target_arrival_soc_percent: float = 10
    total_distance_km: float
    estimated_duration_minutes: int
    stops: List[RoutePlanStop] = []
