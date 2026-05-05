/**
 * API Client — v4.0 (TIER 4 Updated)
 * Adds /api/v1/* endpoints for all new backend routes.
 * Legacy endpoints (without /api/v1 prefix) kept for backward compat.
 *
 * Evidence: business requirement — all endpoints under /api/v1/
 * frontend must call ONLY real API endpoints (FRONTEND REALISM RULE).
 */
import axios, { AxiosInstance, AxiosError } from 'axios';
import type {
  FlightListResponse, FlightFilterParams,
  FlightStatistics, HealthCheck, Airline,
  LivePositionsResponse, LivePosition,
  FlightDetail, FlightSearchResponse,
  TrajectoryResponse, FlightSearchItem,
  DailySummary, AirlinePerformanceResponse,
  CreditsUsageResponse, AnalyticsSummary,
  HistoryQueryRequest, HistoryQueryResponse,
  IngestionJobListResponse, IngestionJob,
  GeoRegion, RouteStats, AirportStats,
} from '@/types';

const apiClient: AxiosInstance = axios.create({
  baseURL: '',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
});

apiClient.interceptors.request.use(
  (config) => {
    if (import.meta.env.DEV) {
      console.log(`[API] ${config.method?.toUpperCase()} ${config.url}`);
    }
    return config;
  },
  (error) => Promise.reject(error),
);

apiClient.interceptors.response.use(
  (r) => r,
  (error: AxiosError) => {
    if (import.meta.env.DEV) {
      console.error('[API Error]', error.response?.data || error.message);
    }
    return Promise.reject(error);
  },
);

// ─────────────────────────────────────────────────────────────────────────────
// LIVE POSITIONS (v1) — GET /api/v1/live/positions
// Evidence: business requirement + backend live.py
// ─────────────────────────────────────────────────────────────────────────────
export const liveApi = {
  getPositions: async (params: {
    region_key?: string;
    on_ground?: boolean;
    limit?: number;
    page?: number;
  } = {}): Promise<LivePositionsResponse> =>
    (await apiClient.get('/api/v1/live/positions', { params })).data,
};

// ─────────────────────────────────────────────────────────────────────────────
// FLIGHTS (v1)
// ─────────────────────────────────────────────────────────────────────────────
export const flightsV1Api = {
  search: async (params: {
    callsign?: string;
    icao24?: string;
    fr24_id?: string;
    flight_number?: string;
    operator_icao?: string;
    dep_icao?: string;
    arr_icao?: string;
    status?: string;
    date_from?: string;
    date_to?: string;
    page?: number;
    page_size?: number;
    export_csv?: boolean;
  }): Promise<FlightSearchResponse> =>
    (await apiClient.get('/api/v1/flights/search', { params })).data,

  getById: async (sessionId: number, includeTrajectory = false): Promise<FlightDetail> =>
    (await apiClient.get(`/api/v1/flights/${sessionId}`, {
      params: { include_trajectory: includeTrajectory },
    })).data,

  getTrajectory: async (sessionId: number): Promise<TrajectoryResponse> =>
    (await apiClient.get(`/api/v1/flights/${sessionId}/trajectory`)).data,

  exportCsv: (params: Record<string, unknown>): string => {
    const q = new URLSearchParams(params as Record<string, string>).toString();
    return `/api/v1/flights/search?${q}&export_csv=true`;
  },
};

// ─────────────────────────────────────────────────────────────────────────────
// AIRCRAFT HISTORY (v1)
// ─────────────────────────────────────────────────────────────────────────────
export const aircraftApi = {
  getHistory: async (icao24: string, params: {
    date_from?: string;
    date_to?: string;
    page?: number;
    page_size?: number;
  } = {}): Promise<FlightSearchResponse> =>
    (await apiClient.get(`/api/v1/aircraft/${icao24}/history`, { params })).data,
};

// ─────────────────────────────────────────────────────────────────────────────
// ANALYTICS (v1)
// ─────────────────────────────────────────────────────────────────────────────
export const analyticsV1Api = {
  getTopRoutes: async (params: {
    limit?: number;
    date_from?: string;
    date_to?: string;
  } = {}): Promise<{ total: number; data: RouteStats[] }> =>
    (await apiClient.get('/api/v1/analytics/top-routes', { params })).data,

  getBusiestAirports: async (params: {
    limit?: number;
    date_from?: string;
    date_to?: string;
  } = {}): Promise<{ total: number; data: AirportStats[] }> =>
    (await apiClient.get('/api/v1/analytics/busiest-airports', { params })).data,

  getDailySummary: async (date?: string): Promise<DailySummary> =>
    (await apiClient.get('/api/v1/analytics/daily-summary', {
      params: date ? { date } : {},
    })).data,

  getAirlinePerformance: async (params: {
    date_from?: string;
    date_to?: string;
    page?: number;
    page_size?: number;
  } = {}): Promise<AirlinePerformanceResponse> =>
    (await apiClient.get('/api/v1/analytics/airline-performance', { params })).data,

  exportCsvUrl: (reportType: 'routes' | 'airports' | 'airlines', params: Record<string, string> = {}): string => {
    const q = new URLSearchParams({ report_type: reportType, ...params }).toString();
    return `/api/v1/analytics/export-csv?${q}`;
  },
};

