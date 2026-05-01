// ─────────────────────────────────────────────────────────────────────────────
// LEGACY TYPES (preserved for backward compat with existing sections)
// ─────────────────────────────────────────────────────────────────────────────

export interface Flight {
  id: number;
  icao24: string;
  callsign: string | null;
  airline_id: number | null;
  origin_country: string | null;
  first_seen: number | null;
  last_seen: number | null;
  est_departure_airport: string | null;
  est_arrival_airport:   string | null;
  duration_seconds: number | null;
  duration_minutes: number | null;
  duration_hours:   number | null;
  latitude?:  number | null;
  longitude?: number | null;
  altitude?:  number | null;
  velocity?:  number | null;
  heading?:   number | null;
  on_ground?: boolean | null;
  region_key?: string | null;
  trajectory?: TrajectoryPoint[] | null;
}

export interface TrajectoryPoint {
  ts:  number;
  lat: number;
  lon: number;
  alt?:  number;
  vel?:  number;
  hdg?:  number;
  vspd?: number;
}

export interface Airline {
  id: number;
  icao24: string;
  name:   string | null;
  callsign_prefix: string | null;
  country_id: number | null;
  created_at: string;
  flight_count?: number;
}

export interface Country {
  id:       number;
  name:     string;
  iso_code: string | null;
  created_at: string;
}

export interface FlightListResponse {
  total:     number;
  page:      number;
  page_size: number;
  pages:     number;
  data:      Flight[];
}

export interface FlightFilterParams {
  airline_id?:        number;
  country?:           string;
  date_from?:         string;
  date_to?:           string;
  departure_airport?: string;
  arrival_airport?:   string;
  region_key?:        string;
  page?:              number;
  page_size?:         number;
}

export interface DailyFlightStats     { date: string; flight_count: number }
export interface AirlineActivityStats { airline_icao24: string; airline_name: string | null; flight_count: number }
export interface CountryActivityStats { country_name: string; flight_count: number }

export interface FlightStatistics {
  total_flights:      number;
  daily_stats:        DailyFlightStats[];
  top_airlines:       AirlineActivityStats[];
  top_countries:      CountryActivityStats[];
  flights_today:      number;
  flights_this_week:  number;
  flights_this_month: number;
}

export interface HealthCheck {
  status:    string;
  timestamp: string;
  database:  string;
  version:   string;
}

export interface ApiResponse<T> { data: T; message?: string; error?: string }

// ─────────────────────────────────────────────────────────────────────────────
// FR24 API TYPES (v1 — aligned with backend schemas.py)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * LivePositionResponse — from GET /api/v1/live/positions
 * Maps exactly to CurrentAircraftState + schemas.LivePositionResponse
 */
export interface LivePosition {
  icao24:          string;
  fr24_id:         string | null;
  callsign:        string | null;
  flight_number:   string | null;
  operator_name:   string | null;
  aircraft_model:  string | null;
  aircraft_type:   string | null;
  dep_airport_iata: string | null;
  arr_airport_iata: string | null;
  latitude:        number | null;
  longitude:       number | null;
  altitude_m:      number | null;
  velocity_kmh:    number | null;
  heading_deg:     number | null;
  vspeed_fpm:      number | null;
  on_ground:       boolean | null;
  squawk:          string | null;
  region_key:      string | null;
  last_updated:    string | null;
  session_id:      number | null;
}

export interface LivePositionsResponse {
  total:  number;
  active: number;
  data:   LivePosition[];
}

/**
 * Airport / Operator sub-objects in flight details
 */
export interface AirportRef {
  icao_code: string | null;
  iata_code: string | null;
  name:      string | null;
}

export interface OperatorRef {
  icao_code: string | null;
  name:      string | null;
}

export interface AircraftRef {
  icao24:       string | null;
  registration: string | null;
  type_code:    string | null;
  model:        string | null;
}

/**
 * FlightDetailResponse — from GET /api/v1/flights/{session_id}
 */
export interface FlightDetail {
  session_id:    number;
  fr24_id:       string | null;
  flight_number: string | null;
  callsign:      string | null;
  flight_status: string | null;
  first_seen_ts: string | null;
  last_seen_ts:  string | null;
  actual_takeoff_ts:  string | null;
  actual_landing_ts:  string | null;
  duration_seconds:   number | null;
  max_altitude_m:     number | null;
  total_distance_km:  number | null;
  aircraft:    AircraftRef  | null;
  operator:    OperatorRef  | null;
  dep_airport: AirportRef   | null;
  arr_airport: AirportRef   | null;
  trajectory?: TrajectoryResponse | null;
}

