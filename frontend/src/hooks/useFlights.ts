import { useState, useEffect, useCallback } from 'react';
import { flightsApi } from '@/api/client';
import { FlightListResponse, FlightFilterParams } from '@/types';

interface UseFlightsReturn {
  data: FlightListResponse | null;
  loading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
}

export const useFlights = (page: number = 1, pageSize: number = 50): UseFlightsReturn => {
  const [data, setData] = useState<FlightListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchFlights = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await flightsApi.getFlights(page, pageSize);
      setData(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch flights');
    } finally {
      setLoading(false);
    }
  }, [page, pageSize]);

  useEffect(() => {
    fetchFlights();
  }, [fetchFlights]);

  return { data, loading, error, refetch: fetchFlights };
};

export const useFilteredFlights = (params: FlightFilterParams): UseFlightsReturn => {
  const [data, setData] = useState<FlightListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchFilteredFlights = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await flightsApi.filterFlights(params);
      setData(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch filtered flights');
    } finally {
      setLoading(false);
    }
  }, [params]);

  useEffect(() => {
    fetchFilteredFlights();
  }, [fetchFilteredFlights]);

  return { data, loading, error, refetch: fetchFilteredFlights };
};
