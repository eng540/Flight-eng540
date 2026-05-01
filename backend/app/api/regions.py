"""Geographic regions API."""
from fastapi import APIRouter, HTTPException
from typing import List
from app.config import settings
from app.schemas import RegionResponse

router = APIRouter(prefix="/regions", tags=["regions"])


@router.get("", response_model=List[RegionResponse])
def list_regions():
    """List all available geographic regions."""
    return [r.to_dict() for r in settings.get_regions().values()]


@router.get("/{key}", response_model=RegionResponse)
def get_region(key: str):
    """Get a specific region by key."""
    r = settings.get_region(key)
    if not r:
        raise HTTPException(status_code=404, detail=f"Region '{key}' not found")
    return r.to_dict()
