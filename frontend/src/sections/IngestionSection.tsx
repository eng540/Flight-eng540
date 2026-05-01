import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { ingestionApi, regionsApi } from '@/api/client';
import { GeoRegion, IngestionJob } from '@/types';

const STATUS_BADGE: Record<string, 'default'|'secondary'|'outline'|'destructive'> = {
  pending:   'secondary',
  running:   'default',
  completed: 'outline',
  failed:    'destructive',
};

const STATUS_ICON: Record<string, string> = {
  pending: '⏳', running: '🔄', completed: '✅', failed: '❌',
};

export function IngestionSection() {
  const [regions, setRegions]         = useState<GeoRegion[]>([]);
  const [jobs,    setJobs]            = useState<IngestionJob[]>([]);
  const [total,   setTotal]           = useState(0);
  const [loading, setLoading]         = useState(false);
  const [page,    setPage]            = useState(1);

  // Form state
  const [beginDate,     setBeginDate]     = useState('2026-02-01');
  const [endDate,       setEndDate]       = useState('2026-04-08');
  const [selectedRegions, setSelectedRegions] = useState<Set<string>>(
    new Set(['middle_east', 'north_africa', 'central_asia']));
  const [forceReingest, setForceReingest] = useState(false);
  const [submitting,    setSubmitting]    = useState(false);
  const [submitMsg,     setSubmitMsg]     = useState('');

  useEffect(() => {
    regionsApi.listRegions().then((data: GeoRegion[]) => setRegions(data)).catch(console.error);
  }, []);

  const loadJobs = useCallback(async () => {
    setLoading(true);
    try {
      const data = await ingestionApi.listJobs({ page, page_size: 30 });
      setJobs(data.data || []);
      setTotal(data.total || 0);
    } catch (e) { console.error(e); }
    setLoading(false);
  }, [page]);

  useEffect(() => { loadJobs(); }, [loadJobs]);

  // Auto-refresh while jobs are running
  useEffect(() => {
    if (!jobs.some(j => j.status === 'running' || j.status === 'pending')) return;
    const id = setInterval(loadJobs, 6000);
    return () => clearInterval(id);
  }, [jobs, loadJobs]);

  const toggleRegion = (key: string) =>
    setSelectedRegions(prev => {
      const s = new Set(prev);
      s.has(key) ? s.delete(key) : s.add(key);
      return s;
    });

  const handleStart = async () => {
    if (!beginDate || !endDate) { setSubmitMsg('❌ Enter both dates'); return; }
    if (selectedRegions.size === 0) { setSubmitMsg('❌ Select at least one region'); return; }
    setSubmitting(true); setSubmitMsg('');
    try {
      const result = await ingestionApi.startIngestion({
        begin_date: beginDate, end_date: endDate,
        region_keys: Array.from(selectedRegions),
        force_reingest: forceReingest,
      });
      setSubmitMsg(`✅ Task queued (ID: ${String(result.task_id).slice(0,8)}…)`);
      setTimeout(loadJobs, 2000);
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      setSubmitMsg(`❌ ${err.response?.data?.detail || 'Failed to start'}`);
    }
    setSubmitting(false);
  };

  const handleRetry = async (id: number) => {
    try { await ingestionApi.retryJob(id); loadJobs(); }
    catch (e) { console.error(e); }
  };

  const handleDelete = async (id: number) => {
    if (!confirm('Delete this job record?')) return;
    try { await ingestionApi.deleteJob(id); loadJobs(); }
    catch (e) { console.error(e); }
  };

  const days = beginDate && endDate
    ? Math.max(0, Math.ceil(
        (new Date(endDate).getTime() - new Date(beginDate).getTime()) / 86400000) + 1)
    : 0;
  const totalJobs = days * selectedRegions.size;

  return (
    <div className="space-y-6">
      {/* ── Start form ── */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">📥 Start Historical Ingestion</CardTitle>
          <p className="text-sm text-muted-foreground">
            Fetch flight data from OpenSky Network for a date range and geographic regions.
            Each (date × region) pair is an independent job — completed jobs are skipped automatically.
          </p>
        </CardHeader>
        <CardContent className="space-y-5">
          {/* Date range */}
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label>Start Date</Label>
              <Input type="date" value={beginDate}
                onChange={e => setBeginDate(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label>End Date</Label>
              <Input type="date" value={endDate}
                onChange={e => setEndDate(e.target.value)} />
            </div>
          </div>

          {/* Region selection */}
          <div>
            <Label className="mb-2 block">Regions</Label>
            <div className="flex flex-wrap gap-2">
              {regions.map(r => (
                <button key={r.key} type="button"
                  onClick={() => toggleRegion(r.key)}
                  className={`px-3 py-1.5 rounded-full text-sm font-medium border transition-colors ${
                    selectedRegions.has(r.key)
                      ? 'bg-primary text-primary-foreground border-primary'
                      : 'border-border text-muted-foreground hover:border-primary hover:text-foreground'
                  }`}>
                  {r.name_ar} <span className="opacity-60 text-xs">({r.name})</span>
                </button>
              ))}
            </div>
          </div>

          {/* Summary + options */}
          {totalJobs > 0 && (
            <div className="rounded-lg bg-muted p-3 text-sm">
              📊 Will process <strong>{selectedRegions.size} region{selectedRegions.size !== 1 ? 's' : ''}</strong>
              {' × '}
              <strong>{days} days</strong>
              {' = '}
              <strong>{totalJobs} jobs</strong>
              {' · '}
              Each job is split into 2-hour chunks. API delay: 10s between calls.
            </div>
          )}

          <label className="flex items-center gap-2 text-sm text-muted-foreground cursor-pointer">
            <input type="checkbox" className="rounded"
              checked={forceReingest}
              onChange={e => setForceReingest(e.target.checked)} />
            Force re-ingest (overwrite completed jobs)
          </label>

          <div className="flex items-center gap-3">
            <Button onClick={handleStart} disabled={submitting}>
              {submitting ? '⏳ Queueing…' : '🚀 Start Ingestion'}
            </Button>
            {submitMsg && <span className="text-sm">{submitMsg}</span>}
          </div>
        </CardContent>
      </Card>

      {/* ── Jobs table ── */}
      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0 pb-3">
          <CardTitle className="text-base">📋 Ingestion Jobs ({total})</CardTitle>
          <Button variant="outline" size="sm" onClick={loadJobs} disabled={loading}>
            🔄 Refresh
          </Button>
        </CardHeader>
        <CardContent className="p-0">
          {loading && jobs.length === 0 && (
            <div className="p-8 text-center text-muted-foreground">Loading…</div>
          )}
          {!loading && jobs.length === 0 && (
            <div className="p-8 text-center text-muted-foreground">
              <p className="text-3xl mb-2">📭</p>
              No jobs yet. Start an ingestion above.
            </div>
          )}
          {jobs.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b bg-muted/50">
                  <tr>
                    {['Date','Region','Status','Progress','Flights','Duration','Actions'].map(h => (
                      <th key={h} className="px-4 py-2 text-left text-xs font-medium text-muted-foreground">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {jobs.map(job => {
                    const pct = job.chunks_total > 0
                      ? Math.round((job.chunks_done / job.chunks_total) * 100)
                      : (job.status === 'completed' ? 100 : 0);
                    const duration = job.started_at && job.completed_at
                      ? Math.round((new Date(job.completed_at).getTime()
                          - new Date(job.started_at).getTime()) / 1000)
                      : null;
                    return (
                      <tr key={job.id} className="hover:bg-muted/30 transition-colors">
                        <td className="px-4 py-2.5 font-mono text-xs font-semibold">
                          {job.date_str}
                        </td>
                        <td className="px-4 py-2.5">
                          <Badge variant="outline" className="text-xs">{job.region_key}</Badge>
                        </td>
                        <td className="px-4 py-2.5">
                          <Badge variant={STATUS_BADGE[job.status] || 'secondary'}>
                            {STATUS_ICON[job.status]} {job.status}
                          </Badge>
                        </td>
                        <td className="px-4 py-2.5 w-40">
                          <Progress value={pct} className="h-1.5 mb-1" />
                          <span className="text-xs text-muted-foreground">
                            {job.chunks_done}/{job.chunks_total} chunks ({pct}%)
                          </span>
                        </td>
                        <td className="px-4 py-2.5 text-xs font-semibold text-green-600">
                          {job.flights_ingested > 0
                            ? `+${job.flights_ingested.toLocaleString()}` : '—'}
                        </td>
                        <td className="px-4 py-2.5 text-xs text-muted-foreground">
                          {duration !== null
                            ? `${duration}s`
                            : job.status === 'running' ? '⚡ running…' : '—'}
                        </td>
                        <td className="px-4 py-2.5">
                          <div className="flex gap-1">
                            {job.status === 'failed' && (
                              <Button variant="ghost" size="sm" className="h-7 text-xs"
                                onClick={() => handleRetry(job.id)}>
                                Retry
                              </Button>
                            )}
                            {job.status !== 'running' && (
                              <Button variant="ghost" size="sm"
                                className="h-7 text-xs text-destructive hover:text-destructive"
                                onClick={() => handleDelete(job.id)}>
                                Del
                              </Button>
                            )}
                            {job.error_message && (
                              <span title={job.error_message}
                                className="text-destructive cursor-help">⚠️</span>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {/* Pagination */}
          {total > 30 && (
            <div className="px-4 py-3 border-t flex items-center justify-between">
              <Button variant="outline" size="sm" disabled={page === 1}
                onClick={() => setPage(p => p - 1)}>← Prev</Button>
              <span className="text-xs text-muted-foreground">Page {page}</span>
              <Button variant="outline" size="sm" disabled={jobs.length < 30}
                onClick={() => setPage(p => p + 1)}>Next →</Button>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Info card */}
      <Card className="border-amber-200 bg-amber-50 dark:bg-amber-900/20 dark:border-amber-700">
        <CardContent className="pt-4 text-sm">
          <p className="font-semibold text-amber-800 dark:text-amber-300 mb-2">
            ℹ️ How Ingestion Works
          </p>
          <ul className="space-y-1 text-xs text-amber-700 dark:text-amber-400 list-disc list-inside">
            <li>Each (date × region) creates one job — tracked to prevent duplicate ingestion</li>
            <li>Each job is split into <strong>12 × 2-hour chunks</strong> (OpenSky API limit)</li>
            <li>A <strong>10-second delay</strong> between API calls respects rate limits</li>
            <li>Completed jobs are <strong>skipped automatically</strong> on re-run</li>
            <li>Use <em>Force re-ingest</em> to overwrite already-completed days</li>
            <li>The Celery worker process must be running for tasks to execute</li>
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}