// ─────────────────────────────────────────────────────────────────────────────
// HISTORY ENGINE (v1)
// ─────────────────────────────────────────────────────────────────────────────
export const historyApi = {
  query: async (body: HistoryQueryRequest): Promise<HistoryQueryResponse> =>
    (await apiClient.post('/api/v1/history/query', body)).data,

  exportCsvUrl: (params: {
    entity_type: string;
    entity_id: string;
    date_from?: string;
    date_to?: string;
  }): string => {
    const q = new URLSearchParams(params as Record<string, string>).toString();
    return `/api/v1/history/export?${q}`;
  },
};

// ─────────────────────────────────────────────────────────────────────────────
// SYSTEM (v1)
// ─────────────────────────────────────────────────────────────────────────────
export const systemApi = {
  getCreditsUsage: async (): Promise<CreditsUsageResponse> =>
    (await apiClient.get('/api/v1/system/credits-usage')).data,

  getStatus: async () =>
    (await apiClient.get('/api/v1/system/status')).data,
};

// ─────────────────────────────────────────────────────────────────────────────
// INGESTION (v1)
// ─────────────────────────────────────────────────────────────────────────────
export const ingestionApi = {
  listJobs: async (params: {
    status?: string;
    region_key?: string;
    page?: number;
    page_size?: number;
  } = {}): Promise<IngestionJobListResponse> =>
    (await apiClient.get('/api/v1/ingestion/jobs', { params })).data,

  getJob: async (id: number): Promise<IngestionJob> =>
    (await apiClient.get(`/api/v1/ingestion/jobs/${id}`)).data,

  startIngestion: async (body: {
    begin_date: string;
    end_date: string;
    region_keys: string[];
    force_reingest?: boolean;
  }) => (await apiClient.post('/api/v1/ingestion/start', body)).data,
};

// ─────────────────────────────────────────────────────────────────────────────
// REGIONS (legacy — no v1 version needed)
// ─────────────────────────────────────────────────────────────────────────────
export const regionsApi = {
  listRegions: async (): Promise<GeoRegion[]> =>
    (await apiClient.get('/regions')).data,
  getRegion: async (key: string): Promise<GeoRegion> =>
    (await apiClient.get(`/regions/${key}`)).data,
};

// ─────────────────────────────────────────────────────────────────────────────
// LEGACY API (kept for backward compat with existing sections during migration)
// ─────────────────────────────────────────────────────────────────────────────
export const flightsApi = {
  getFlights: async (page = 1, pageSize = 500): Promise<FlightListResponse> =>
    (await apiClient.get('/flights', { params: { page, page_size: pageSize } })).data,

  filterFlights: async (params: FlightFilterParams): Promise<FlightListResponse> =>
    (await apiClient.get('/flights', { params })).data,

  getFlight: async (id: number) =>
    (await apiClient.get(`/api/v1/flights/${id}`)).data,
};

export const airlinesApi = {
  getAirlines: async (skip = 0, limit = 100): Promise<Airline[]> =>
    (await apiClient.get('/airlines', { params: { skip, limit } })).data,
};

export const statsApi = {
  getStatistics: async (): Promise<FlightStatistics> =>
    (await apiClient.get('/stats')).data,
  healthCheck: async (): Promise<HealthCheck> =>
    (await apiClient.get('/stats/health')).data,
};

// Legacy analytics — kept for AnalyticsSection backward compat
export const analyticsApi = {
  getTopCountries: async (params: Record<string, unknown> = {}) =>
    (await apiClient.get('/analytics/top_countries', { params })).data,
  getTopAirports: async (params: Record<string, unknown> = {}) =>
    (await apiClient.get('/api/v1/analytics/busiest-airports', { params })).data,
  getTopRoutes: async (params: Record<string, unknown> = {}) =>
    (await apiClient.get('/api/v1/analytics/top-routes', { params })).data,
  getSummary: async (params: Record<string, unknown> = {}) =>
    (await apiClient.get('/analytics/summary', { params })).data,
};

export default apiClient;
