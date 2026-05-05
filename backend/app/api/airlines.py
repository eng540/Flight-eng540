"""
Enterprise Airlines API Endpoints (v3.0 - Graceful Degradation)
"""
from fastapi import APIRouter

router = APIRouter(prefix="/airlines", tags=["airlines"])

@router.get("")
async def get_airlines():
    """SRE Fallback: Return empty list during Enterprise Migration."""
    return []

@router.get("/{airline_id}")
async def get_airline(airline_id: int):
    return None

@router.get("/icao/{icao24}")
async def get_airline_by_icao(icao24: str):
    return None