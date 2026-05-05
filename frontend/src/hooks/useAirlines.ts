import { useState, useEffect, useCallback } from 'react';
import { airlinesApi } from '@/api/client';
import { Airline } from '@/types';

interface UseAirlinesReturn {
  data: Airline[];
  loading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
}

export const useAirlines = (skip: number = 0, limit: number = 100): UseAirlinesReturn => {
  const [data, setData] = useState<Airline[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchAirlines = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await airlinesApi.getAirlines(skip, limit);
      setData(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch airlines');
    } finally {
      setLoading(false);
    }
  }, [skip, limit]);

  useEffect(() => {
    fetchAirlines();
  }, [fetchAirlines]);

  return { data, loading, error, refetch: fetchAirlines };
};
