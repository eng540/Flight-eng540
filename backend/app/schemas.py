"""
Enterprise Pydantic Schemas (v3.1 — TIER 0 Fixed)
Strict validation and typing for the Snowflake Architecture.

CHANGES FROM v3.0:
  RawIngestionPayload     → +fr24_id, +flight_number, +vspeed_fpm, +aircraft_type
                            Evidence: FR24 OpenAPI FlightPositionsFull fields
  IngestionJobResponse    → Fixed to match actual IngestionJob model columns.
                            Evidence: ValidationError crash — 9 fields in schema
                            had no matching DB columns.
  LivePositionResponse    → NEW: response schema for /api/v1/live/positions
  FlightDetailResponse    → NEW: response schema for /api/v1/flights/{session_id}
  TrajectoryResponse      → NEW: response schema for trajectory endpoint
  HistoryQueryRequest     → NEW: request body for /api/v1/history/query
  HistoryQueryResponse    → NEW: paginated history response
  DailySummaryResponse    → NEW: for /api/v1/analytics/daily-summary
  AirlinePerformanceItem  → NEW: for /api/v1/analytics/airline-performance
  CreditsUsageItem        → NEW: for /api/v1/system/credits-usage
                            Evidence: FR24 OpenAPI UsageLogSummary schema
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Any, Dict
from datetime import datetime


# ═════════════════════════════════════════════════════════════════════════════
# 1. DIMENSION SCHEMAS (Reference Data)
# ═════════════════════════════════════════════════════════════════════════════

class DimGeographyBase(BaseModel):
    icao_code:   Optional[str]   = Field(None, max_length=4)
    iata_code:   Optional[str]   = Field(None, max_length=3)
    name:        str             = Field(..., max_length=255)
    city:        Optional[str]   = Field(None, max_length=100)
    country_code: Optional[str]  = Field(None, max_length=2)
    latitude:    Optional[float] = None
    longitude:   Optional[float] = None
    elevation_m: Optional[float] = None

class DimGeographyResponse(DimGeographyBase):
    model_config = ConfigDict(from_attributes=True)
    # Optional: nested responses from _session_to_dict dicts may omit id
    id: Optional[int] = None


class DimOperatorBase(BaseModel):
    icao_code:     Optional[str] = Field(None, max_length=3)
    iata_code:     Optional[str] = Field(None, max_length=2)
    name:          str           = Field(..., max_length=255)
    country_code:  Optional[str] = Field(None, max_length=2)
    operator_type: Optional[str] = Field(None, max_length=50)

class DimOperatorResponse(DimOperatorBase):
    model_config = ConfigDict(from_attributes=True)
    # Optional: nested responses from _session_to_dict dicts may omit id
    id: Optional[int] = None


class DimAircraftBase(BaseModel):
    icao24:       str            = Field(..., min_length=4, max_length=6)
    registration: Optional[str]  = Field(None, max_length=20)
    manufacturer: Optional[str]  = Field(None, max_length=100)
    model:        Optional[str]  = Field(None, max_length=100)
    type_code:    Optional[str]  = Field(None, max_length=10)

class DimAircraftResponse(DimAircraftBase):
    model_config = ConfigDict(from_attributes=True)
    # Optional: nested in flight responses built by _session_to_dict
    id:       Optional[int] = None
    operator: Optional[DimOperatorResponse] = None


# ═════════════════════════════════════════════════════════════════════════════
# 2. TELEMETRY & SESSIONS
# ═════════════════════════════════════════════════════════════════════════════

class TrackTelemetryBase(BaseModel):
    timestamp:    datetime
    latitude:     float
    longitude:    float
    altitude_m:   Optional[float] = None
    velocity_kmh: Optional[float] = None
    heading_deg:  Optional[float] = None
    # FIX: Added vspeed_fpm — FR24 OpenAPI FlightPositionsFull.vspeed (ft/min)
    vspeed_fpm:   Optional[float] = None
    is_on_ground: Optional[bool]  = False
    squawk:       Optional[str]   = None

class TrackTelemetryResponse(TrackTelemetryBase):
    model_config = ConfigDict(from_attributes=True)


class FlightSessionBase(BaseModel):
    callsign:       Optional[str] = Field(None, max_length=20)
    fr24_id:        Optional[str] = None
    flight_number:  Optional[str] = None
    # FIX: Made Optional — _session_to_dict returns None for incomplete sessions
    # Root cause of POST /api/v1/history/query → 500:
    # Required datetime field fails when session has no timestamp yet
    first_seen_ts:  Optional[datetime] = None
    last_seen_ts:   Optional[datetime] = None
    flight_status:  Optional[str] = "active"

class FlightSessionResponse(FlightSessionBase):
    model_config = ConfigDict(from_attributes=True)
    session_id:   int
    aircraft:     Optional[DimAircraftResponse]  = None
    operator:     Optional[DimOperatorResponse]  = None
    dep_airport:  Optional[DimGeographyResponse] = None
    arr_airport:  Optional[DimGeographyResponse] = None
    tracks:       Optional[List[TrackTelemetryBase]] = []
    max_altitude_m:    Optional[float] = None
    total_distance_km: Optional[float] = None

class FlightListResponse(BaseModel):
    total:     int
    page:      int
    page_size: int
    pages:     int
    # FIX: List[Any] — data comes from _session_to_dict dicts, not ORM objects
    data:      List[Any]


# ═════════════════════════════════════════════════════════════════════════════
# 3. LIVE MAP (Denormalized Fast Response)
# ═════════════════════════════════════════════════════════════════════════════

class LivePositionResponse(BaseModel):
    """
    Fast response from current_aircraft_state table.
    Maps exactly to CurrentAircraftState model columns.
    Used by: GET /api/v1/live/positions
    """
    model_config = ConfigDict(from_attributes=True)

    icao24:        str
    fr24_id:       Optional[str]   = None
    callsign:      Optional[str]   = None
    flight_number: Optional[str]   = None
    operator_name: Optional[str]   = None
    aircraft_model: Optional[str]  = None
    aircraft_type: Optional[str]   = None
    dep_airport_iata: Optional[str] = None
    arr_airport_iata: Optional[str] = None
    latitude:      Optional[float] = None
    longitude:     Optional[float] = None
    altitude_m:    Optional[float] = None
    velocity_kmh:  Optional[float] = None
    heading_deg:   Optional[float] = None
    vspeed_fpm:    Optional[float] = None
    on_ground:     Optional[bool]  = None
    squawk:        Optional[str]   = None
    region_key:    Optional[str]   = None
    last_updated:  Optional[datetime] = None
    session_id:    Optional[int]   = None

class LivePositionsResponse(BaseModel):
    total:  int
    active: int  # on_ground=False count
    data:   List[LivePositionResponse]


# ═════════════════════════════════════════════════════════════════════════════
# 4. FLIGHT DETAIL (Full session + trajectory)
# ═════════════════════════════════════════════════════════════════════════════

class TrajectoryPoint(BaseModel):
    """Single point in a flight trajectory. Used by frontend map."""
    ts:  int    # Unix epoch
    lat: float
    lon: float
    alt: Optional[float] = None   # metres
    vel: Optional[float] = None   # km/h
    hdg: Optional[float] = None
    vspd: Optional[float] = None  # ft/min

class TrajectoryResponse(BaseModel):
    session_id: int
    fr24_id:    Optional[str] = None
    callsign:   Optional[str] = None
    points:     List[TrajectoryPoint]

class FlightDetailResponse(BaseModel):
    """Full flight detail for /api/v1/flights/{session_id}"""
    model_config = ConfigDict(from_attributes=True)

    session_id:    int
    fr24_id:       Optional[str]  = None
    flight_number: Optional[str]  = None
    callsign:      Optional[str]  = None
    flight_status: Optional[str]  = None
    first_seen_ts: Optional[datetime] = None
    last_seen_ts:  Optional[datetime] = None
    actual_takeoff_ts:  Optional[datetime] = None
    actual_landing_ts:  Optional[datetime] = None
    duration_seconds:   Optional[int]    = None
    max_altitude_m:     Optional[float]  = None
    total_distance_km:  Optional[float]  = None

    aircraft:    Optional[DimAircraftResponse]  = None
    operator:    Optional[DimOperatorResponse]  = None
    dep_airport: Optional[DimGeographyResponse] = None
    arr_airport: Optional[DimGeographyResponse] = None

    trajectory:  Optional[TrajectoryResponse]   = None


# ═════════════════════════════════════════════════════════════════════════════
# 5. INGESTION (Internal Use + API)
# ═════════════════════════════════════════════════════════════════════════════

class RawIngestionPayload(BaseModel):
    """
    Internal payload passed from ingestion_service to crud.
    FIX: Added fr24_id, flight_number, vspeed_fpm, aircraft_type.
    Evidence: FR24 OpenAPI FlightPositionsFull — all are valid fields
    returned by /api/live/flight-positions/full.
    """
    icao24:        str
    # FR24 primary identifier — MUST be stored for API enrichment calls
    fr24_id:       Optional[str]   = None
    callsign:      Optional[str]   = None
    # FR24 commercial flight number (distinct from ATC callsign)
    flight_number: Optional[str]   = None
    registration:  Optional[str]   = None
    # Aircraft ICAO type code e.g. "B77W", "A320"
    aircraft_type: Optional[str]   = None
    operator_iata: Optional[str]   = None
    operator_icao: Optional[str]   = None
    origin_country: Optional[str]  = None
    timestamp:     int
    longitude:     float
    latitude:      float
    altitude:      Optional[float] = 0.0   # metres (converted from ft)
    velocity:      Optional[float] = 0.0   # km/h (converted from knots)
    heading:       Optional[float] = None
    # FIX: Added vspeed_fpm — FR24 OpenAPI FlightPositionsFull.vspeed (ft/min)
    vspeed_fpm:    Optional[float] = None
    on_ground:     Optional[bool]  = False
    est_departure_airport: Optional[str] = None
    est_arrival_airport:   Optional[str] = None
    region_key:    Optional[str]   = "global"
    squawk:        Optional[str]   = None
    # Truth: FlightPositionsFull.source — ADSB | MLAT | ESTIMATED | FLARM | ADSB_ICAO | ADSB_ICAO_NT
    source:        Optional[str]   = None
    # Truth: FlightPositionsFull.eta — estimated time of arrival (ISO 8601)
    eta:           Optional[str]   = None


# ═════════════════════════════════════════════════════════════════════════════
# 6. ANALYTICS RESPONSES
# ═════════════════════════════════════════════════════════════════════════════

class CountryStats(BaseModel):
    country_name: str
    flight_count: int

class DailyFlightStats(BaseModel):
    date:         str
    flight_count: int

class HourlyStats(BaseModel):
    hour:         int
    flight_count: int

class AirportStats(BaseModel):
    airport_icao: str
    flight_count: int
    as_departure: int
    as_arrival:   int

class RouteStats(BaseModel):
    departure:    str
    arrival:      str
    flight_count: int

class AnalyticsSummary(BaseModel):
    total_flights:    int
    unique_countries: int
    unique_airports:  int
    top_countries:    List[CountryStats]

class AirlineActivityStats(BaseModel):
    airline_icao24: str
    airline_name:   Optional[str]
    flight_count:   int

class DailySummaryResponse(BaseModel):
    """Response for GET /api/v1/analytics/daily-summary"""
    date:              str
    total_flights:     int
    active_flights:    int
    landed_flights:    int
    emergency_events:  int
    unique_aircraft:   int
    unique_operators:  int
    top_routes:        List[RouteStats] = []

class AirlinePerformanceItem(BaseModel):
    """Single row in GET /api/v1/analytics/airline-performance"""
    operator_icao:           str
    operator_name:           Optional[str] = None
    total_flights:           int
    active_flights:          int = 0
    avg_flight_duration_min: Optional[float] = None
    total_distance_km:       Optional[float] = None

class AirlinePerformanceResponse(BaseModel):
    total: int
    data:  List[AirlinePerformanceItem]

# ── Credits Usage (FR24 API budget tracking) ──────────────────────────────
class CreditsUsageItem(BaseModel):
    """
    Mirrors FR24 OpenAPI UsageLogSummary schema exactly.
    Evidence: FR24 OpenAPI UsageLogSummary.{endpoint, request_count, credits}
    """
    endpoint:      str
    request_count: int
    credits:       int

class CreditsUsageResponse(BaseModel):
    data:         List[CreditsUsageItem]
    total_credits: int


# ═════════════════════════════════════════════════════════════════════════════
# 7. HISTORY ENGINE
# ═════════════════════════════════════════════════════════════════════════════

class HistoryQueryRequest(BaseModel):
    """
    Request body for POST /api/v1/history/query
    Supports multi-dimensional filtering per business requirements.
    """
    entity_type: str = Field(
        ...,
        description="One of: aircraft | airport | airline | country | region",
        pattern="^(aircraft|airport|airline|country|region)$",
    )
    entity_id:   str = Field(..., description="ICAO24, airport ICAO, operator ICAO, country code, or region key")
    date_from:   Optional[str] = Field(None, description="YYYY-MM-DD")
    date_to:     Optional[str] = Field(None, description="YYYY-MM-DD inclusive")
    page:        int = Field(1, ge=1)
    page_size:   int = Field(50, ge=1, le=500)

class HistoryAggregations(BaseModel):
    total_flights:      int
    unique_aircraft:    int
    unique_operators:   int
    total_distance_km:  Optional[float] = None
    avg_duration_min:   Optional[float] = None
    top_routes:         List[RouteStats] = []

class HistoryQueryResponse(BaseModel):
    entity_type:  str
    entity_id:    str
    total:        int
    page:         int
    page_size:    int
    pages:        int
    # FIX: List[Any] instead of List[FlightSessionResponse]
    # _session_to_dict() returns plain dicts — not ORM objects.
    # Pydantic strict-validates FlightSessionResponse including required fields
    # like first_seen_ts/last_seen_ts causing 500 when sessions are incomplete.
    # Root cause of POST /api/v1/history/query HTTP 500 at 19:14:40.
    data:         List[Any]
    aggregations: Optional[HistoryAggregations] = None


# ═════════════════════════════════════════════════════════════════════════════
# 8. STATISTICS (Kept for frontend compat)
# ═════════════════════════════════════════════════════════════════════════════

class FlightStatistics(BaseModel):
    total_flights:       int
    daily_stats:         List[DailyFlightStats]
    top_airlines:        List[AirlineActivityStats]
    top_countries:       List[CountryStats]
    flights_today:       int
    flights_this_week:   int
    flights_this_month:  int

class CountryActivityStats(BaseModel):
    country_name: str
    flight_count: int

class HealthCheck(BaseModel):
    status:    str
    timestamp: datetime
    database:  str
    version:   str = "3.1.0-Enterprise"


# ═════════════════════════════════════════════════════════════════════════════
# 9. REGIONS
# ═════════════════════════════════════════════════════════════════════════════

class RegionResponse(BaseModel):
    key:        str
    name:       str
    name_ar:    str
    lamin:      float
    lomin:      float
    lamax:      float
    lomax:      float
    center_lat: float
    center_lon: float


# ═════════════════════════════════════════════════════════════════════════════
# 10. INGESTION JOB (Fixed Schema ↔ Model alignment)
# ═════════════════════════════════════════════════════════════════════════════

class IngestionJobResponse(BaseModel):
    """
    FIX: Rebuilt to exactly match IngestionJob model columns.
    All new fields are Optional to safely handle rows created before migration 002.
    Evidence: original schema referenced date_str, lamin, lomin, lamax, lomax,
    begin_ts, end_ts, flights_ingested, chunks_total, chunks_done — none existed
    in the model → ValidationError on every GET /ingestion/jobs call.
    """
    model_config = ConfigDict(from_attributes=True)

    id:         int
    region_key: str
    status:     str
    job_type:   Optional[str] = None

    # New fields (added in migration 002 — Optional for backward compat)
    date_str:         Optional[str]   = None
    lamin:            Optional[float] = None
    lomin:            Optional[float] = None
    lamax:            Optional[float] = None
    lomax:            Optional[float] = None
    begin_ts:         Optional[int]   = None
    end_ts:           Optional[int]   = None
    flights_ingested: Optional[int]   = 0
    chunks_total:     Optional[int]   = 0
    chunks_done:      Optional[int]   = 0

    # Legacy fields (kept for backward compat)
    records_processed: Optional[int] = 0
    api_calls:         Optional[int] = 0
    credits_used:      Optional[int] = 0

    error_message: Optional[str]      = None
    created_at:    Optional[datetime] = None
    started_at:    Optional[datetime] = None
    completed_at:  Optional[datetime] = None

class IngestionJobListResponse(BaseModel):
    total: int
    data:  List[IngestionJobResponse]

class IngestionStartRequest(BaseModel):
    begin_date:    str  = Field(..., description="YYYY-MM-DD")
    end_date:      str  = Field(..., description="YYYY-MM-DD inclusive")
    region_keys:   List[str]
    force_reingest: bool = False


# ═════════════════════════════════════════════════════════════════════════════
# OPERATIONS BOARD SCHEMAS (System Design §1–§7)
# ═════════════════════════════════════════════════════════════════════════════

# ── Request Schemas ────────────────────────────────────────────────────────

class ScopeDefinition(BaseModel):
    """
    User-defined scope for the operation.
    Maps directly to Operation.scope_* columns.
    Evidence: system design §1 — scope fields.
    """
    region_key:   Optional[str]       = Field(None, description="مفتاح المنطقة الجغرافية")
    date_from:    Optional[str]       = Field(None, description="YYYY-MM-DD")
    date_to:      Optional[str]       = Field(None, description="YYYY-MM-DD inclusive")
    entity_id:    Optional[str]       = Field(None, description="ICAO24, flight_id, airport_code...")
    entity_type:  Optional[str]       = Field(None, description="aircraft|airport|airline|route")
    entity_ids:   Optional[List[str]] = Field(None, description="لطلبات متعددة الكيانات")
    filters:      Optional[Dict[str, Any]] = Field(None, description="فلاتر إضافية")
    bounds:       Optional[Dict[str, float]] = Field(
        None, description='{"lamin":..., "lomin":..., "lamax":..., "lomax":...}'
    )


class OperationCreateRequest(BaseModel):
    """
    POST /api/v1/operations — إنشاء عملية جديدة.
    المستخدم يحدد ماذا يريد وعلى ماذا.
    النظام يحسب التكلفة ويعرض Pre-flight Summary.
    Evidence: system design §5 Execution Flow step 1.
    """
    capability_type: str = Field(
        ...,
        description=(
            "live_positions | flight_summaries | flight_tracks | "
            "historic_positions | historic_events | static_airport | static_airline"
        ),
        pattern="^(live_positions|flight_summaries|flight_tracks|"
                "historic_positions|historic_events|static_airport|static_airline)$",
    )
    scope: ScopeDefinition = Field(..., description="نطاق الطلب")


class OperationApproveRequest(BaseModel):
    """
    POST /api/v1/operations/{id}/approve — موافقة المستخدم بعد Pre-flight.
    Evidence: system design §3 transitions: planned → running on approved_at IS NOT NULL.
    Evidence: system design §5 "user clicks إطلاق → approved_at set"
    """
    confirmed: bool = Field(
        ...,
        description="يجب أن تكون True — تأكيد قراءة Pre-flight Summary"
    )


class OperationCancelRequest(BaseModel):
    """
    POST /api/v1/operations/{id}/cancel
    Evidence: system design §7: "SET cancel_requested = TRUE, worker checks between chunks"
    """
    reason: Optional[str] = Field(None, max_length=255, description="سبب الإلغاء")


# ── Pre-flight Summary ─────────────────────────────────────────────────────

class PreflightWarning(BaseModel):
    """تحذير واحد يُعرض في Pre-flight Summary."""
    level:   str = Field(..., description="info | warning | critical")
    code:    str = Field(..., description="INSUFFICIENT_CREDITS | LARGE_DATE_RANGE | ...")
    message: str = Field(..., description="الرسالة بالعربية")


class ChunkPlan(BaseModel):
    """
    وصف chunk واحد في خطة التنفيذ — يُعرض في Pre-flight Summary
    ليرى المستخدم بالضبط كيف سيُقسَّم طلبه.
    Evidence: system design §4 Pre-flight Engine.
    """
    chunk_index:   int
    label:         str            = Field(..., description="1-7 فبراير 2026")
    date_from:     Optional[str]  = None
    date_to:       Optional[str]  = None
    entity_id:     Optional[str]  = None
    region_key:    Optional[str]  = None
    fr24_endpoint: str
    estimated_credits: int


class PreflightSummary(BaseModel):
    """
    ملخص ما قبل التنفيذ — يُعرض للمستخدم قبل ضغط إطلاق.
    Evidence: system design §4:
    "سيقوم النظام بتقسيم طلبك إلى N مكالمة API.
     التكلفة التقديرية: X نقطة. الجدول الزمني: Y دقائق."
    """
    operation_id:  int
    operation_ref: str
    capability_type: str
    capability_label: str         = Field(..., description="رصد حي | ملخصات الرحلات | ...")

    # Estimates
    estimated_chunks:   int
    estimated_api_calls: int
    estimated_credits:  int
    estimated_duration_seconds: int
    estimated_duration_label:   str  = Field(..., description="4 دقائق | 45 ثانية | ...")
    estimated_results:  int

    # Cost context
    # Evidence: §4 "💡 نصيحة: رصيدك الحالي (X نقطة) يكفي"
    current_credits_balance: Optional[int] = None
    credits_sufficient:      Optional[bool] = None

    # Execution plan breakdown
    chunk_plan: List[ChunkPlan] = Field(
        ...,
        description="قائمة الـ chunks التي سيُنفَّذ كل منها بمكالمة API واحدة"
    )

    # Warnings
    warnings: List[PreflightWarning] = Field(
        default_factory=list,
        description="تحذيرات مثل نطاق زمني كبير أو رصيد منخفض"
    )


# ── Chunk Status (for live tracking) ──────────────────────────────────────

class ChunkProgressItem(BaseModel):
    """
    حالة chunk واحد في لوحة التتبع.
    Evidence: system design §2 + §6:
    "يتم الآن جلب الفترة من X... (مكتمل) ✅ | جاري ⏳ | في الانتظار ⏸️"
    """
    model_config = ConfigDict(from_attributes=True)

    chunk_index:    int
    label:          str            = Field(..., description="تسمية بشرية: 1-7 مارس")
    date_from:      Optional[str]  = None
    date_to:        Optional[str]  = None
    entity_id:      Optional[str]  = None
    region_key:     Optional[str]  = None
    fr24_endpoint:  Optional[str]  = None

    status:         str
    # pending | running | completed | failed | cancelled | skipped

    attempt_count:  int            = 0
    results_count:  int            = 0
    credits_used:   int            = 0

    started_at:     Optional[datetime] = None
    completed_at:   Optional[datetime] = None
    next_retry_at:  Optional[datetime] = None
    last_error:     Optional[str]  = None
    http_status:    Optional[int]  = None

    # FR24 call details — exposed so UI can show which endpoint was called
    # Evidence: system design §2 Chunk Model — fr24_params stored per chunk
    fr24_params:        Optional[Dict[str, Any]] = None

    # Partial result key for direct DB query to this chunk's data
    # Evidence: system design §6 "partial_result_key = 'op:{id}:chunk:{id}'"
    partial_result_key: Optional[str] = None

    # UI display helpers
    status_icon:    str            = Field("⏸️", description="✅ | ⏳ | ❌ | ⏸️ | ⏭️")
    status_label:   str            = Field("في الانتظار", description="عربي")


# ── Operation Response ─────────────────────────────────────────────────────

class OperationResponse(BaseModel):
    """
    استجابة GET /api/v1/operations/{id}
    الملف الكامل للعملية مع قائمة الـ chunks.
    Evidence: system design §1 Operation Model.
    """
    model_config = ConfigDict(from_attributes=True)

    id:            int
    operation_ref: str
    capability_type: str

    # Scope
    scope_region_key:  Optional[str]  = None
    scope_date_from:   Optional[date] = None
    scope_date_to:     Optional[date] = None
    scope_entity_id:   Optional[str]  = None
    scope_entity_type: Optional[str]  = None
    scope_filters:     Optional[Dict[str, Any]] = None
    scope_bounds:      Optional[Dict[str, Any]] = None

    # Estimates
    estimated_chunks:           int = 0
    estimated_api_calls:        int = 0
    estimated_credits:          int = 0
    estimated_duration_seconds: int = 0
    estimated_results:          int = 0

    # Actuals
    actual_api_calls:        int = 0
    actual_credits_used:     int = 0
    actual_duration_seconds: Optional[int] = None
    total_results_count:     int = 0

    # State
    status:          str
    progress_pct:    float = 0.0
    chunks_total:    int = 0
    chunks_completed:int = 0
    chunks_failed:   int = 0
    chunks_cancelled:int = 0

    # Approval gate
    preflight_shown_at: Optional[datetime] = None
    approved_at:        Optional[datetime] = None

    # Lifecycle
    created_at:   Optional[datetime] = None
    started_at:   Optional[datetime] = None
    completed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None

    # Cancellation
    cancel_requested: bool = False
    cancel_reason:    Optional[str] = None
    failure_reason:   Optional[str] = None

    # Chunks list (populated on detail view)
    chunks: Optional[List[ChunkProgressItem]] = None


class OperationListResponse(BaseModel):
    """
    استجابة GET /api/v1/operations (قائمة)
    Evidence: §6 لوحة تتبع المهمات — عرض جميع العمليات.
    """
    total:     int
    page:      int
    page_size: int
    pages:     int
    data:      List[OperationResponse]


# ── Live Progress ──────────────────────────────────────────────────────────

class OperationProgressResponse(BaseModel):
    """
    استجابة GET /api/v1/operations/{id}/progress
    مُصمَّم للـ polling كل 3 ثوانٍ من الواجهة.
    مُحسَّن: يُعيد فقط بيانات التقدم بلا scope الكاملة.
    Evidence: system design §6 Monitoring:
    "operation_progress_view — polling every 3s"
    """
    id:            int
    operation_ref: str
    capability_type: str
    status:        str

    # Progress counters
    chunks_total:     int
    chunks_completed: int
    chunks_failed:    int
    chunks_cancelled: int
    progress_pct:     float

    # Live data
    total_results_count: int
    actual_credits_used: int
    estimated_credits:   int

    cancel_requested: bool

    # Timestamps
    created_at:   Optional[datetime] = None
    started_at:   Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Current running chunk (from VIEW current_chunk JSON)
    current_chunk:        Optional[Dict[str, Any]] = None
    # Last completed chunk (from VIEW last_completed_chunk JSON)
    last_completed_chunk: Optional[Dict[str, Any]] = None

    # Computed for UI
    # Evidence: §2 الفلسفة "الشريط الكوني: مهمات نشطة، نقاط متبقية"
    is_terminal:      bool = False
    can_be_cancelled: bool = False


# ── ApiCreditRate (admin/info) ─────────────────────────────────────────────

class ApiCreditRateResponse(BaseModel):
    """
    استجابة GET /api/v1/operations/credit-rates
    تُعرض في Pre-flight لإعطاء المستخدم سياقاً.
    Evidence: system design §4 Pre-flight Engine — credit rate table.
    """
    model_config = ConfigDict(from_attributes=True)

    capability_type:           str
    credits_per_call:          int
    credits_per_record:        float
    avg_call_duration_seconds: float
    avg_results_per_call:      int
    notes:                     Optional[str] = None


# ── Partial Results ────────────────────────────────────────────────────────

class PartialResultsSummary(BaseModel):
    """
    ملخص النتائج الجزئية المتاحة الآن.
    Evidence: system design §6 Partial Results Strategy:
    "أريد أن أتمكن من رؤية نتائج الأسبوع الأول
     بمجرد أن يصبح جاهزًا، ولا أنتظر حتى تكتمل العملية."
    """
    operation_id:    int
    operation_ref:   str
    status:          str
    results_available: int   = Field(..., description="عدد النتائج الجاهزة الآن")
    chunks_ready:    int     = Field(..., description="عدد الـ chunks المكتملة")
    chunks_total:    int
    export_url:      Optional[str] = Field(
        None, description="رابط تصدير CSV للنتائج الجاهزة الآن"
    )

