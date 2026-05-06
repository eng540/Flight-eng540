"""
Enterprise Pydantic Schemas (v3.2 — Multi-Source Ready)
Strict validation and typing for the Snowflake Architecture.

CHANGES FROM v3.1:
  RawIngestionPayload     → +data_source
  LivePositionResponse    → +data_source
                            Evidence: Support for OpenSky, AirLabs, and FR24.
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Any, Dict
from datetime import datetime, date

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
    id: int


class DimOperatorBase(BaseModel):
    icao_code:     Optional[str] = Field(None, max_length=3)
    iata_code:     Optional[str] = Field(None, max_length=2)
    name:          str           = Field(..., max_length=255)
    country_code:  Optional[str] = Field(None, max_length=2)
    operator_type: Optional[str] = Field(None, max_length=50)

class DimOperatorResponse(DimOperatorBase):
    model_config = ConfigDict(from_attributes=True)
    id: int


class DimAircraftBase(BaseModel):
    icao24:       str            = Field(..., min_length=4, max_length=6)
    registration: Optional[str]  = Field(None, max_length=20)
    manufacturer: Optional[str]  = Field(None, max_length=100)
    model:        Optional[str]  = Field(None, max_length=100)
    type_code:    Optional[str]  = Field(None, max_length=10)

class DimAircraftResponse(DimAircraftBase):
    model_config = ConfigDict(from_attributes=True)
    id:       int
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
    vspeed_fpm:   Optional[float] = None
    is_on_ground: Optional[bool]  = False
    squawk:       Optional[str]   = None
    data_source:  Optional[str]   = None

class TrackTelemetryResponse(TrackTelemetryBase):
    model_config = ConfigDict(from_attributes=True)


class FlightSessionBase(BaseModel):
    callsign:       Optional[str] = Field(None, max_length=20)
    fr24_id:        Optional[str] = None
    flight_number:  Optional[str] = None
    first_seen_ts:  datetime
    last_seen_ts:   datetime
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
    data:      List[FlightSessionResponse]


# ═════════════════════════════════════════════════════════════════════════════
# 3. LIVE MAP (Denormalized Fast Response)
# ═════════════════════════════════════════════════════════════════════════════

class LivePositionResponse(BaseModel):
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
    data_source:   Optional[str]   = None


# ═════════════════════════════════════════════════════════════════════════════
# 4. FLIGHT DETAIL (Full session + trajectory)
# ═════════════════════════════════════════════════════════════════════════════

class TrajectoryPoint(BaseModel):
    ts:  int
    lat: float
    lon: float
    alt: Optional[float] = None
    vel: Optional[float] = None
    hdg: Optional[float] = None
    vspd: Optional[float] = None
    src: Optional[str] = None

class TrajectoryResponse(BaseModel):
    session_id: int
    fr24_id:    Optional[str] = None
    callsign:   Optional[str] = None
    points:     List[TrajectoryPoint]

class FlightDetailResponse(BaseModel):
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
    icao24:        str
    fr24_id:       Optional[str]   = None
    callsign:      Optional[str]   = None
    flight_number: Optional[str]   = None
    registration:  Optional[str]   = None
    aircraft_type: Optional[str]   = None
    operator_iata: Optional[str]   = None
    operator_icao: Optional[str]   = None
    origin_country: Optional[str]  = None
    timestamp:     int
    longitude:     float
    latitude:      float
    altitude:      Optional[float] = 0.0
    velocity:      Optional[float] = 0.0
    heading:       Optional[float] = None
    vspeed_fpm:    Optional[float] = None
    on_ground:     Optional[bool]  = False
    est_departure_airport: Optional[str] = None
    est_arrival_airport:   Optional[str] = None
    region_key:    Optional[str]   = "global"
    squawk:        Optional[str]   = None
    data_source:   Optional[str]   = None


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
    date:              str
    total_flights:     int
    active_flights:    int
    landed_flights:    int
    emergency_events:  int
    unique_aircraft:   int
    unique_operators:  int
    top_routes:        List[RouteStats] = []

class AirlinePerformanceItem(BaseModel):
    operator_icao:           str
    operator_name:           Optional[str] = None
    total_flights:           int
    active_flights:          int = 0
    avg_flight_duration_min: Optional[float] = None
    total_distance_km:       Optional[float] = None

class AirlinePerformanceResponse(BaseModel):
    total: int
    data:  List[AirlinePerformanceItem]

class CreditsUsageItem(BaseModel):
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
    data:         List[FlightSearchItem]
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
    version:   str = "3.3.0-MultiSource"


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
# 10. INGESTION JOB
# ═════════════════════════════════════════════════════════════════════════════

class IngestionJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id:         int
    region_key: str
    status:     str
    job_type:   Optional[str] = None
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
# OPERATIONS BOARD SCHEMAS
# ═════════════════════════════════════════════════════════════════════════════

class ScopeDefinition(BaseModel):
    region_key:   Optional[str]       = Field(None, description="مفتاح المنطقة الجغرافية")
    date_from:    Optional[str]       = Field(None, description="YYYY-MM-DD")
    date_to:      Optional[str]       = Field(None, description="YYYY-MM-DD inclusive")
    entity_id:    Optional[str]       = Field(None, description="ICAO24, flight_id, airport_code...")
    entity_type:  Optional[str]       = Field(None, description="aircraft|airport|airline|route")
    entity_ids:   Optional[List[str]] = Field(None, description="لطلبات متعددة الكيانات")
    filters:      Optional[Dict[str, Any]] = Field(None, description="فلاتر إضافية")
    bounds:       Optional[Dict[str, float]] = Field(None)

class OperationCreateRequest(BaseModel):
    capability_type: str = Field(
        ...,
        pattern="^(live_positions|flight_summaries|flight_tracks|"
                "historic_positions|historic_events|static_airport|static_airline)$",
    )
    scope: ScopeDefinition = Field(..., description="نطاق الطلب")

class OperationApproveRequest(BaseModel):
    confirmed: bool = Field(..., description="يجب أن تكون True")

class OperationCancelRequest(BaseModel):
    reason: Optional[str] = Field(None, max_length=255)

class PreflightWarning(BaseModel):
    level:   str = Field(..., description="info | warning | critical")
    code:    str = Field(...)
    message: str = Field(...)

class ChunkPlan(BaseModel):
    chunk_index:   int
    label:         str
    date_from:     Optional[str]  = None
    date_to:       Optional[str]  = None
    entity_id:     Optional[str]  = None
    region_key:    Optional[str]  = None
    fr24_endpoint: str
    estimated_credits: int

class PreflightSummary(BaseModel):
    operation_id:  int
    operation_ref: str
    capability_type: str
    capability_label: str
    estimated_chunks:   int
    estimated_api_calls: int
    estimated_credits:  int
    estimated_duration_seconds: int
    estimated_duration_label:   str
    estimated_results:  int
    current_credits_balance: Optional[int] = None
    credits_sufficient:      Optional[bool] = None
    chunk_plan: List[ChunkPlan]
    warnings: List[PreflightWarning]

class ChunkProgressItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    chunk_index:    int
    label:          str
    date_from:      Optional[str]  = None
    date_to:        Optional[str]  = None
    entity_id:      Optional[str]  = None
    region_key:     Optional[str]  = None
    fr24_endpoint:  Optional[str]  = None
    status:         str
    attempt_count:  int            = 0
    results_count:  int            = 0
    credits_used:   int            = 0
    started_at:     Optional[datetime] = None
    completed_at:   Optional[datetime] = None
    next_retry_at:  Optional[datetime] = None
    last_error:     Optional[str]  = None
    http_status:    Optional[int]  = None
    fr24_params:        Optional[Dict[str, Any]] = None
    partial_result_key: Optional[str] = None
    status_icon:    str
    status_label:   str

class OperationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id:            int
    operation_ref: str
    capability_type: str
    scope_region_key:  Optional[str]  = None
    scope_date_from:   Optional[date] = None
    scope_date_to:     Optional[date] = None
    scope_entity_id:   Optional[str]  = None
    scope_entity_type: Optional[str]  = None
    scope_filters:     Optional[Dict[str, Any]] = None
    scope_bounds:      Optional[Dict[str, Any]] = None
    estimated_chunks:           int = 0
    estimated_api_calls:        int = 0
    estimated_credits:          int = 0
    estimated_duration_seconds: int = 0
    estimated_results:          int = 0
    actual_api_calls:        int = 0
    actual_credits_used:     int = 0
    actual_duration_seconds: Optional[int] = None
    total_results_count:     int = 0
    status:          str
    progress_pct:    float = 0.0
    chunks_total:    int = 0
    chunks_completed:int = 0
    chunks_failed:   int = 0
    chunks_cancelled:int = 0
    preflight_shown_at: Optional[datetime] = None
    approved_at:        Optional[datetime] = None
    created_at:   Optional[datetime] = None
    started_at:   Optional[datetime] = None
    completed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    cancel_requested: bool = False
    cancel_reason:    Optional[str] = None
    failure_reason:   Optional[str] = None
    chunks: Optional[List[ChunkProgressItem]] = None

class OperationListResponse(BaseModel):
    total:     int
    page:      int
    page_size: int
    pages:     int
    data:      List[OperationResponse]

class OperationProgressResponse(BaseModel):
    id:            int
    operation_ref: str
    capability_type: str
    status:        str
    chunks_total:     int
    chunks_completed: int
    chunks_failed:    int
    chunks_cancelled: int
    progress_pct:     float
    total_results_count: int
    actual_credits_used: int
    estimated_credits:   int
    cancel_requested: bool
    created_at:   Optional[datetime] = None
    started_at:   Optional[datetime] = None
    completed_at: Optional[datetime] = None
    current_chunk:        Optional[Dict[str, Any]] = None
    last_completed_chunk: Optional[Dict[str, Any]] = None
    is_terminal:      bool = False
    can_be_cancelled: bool = False

class ApiCreditRateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    capability_type:           str
    credits_per_call:          int
    credits_per_record:        float
    avg_call_duration_seconds: float
    avg_results_per_call:      int
    notes:                     Optional[str] = None

class PartialResultsSummary(BaseModel):
    operation_id:    int
    operation_ref:   str
    status:          str
    results_available: int
    chunks_ready:    int
    chunks_total:    int
    export_url:      Optional[str] = None