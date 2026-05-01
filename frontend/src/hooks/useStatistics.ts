import { useState, useEffect, useCallback } from 'react';
import { statsApi } from '@/api/client';
import { FlightStatistics } from '@/types';

interface UseStatisticsReturn {
  data: FlightStatistics | null;
  loading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
}

export const useStatistics = (): UseStatisticsReturn => {
  const [data, setData] = useState<FlightStatistics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchStatistics = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await statsApi.getStatistics();
      setData(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch statistics');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatistics();
  }, [fetchStatistics]);

  return { data, loading, error, refetch: fetchStatistics };
};

interface UseHealthCheckReturn {
  healthy: boolean;
  loading: boolean;
  error: string | null;
}

export const useHealthCheck = (): UseHealthCheckReturn => {
  const [healthy, setHealthy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const checkHealth = async () => {
      try {
        setLoading(true);
        const response = await statsApi.healthCheck();
        setHealthy(response.status === 'healthy');
      } catch (err) {
        setHealthy(false);
        setError(err instanceof Error ? err.message : 'Health check failed');
      } finally {
        setLoading(false);
      }
    };

    checkHealth();
    const interval = setInterval(checkHealth, 30000); // Check every 30 seconds
    return () => clearInterval(interval);
  }, []);

  return { healthy, loading, error };
};