/**
 * TrajectoryResponse — from GET /api/v1/flights/{session_id}/trajectory
 */
export interface TrajectoryResponse {
  session_id: number;
  fr24_id:    string | null;
  callsign:   string | null;
  points:     TrajectoryPoint[];
}

/**
 * Search result item (same shape as FlightDetail but no trajectory)
 */
export type FlightSearchItem = Omit<FlightDetail, 'trajectory'>;

export interface FlightSearchResponse {
  total:     number;
  page:      number;
  page_size: number;
  pages:     number;
  data:      FlightSearchItem[];
}

// ─────────────────────────────────────────────────────────────────────────────
// ANALYTICS TYPES
// ─────────────────────────────────────────────────────────────────────────────

export interface RouteStats    { departure: string; arrival: string; flight_count: number }
export interface AirportStats  { airport_icao: string; flight_count: number; as_departure: number; as_arrival: number }
export interface CountryStats  { country_name: string; flight_count: number }
export interface DailyStats    { date: string; flight_count: number }
export interface HourlyStats   { hour: number; flight_count: number }

export interface DailySummary {
  date:             string;
  total_flights:    number;
  active_flights:   number;
  landed_flights:   number;
  emergency_events: number;
  unique_aircraft:  number;
  unique_operators: number;
  top_routes:       RouteStats[];
}

export interface AirlinePerformanceItem {
  operator_icao:           string;
  operator_name:           string | null;
  total_flights:           number;
  active_flights:          number;
  avg_flight_duration_min: number | null;
  total_distance_km:       number | null;
}

export interface AirlinePerformanceResponse {
  total: number;
  data:  AirlinePerformanceItem[];
}

export interface CreditsUsageItem { endpoint: string; request_count: number; credits: number }
export interface CreditsUsageResponse { data: CreditsUsageItem[]; total_credits: number }

export interface AnalyticsSummary {
  total_flights:    number;
  unique_countries: number;
  unique_airports:  number;
  top_countries:    CountryStats[];
}

// ─────────────────────────────────────────────────────────────────────────────
// HISTORY ENGINE TYPES
// ─────────────────────────────────────────────────────────────────────────────

export type HistoryEntityType = 'aircraft' | 'airport' | 'airline' | 'country' | 'region';

export interface HistoryQueryRequest {
  entity_type: HistoryEntityType;
  entity_id:   string;
  date_from?:  string;
  date_to?:    string;
  page?:       number;
  page_size?:  number;
}

export interface HistoryAggregations {
  total_flights:     number;
  unique_aircraft:   number;
  unique_operators:  number;
  total_distance_km: number | null;
  avg_duration_min:  number | null;
  top_routes:        RouteStats[];
}

export interface HistoryQueryResponse {
  entity_type:  string;
  entity_id:    string;
  total:        number;
  page:         number;
  page_size:    number;
  pages:        number;
  data:         FlightSearchItem[];
  aggregations: HistoryAggregations | null;
}

// ─────────────────────────────────────────────────────────────────────────────
// INGESTION TYPES
// ─────────────────────────────────────────────────────────────────────────────

export interface GeoRegion {
  key:        string;
  name:       string;
  name_ar:    string;
  lamin:      number;
  lomin:      number;
  lamax:      number;
  lomax:      number;
  center_lat: number;
  center_lon: number;
}

export interface IngestionJob {
  id:         number;
  region_key: string;
  status:     'pending' | 'running' | 'completed' | 'failed';
  job_type:   string | null;
  date_str:   string | null;
  lamin: number | null; lomin: number | null;
  lamax: number | null; lomax: number | null;
  begin_ts:         number | null;
  end_ts:           number | null;
  flights_ingested: number;
  chunks_total:     number;
  chunks_done:      number;
  records_processed: number;
  credits_used:      number;
  error_message:     string | null;
  created_at:        string | null;
  started_at:        string | null;
  completed_at:      string | null;
}

export interface IngestionJobListResponse {
  total:     number;
  page:      number;
  page_size: number;
  pages:     number;
  data:      IngestionJob[];
}
