import os
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from datetime import datetime, timedelta
from bson import ObjectId

from database import db, create_document, get_documents
from schemas import User, Vehicle, ChargingStation, Booking, Session, Plan, RoutePlan, RoutePlanStop

app = FastAPI(title="Ampora API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    return {"name": "Ampora", "message": "EV Trip Planner & Intelligent Charging API"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:20]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:80]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"

    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"
    return response


# Utility: convert ObjectId to str for responses

def serialize(doc):
    if not doc:
        return doc
    d = dict(doc)
    if "_id" in d:
        d["id"] = str(d.pop("_id"))
    return d


# Seed some pricing plans and demo stations if empty
@app.on_event("startup")
async def seed_data():
    if db is None:
        return
    if db["plan"].count_documents({}) == 0:
        plans = [
            {"name": "Basic", "monthly_fee_usd": 0, "kwh_included": 0, "overage_price_per_kwh": 0.39},
            {"name": "Plus", "monthly_fee_usd": 9.99, "kwh_included": 50, "overage_price_per_kwh": 0.33},
            {"name": "Pro", "monthly_fee_usd": 19.99, "kwh_included": 120, "overage_price_per_kwh": 0.29},
        ]
        for p in plans:
            create_document("plan", p)
    if db["chargingstation"].count_documents({}) == 0:
        stations = [
            {"name": "Ampora Supercharge - Downtown", "operator": "Ampora", "latitude": 37.7749, "longitude": -122.4194, "power_kw": 150, "price_per_kwh": 0.35, "available_ports": 6, "city": "San Francisco"},
            {"name": "GreenVolt Hub - Silicon Valley", "operator": "GreenVolt", "latitude": 37.3875, "longitude": -122.0575, "power_kw": 100, "price_per_kwh": 0.32, "available_ports": 4, "city": "Mountain View"},
            {"name": "ChargeX Express - Bay Bridge", "operator": "ChargeX", "latitude": 37.798, "longitude": -122.377, "power_kw": 250, "price_per_kwh": 0.41, "available_ports": 8, "city": "San Francisco"},
        ]
        for s in stations:
            create_document("chargingstation", s)


# Users
@app.post("/api/users")
def create_user(user: User):
    user_id = create_document("user", user)
    return {"id": user_id}


# Vehicles
@app.post("/api/vehicles")
def create_vehicle(vehicle: Vehicle):
    vid = create_document("vehicle", vehicle)
    return {"id": vid}

@app.get("/api/vehicles")
def list_vehicles(user_email: Optional[str] = None):
    q = {"user_email": user_email} if user_email else {}
    return [serialize(v) for v in get_documents("vehicle", q, None)]


# Stations
@app.get("/api/stations")
def list_stations(city: Optional[str] = None, limit: int = Query(50, ge=1, le=200)):
    q = {"city": city} if city else {}
    return [serialize(s) for s in get_documents("chargingstation", q, limit)]


# Plans
@app.get("/api/plans")
def list_plans():
    return [serialize(p) for p in get_documents("plan", {}, None)]


# Bookings
class BookingRequest(BaseModel):
    user_email: str
    station_id: str
    vehicle_make: Optional[str] = None
    vehicle_model: Optional[str] = None
    start_time: datetime
    duration_minutes: int = Field(..., gt=0)

@app.post("/api/bookings")
def create_booking(b: BookingRequest):
    # naive spot availability check by available_ports
    station = db["chargingstation"].find_one({"_id": ObjectId(b.station_id)})
    if not station:
        raise HTTPException(status_code=404, detail="Station not found")

    # create booking document
    data = {
        **b.model_dump(),
        "status": "reserved",
    }
    booking_id = create_document("booking", data)

    # reduce available ports optimistically (not production safe)
    db["chargingstation"].update_one({"_id": station["_id"]}, {"$inc": {"available_ports": -1}})

    return {"id": booking_id}

@app.get("/api/bookings")
def list_bookings(user_email: Optional[str] = None):
    q = {"user_email": user_email} if user_email else {}
    return [serialize(b) for b in get_documents("booking", q, None)]


# Simple route planning (heuristic)
class TripRequest(BaseModel):
    origin_lat: float
    origin_lng: float
    dest_lat: float
    dest_lng: float
    vehicle_battery_kwh: float
    vehicle_efficiency_kwh_per_100km: float
    current_soc_percent: float = Field(..., ge=0, le=100)
    target_arrival_soc_percent: float = Field(10, ge=0, le=100)

@app.post("/api/plan-trip")
def plan_trip(req: TripRequest):
    import math

    # estimate straight-line distance as fallback
    R = 6371
    dlat = math.radians(req.dest_lat - req.origin_lat)
    dlon = math.radians(req.dest_lng - req.origin_lng)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(req.origin_lat)) * math.cos(math.radians(req.dest_lat)) * math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    distance_km = R * c

    usable_kwh = req.vehicle_battery_kwh * (req.current_soc_percent / 100)
    kwh_per_km = req.vehicle_efficiency_kwh_per_100km / 100
    max_km_now = usable_kwh / kwh_per_km if kwh_per_km else distance_km

    stops: List[RoutePlanStop] = []

    # If can make it without charging
    if max_km_now >= distance_km * 1.05:  # buffer
        duration_minutes = int(distance_km / 90 * 60)  # assume avg 90km/h
        plan = RoutePlan(
            origin_lat=req.origin_lat,
            origin_lng=req.origin_lng,
            dest_lat=req.dest_lat,
            dest_lng=req.dest_lng,
            vehicle_battery_kwh=req.vehicle_battery_kwh,
            vehicle_efficiency_kwh_per_100km=req.vehicle_efficiency_kwh_per_100km,
            current_soc_percent=req.current_soc_percent,
            target_arrival_soc_percent=req.target_arrival_soc_percent,
            total_distance_km=round(distance_km, 1),
            estimated_duration_minutes=duration_minutes,
            stops=stops
        )
        return plan

    # Need charging: choose nearest high-power station half-way heuristic
    stations = list(db["chargingstation"].find({}).limit(50)) if db else []
    if not stations:
        raise HTTPException(status_code=400, detail="No stations available to plan route")

    # pick the strongest power station as a simple heuristic
    station = sorted(stations, key=lambda s: s.get("power_kw", 0), reverse=True)[0]

    # assume 20min charge at high power per stop
    charge_minutes = 25 if station.get("power_kw", 50) >= 150 else 35

    # naive ETA: drive to half distance, charge, then rest
    base_time = distance_km / 90 * 60
    duration_minutes = int(base_time + charge_minutes)

    stop = RoutePlanStop(
        station_id=str(station.get("_id")),
        station_name=station.get("name", "Station"),
        latitude=station.get("latitude", req.origin_lat),
        longitude=station.get("longitude", req.origin_lng),
        charge_minutes=charge_minutes,
        notes="Heuristic stop based on fastest available charger"
    )
    stops.append(stop)

    plan = RoutePlan(
        origin_lat=req.origin_lat,
        origin_lng=req.origin_lng,
        dest_lat=req.dest_lat,
        dest_lng=req.dest_lng,
        vehicle_battery_kwh=req.vehicle_battery_kwh,
        vehicle_efficiency_kwh_per_100km=req.vehicle_efficiency_kwh_per_100km,
        current_soc_percent=req.current_soc_percent,
        target_arrival_soc_percent=req.target_arrival_soc_percent,
        total_distance_km=round(distance_km, 1),
        estimated_duration_minutes=duration_minutes,
        stops=stops
    )
    return plan


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
