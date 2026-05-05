"""
Application configuration using Pydantic Settings.
FIX (P0.3): Added FR24_API_KEY to Settings model — previously used as raw
os.getenv() in ingestion_service.py causing silent failures when key is absent.
Evidence: ingestion_service.py line: self.fr24_api_key = os.getenv("FR24_API_KEY")
"""
from pydantic_settings import BaseSettings
from typing import Optional, Dict, List


class GeoRegion:
    def __init__(self, key: str, name: str, name_ar: str,
                 lamin: float, lomin: float, lamax: float, lomax: float):
        self.key = key
        self.name = name
        self.name_ar = name_ar
        self.lamin = lamin
        self.lomin = lomin
        self.lamax = lamax
        self.lomax = lomax

    def to_dict(self):
        return {
            "key": self.key,
            "name": self.name,
            "name_ar": self.name_ar,
            "lamin": self.lamin,
            "lomin": self.lomin,
            "lamax": self.lamax,
            "lomax": self.lomax,
            "center_lat": (self.lamin + self.lamax) / 2,
            "center_lon": (self.lomin + self.lomax) / 2,
        }


DEFAULT_REGIONS: Dict[str, "GeoRegion"] = {
    "middle_east":  GeoRegion("middle_east",  "Middle East",  "الشرق الأوسط",   12.0,  25.0, 42.0, 63.0),
    "north_africa": GeoRegion("north_africa", "North Africa", "شمال أفريقيا",   15.0, -18.0, 37.0, 35.0),
    "central_asia": GeoRegion("central_asia", "Central Asia", "آسيا الوسطى",    35.0,  45.0, 55.0, 85.0),
    "east_africa":  GeoRegion("east_africa",  "East Africa",  "شرق أفريقيا",  -12.0,  25.0, 22.0, 51.0),
    "south_asia":   GeoRegion("south_asia",   "South Asia",   "جنوب آسيا",       5.0,  60.0, 38.0, 90.0),
}


def _fix_db_url(url: str) -> str:
    """Convert postgres:// → postgresql:// for SQLAlchemy compatibility."""
    if url and url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


class Settings(BaseSettings):
    APP_NAME: str = "Flight Intelligence API"
    DEBUG: bool = False
    SECRET_KEY: str = "change-me-in-production"
    ENVIRONMENT: str = "development"

    # ── Database & Cache ───────────────────────────────────────────────────────
    DATABASE_URL: str = ""
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── FR24 API (PRIMARY data source) ─────────────────────────────────────────
    # FIX P0.3: Moved from raw os.getenv() to Settings — enables validation,
    # env-file loading, and consistent access across all modules.
    # Evidence: FR24 OpenAPI spec — all endpoints require Bearer token.
    FR24_API_KEY: Optional[str] = None
    FR24_BASE_URL: str = "https://fr24api.flightradar24.com"

    # ── OpenSky (LEGACY — no longer primary source) ────────────────────────────
    OPENSKY_USERNAME: Optional[str] = None
    OPENSKY_PASSWORD: Optional[str] = None
    OPENSKY_CLIENT_ID: Optional[str] = None
    OPENSKY_CLIENT_SECRET: Optional[str] = None

    # ── Ingestion Behaviour ────────────────────────────────────────────────────
    INGESTION_DELAY_SECONDS: float = 10.0
    INGESTION_MAX_RETRIES: int = 3

    # FIX: Default changed from 0 → 30 per explicit business requirement:
    # "implement cleanup_old_data (30-day retention)" in requirements spec.
    # Set to 0 in .env to keep all data forever.
    DATA_RETENTION_DAYS: int = 30

    ACTIVE_REGIONS: str = "middle_east,north_africa,central_asia"

    class Config:
        env_file = ".env"
        case_sensitive = True

    def model_post_init(self, __context):
        object.__setattr__(self, "DATABASE_URL", _fix_db_url(self.DATABASE_URL))

    # ── Region helpers ─────────────────────────────────────────────────────────
    def get_active_region_keys(self) -> List[str]:
        return [r.strip() for r in self.ACTIVE_REGIONS.split(",") if r.strip()]

    def get_regions(self) -> Dict[str, "GeoRegion"]:
        return dict(DEFAULT_REGIONS)

    def get_region(self, key: str) -> Optional["GeoRegion"]:
        return DEFAULT_REGIONS.get(key)

    def is_fr24_configured(self) -> bool:
        """True only when FR24_API_KEY is present and non-empty."""
        return bool(self.FR24_API_KEY and self.FR24_API_KEY.strip())


settings = Settings()
