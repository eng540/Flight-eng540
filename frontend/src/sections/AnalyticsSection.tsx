/**
 * AnalyticsSection.tsx — v4.0 (TIER 4 PART C)
 *
 * FIX: Replaced analyticsApi.getHourlyDistribution → removed (endpoint doesn't exist)
 *      analyticsApi.getDailyTrend → analyticsV1Api.getDailySummary
 *      Evidence: old client.ts called /analytics/hourly_distribution and
 *      /analytics/daily_trend — neither exists in the backend.
 *
 * FIX: All labels translated to Arabic.
 *      Evidence: business requirement "Arabic labels ONLY"
 *
 * NEW: getDailySummary → /api/v1/analytics/daily-summary
 * NEW: getAirlinePerformance → /api/v1/analytics/airline-performance
 * NEW: exportCsvUrl → /api/v1/analytics/export-csv
 *      Evidence: business requirement — all analytics endpoints.
 *
 * FIX: date params were passing Unix timestamps (begin_ts/end_ts).
 *      Backend expects YYYY-MM-DD strings (date_from/date_to).
 *      Evidence: schemas.py HistoryQueryRequest + analytics endpoint params.
 */
import { useState, useEffect, useCallback } from 'react';
import {
  Card, CardContent, CardHeader, CardTitle,
} from '@/components/ui/card';
import { Button }  from '@/components/ui/button';
import { Input }   from '@/components/ui/input';
import { Label }   from '@/components/ui/label';
import {
  Select, SelectContent, SelectItem,
  SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, LineChart, Line, Cell, PieChart, Pie, Legend,
} from 'recharts';
import { analyticsV1Api, regionsApi } from '@/api/client';
import type {
  GeoRegion, RouteStats, AirportStats,
  AirlinePerformanceItem, DailySummary,
} from '@/types';

const COLORS = [
  '#3b82f6','#10b981','#f59e0b','#ef4444','#8b5cf6',
  '#06b6d4','#ec4899','#84cc16','#f97316','#6366f1',
];

export function AnalyticsSection() {
  const [regions,    setRegions]    = useState<GeoRegion[]>([]);
  const [dateFrom,   setDateFrom]   = useState('');
  const [dateTo,     setDateTo]     = useState('');
  const [topAirports, setTopAirports] = useState<AirportStats[]>([]);
  const [topRoutes,   setTopRoutes]   = useState<RouteStats[]>([]);
  const [airlines,    setAirlines]    = useState<AirlinePerformanceItem[]>([]);
  const [dailySummary, setDailySummary] = useState<DailySummary | null>(null);
  const [loading,     setLoading]     = useState(false);
  const [activeChart, setActiveChart] = useState<'airports'|'routes'|'airlines'>('routes');

  useEffect(() => {
    regionsApi.listRegions().then(setRegions).catch(console.error);
  }, []);

  // ── Params builder ────────────────────────────────────────────────────────
  // FIX: passes date_from/date_to strings, not Unix timestamps.
  // Evidence: backend analytics endpoints accept YYYY-MM-DD query params.
  const buildParams = useCallback(() => {
    const p: { date_from?: string; date_to?: string } = {};
    if (dateFrom) p.date_from = dateFrom;
    if (dateTo)   p.date_to   = dateTo;
    return p;
  }, [dateFrom, dateTo]);

  const runAnalysis = useCallback(async () => {
    setLoading(true);
    const p = buildParams();
    try {
      // FIX: Replaced analyticsApi.getHourlyDistribution (non-existent endpoint).
      // FIX: Replaced analyticsApi.getDailyTrend (non-existent endpoint).
      // All calls now map to real backend routes.
      const [airports, routes, airlinesRes, daily] = await Promise.all([
        analyticsV1Api.getBusiestAirports({ limit: 15, ...p }),
        analyticsV1Api.getTopRoutes({ limit: 20, ...p }),
        analyticsV1Api.getAirlinePerformance({ ...p, page_size: 10 }),
        // Daily summary for today (or date_to if specified)
        analyticsV1Api.getDailySummary(dateTo || undefined),
      ]);
      setTopAirports(airports.data  || []);
      setTopRoutes(routes.data      || []);
      setAirlines(airlinesRes.data  || []);
      setDailySummary(daily         || null);
    } catch (e) { console.error('[Analytics]', e); }
    setLoading(false);
  }, [buildParams, dateTo]);

  useEffect(() => { runAnalysis(); }, []);

  const handleExport = (type: 'routes' | 'airports' | 'airlines') => {
    const p: Record<string, string> = {};
    if (dateFrom) p.date_from = dateFrom;
    if (dateTo)   p.date_to   = dateTo;
    window.open(analyticsV1Api.exportCsvUrl(type, p), '_blank');
  };

  return (
    <div className="space-y-6">

      {/* ── Filter bar ──────────────────────────────────────────────────── */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">📊 فلاتر التحليلات</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div className="space-y-2">
              <Label className="text-xs">من تاريخ</Label>
              <Input type="date" value={dateFrom}
                onChange={e => setDateFrom(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label className="text-xs">إلى تاريخ</Label>
              <Input type="date" value={dateTo}
                onChange={e => setDateTo(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label className="text-xs">تصدير CSV</Label>
              <div className="flex gap-1.5">
                <Button size="sm" variant="outline" className="flex-1 text-xs"
                  onClick={() => handleExport('routes')}>الطرق</Button>
                <Button size="sm" variant="outline" className="flex-1 text-xs"
                  onClick={() => handleExport('airports')}>المطارات</Button>
                <Button size="sm" variant="outline" className="flex-1 text-xs"
                  onClick={() => handleExport('airlines')}>الناقلون</Button>
              </div>
            </div>
            <div className="flex items-end">
              <Button onClick={runAnalysis} disabled={loading} className="w-full">
                {loading ? '⏳ جاري التحليل…' : '📈 تحليل'}
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* ── Today's summary counters ─────────────────────────────────────── */}
      {dailySummary && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          {[
            { label: 'إجمالي الرحلات',  value: dailySummary.total_flights,    icon: '✈️' },
            { label: 'رحلات نشطة',      value: dailySummary.active_flights,   icon: '🟢' },
            { label: 'هبطت',            value: dailySummary.landed_flights,   icon: '🛬' },
            { label: 'حوادث طوارئ',    value: dailySummary.emergency_events,  icon: '⚠️' },
            { label: 'طائرات فريدة',   value: dailySummary.unique_aircraft,  icon: '🛩️' },
            { label: 'ناقلون فريدون',  value: dailySummary.unique_operators, icon: '🏢' },
          ].map(c => (
            <Card key={c.label}>
              <CardContent className="pt-4 pb-3">
                <div className="text-2xl mb-1">{c.icon}</div>
                <div className="text-xl font-bold">
                  {(c.value || 0).toLocaleString('ar')}
                </div>
                <div className="text-xs text-muted-foreground">{c.label}</div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* ── Chart tabs ──────────────────────────────────────────────────── */}
      <div className="flex gap-2 border-b pb-1">
        {([
          ['routes',   '🛤️ أبرز الطرق'],
          ['airports', '🛫 أبرز المطارات'],
          ['airlines', '🏢 أداء الناقلين'],
        ] as const).map(([key, label]) => (
          <button key={key} onClick={() => setActiveChart(key)}
            className={`px-4 py-1.5 text-sm rounded-t transition-colors ${
              activeChart === key
                ? 'bg-primary text-primary-foreground font-medium'
                : 'text-muted-foreground hover:text-foreground'
            }`}>
            {label}
          </button>
        ))}
      </div>

      {/* ── Top Routes chart ─────────────────────────────────────────────── */}
      {activeChart === 'routes' && (
        <div className="grid gap-6 lg:grid-cols-2">
          <Card className="lg:col-span-2">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-semibold">🛤️ أكثر الطرق ازدحاماً</CardTitle>
            </CardHeader>
            <CardContent>
              {topRoutes.length === 0 ? (
                <EmptyState />
              ) : (
                <ResponsiveContainer width="100%" height={320}>
                  <BarChart
                    data={topRoutes.slice(0, 15).map(r => ({
                      route: `${r.departure || '??'} ← ${r.arrival || '??'}`,
                      رحلات: r.flight_count,
                    }))}
                    layout="vertical"
                    margin={{ right: 20 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis type="number" tick={{ fontSize: 10, fontFamily: 'Tajawal' }} />
                    <YAxis type="category" dataKey="route"
                      tick={{ fontSize: 10, fontFamily: 'Tajawal' }} width={120} />
                    <Tooltip
                      formatter={(v: number) => [v.toLocaleString('ar'), 'رحلات']}
                      contentStyle={{ fontFamily: 'Tajawal', direction: 'rtl' }}
                    />
                    <Bar dataKey="رحلات" radius={[0, 4, 4, 0]}>
                      {topRoutes.slice(0, 15).map((_, i) => (
                        <Cell key={i} fill={COLORS[i % COLORS.length]} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              )}
            </CardContent>
          </Card>

          {/* Routes table */}
          <Card className="lg:col-span-2">
            <CardContent className="pt-4">
              <div className="rounded border overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-muted">
                    <tr>
                      <th className="p-2 text-right w-8">#</th>
                      <th className="p-2 text-right">المغادرة</th>
                      <th className="p-2 text-center"></th>
                      <th className="p-2 text-right">الوصول</th>
                      <th className="p-2 text-left">عدد الرحلات</th>
                    </tr>
                  </thead>
                  <tbody>
                    {topRoutes.slice(0, 20).map((r, i) => (
                      <tr key={i} className="border-t hover:bg-muted/40">
                        <td className="p-2 text-muted-foreground text-center">{i + 1}</td>
                        <td className="p-2 font-mono font-bold text-primary">{r.departure || '??'}</td>
                        <td className="p-2 text-center text-muted-foreground">←</td>
                        <td className="p-2 font-mono font-bold text-primary">{r.arrival || '??'}</td>
                        <td className="p-2 font-semibold">{r.flight_count.toLocaleString('ar')}</td>
                      </tr>
                    ))}
                    {topRoutes.length === 0 && (
                      <tr><td colSpan={5} className="p-4 text-center text-muted-foreground">لا توجد بيانات</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* ── Busiest Airports chart ───────────────────────────────────────── */}
      {activeChart === 'airports' && (
        <div className="grid gap-6 lg:grid-cols-2">
          {/* Bar chart — total movements */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-semibold">🛫 أكثر المطارات ازدحاماً (إجمالي الحركة)</CardTitle>
            </CardHeader>
            <CardContent>
              {topAirports.length === 0 ? <EmptyState /> : (
                <ResponsiveContainer width="100%" height={300}>
                  <BarChart
                    data={topAirports.slice(0, 12).map(a => ({
                      icao: a.airport_icao,
                      مغادرة: a.as_departure,
                      وصول:   a.as_arrival,
                    }))}
                  >
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="icao" tick={{ fontSize: 10, fontFamily: 'Tajawal' }} />
                    <YAxis tick={{ fontSize: 10 }} />
                    <Tooltip
                      contentStyle={{ fontFamily: 'Tajawal', direction: 'rtl' }}
                      formatter={(v: number, name: string) => [v.toLocaleString('ar'), name]}
                    />
                    <Legend wrapperStyle={{ fontFamily: 'Tajawal' }} />
                    <Bar dataKey="مغادرة" stackId="a" fill="#3b82f6" />
                    <Bar dataKey="وصول"   stackId="a" fill="#10b981" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </CardContent>
          </Card>

          {/* Pie chart */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-semibold">🥧 توزيع حركة المطارات</CardTitle>
            </CardHeader>
            <CardContent>
              {topAirports.length === 0 ? <EmptyState /> : (
                <ResponsiveContainer width="100%" height={300}>
                  <PieChart>
                    <Pie
                      data={topAirports.slice(0, 8).map(a => ({
                        name:  a.airport_icao,
                        value: a.flight_count,
                      }))}
                      dataKey="value"
                      nameKey="name"
                      cx="50%" cy="50%" outerRadius={90}
                      label={({ name, percent }) =>
                        `${name} ${(percent * 100).toFixed(0)}%`}
                      labelLine={false}
                    >
                      {topAirports.slice(0, 8).map((_, i) => (
                        <Cell key={i} fill={COLORS[i % COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip
                      formatter={(v: number) => [v.toLocaleString('ar'), 'رحلات']}
                      contentStyle={{ fontFamily: 'Tajawal' }}
                    />
                  </PieChart>
                </ResponsiveContainer>
              )}
            </CardContent>
          </Card>

          {/* Airport ranking list */}
          <Card className="lg:col-span-2">
            <CardContent className="pt-4">
              <div className="space-y-2 max-h-72 overflow-y-auto">
                {topAirports.slice(0, 15).map((a, i) => {
                  const pct = topAirports[0]?.flight_count
                    ? (a.flight_count / topAirports[0].flight_count) * 100 : 0;
                  return (
                    <div key={a.airport_icao} className="flex items-center gap-3">
                      <span className="text-xs text-muted-foreground w-5 text-center">{i + 1}</span>
                      <span className="font-mono text-sm font-bold text-primary w-14">{a.airport_icao}</span>
                      <div className="flex-1 bg-muted rounded-full h-2">
                        <div className="h-2 rounded-full transition-all"
                          style={{ width: `${pct}%`, backgroundColor: COLORS[i % COLORS.length] }} />
                      </div>
                      <div className="text-xs text-muted-foreground w-32 text-left">
                        ↑{a.as_departure.toLocaleString('ar')} ↓{a.as_arrival.toLocaleString('ar')}
                      </div>
                      <span className="text-xs font-semibold w-16 text-left">
                        {a.flight_count.toLocaleString('ar')}
                      </span>
                    </div>
                  );
                })}
                {topAirports.length === 0 && <EmptyState />}
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* ── Airline Performance ──────────────────────────────────────────── */}
      {activeChart === 'airlines' && (
        <div className="grid gap-6 lg:grid-cols-2">
          {/* Bar chart — total flights */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-semibold">✈️ أداء الناقلين — عدد الرحلات</CardTitle>
            </CardHeader>
            <CardContent>
              {airlines.length === 0 ? <EmptyState /> : (
                <ResponsiveContainer width="100%" height={300}>
                  <BarChart
                    data={airlines.map(a => ({
                      ناقل:      a.operator_icao,
                      'رحلات نشطة':  a.active_flights,
                      'رحلات كاملة': a.total_flights - a.active_flights,
                    }))}
                    layout="vertical"
                    margin={{ right: 20 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis type="number" tick={{ fontSize: 10 }} />
                    <YAxis type="category" dataKey="ناقل"
                      tick={{ fontSize: 10, fontFamily: 'Tajawal' }} width={60} />
                    <Tooltip
                      contentStyle={{ fontFamily: 'Tajawal', direction: 'rtl' }}
                      formatter={(v: number, n: string) => [v.toLocaleString('ar'), n]}
                    />
                    <Legend wrapperStyle={{ fontFamily: 'Tajawal' }} />
                    <Bar dataKey="رحلات نشطة"  stackId="a" fill="#10b981" />
                    <Bar dataKey="رحلات كاملة" stackId="a" fill="#3b82f6" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </CardContent>
          </Card>

          {/* Line chart — avg duration */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-semibold">⏱️ متوسط مدة الرحلة (دقيقة)</CardTitle>
            </CardHeader>
            <CardContent>
              {airlines.length === 0 ? <EmptyState /> : (
                <ResponsiveContainer width="100%" height={300}>
                  <BarChart
                    data={airlines
                      .filter(a => a.avg_flight_duration_min != null)
                      .map(a => ({
                        ناقل: a.operator_icao,
                        دقائق: Math.round(a.avg_flight_duration_min || 0),
                      }))}
                    layout="vertical"
                    margin={{ right: 20 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis type="number" tick={{ fontSize: 10 }} />
                    <YAxis type="category" dataKey="ناقل"
                      tick={{ fontSize: 10, fontFamily: 'Tajawal' }} width={60} />
                    <Tooltip
                      contentStyle={{ fontFamily: 'Tajawal', direction: 'rtl' }}
                      formatter={(v: number) => [`${v.toLocaleString('ar')} دقيقة`, 'متوسط المدة']}
                    />
                    <Bar dataKey="دقائق" fill="#f59e0b" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </CardContent>
          </Card>

          {/* Airline table */}
          <Card className="lg:col-span-2">
            <CardContent className="pt-4">
              <div className="rounded border overflow-auto">
                <table className="w-full text-sm">
                  <thead className="bg-muted">
                    <tr>
                      <th className="p-2 text-right">#</th>
                      <th className="p-2 text-right">الناقل</th>
                      <th className="p-2 text-right">الاسم</th>
                      <th className="p-2 text-left">إجمالي الرحلات</th>
                      <th className="p-2 text-left">نشطة</th>
                      <th className="p-2 text-left">متوسط المدة</th>
                      <th className="p-2 text-left">المسافة الكلية</th>
                    </tr>
                  </thead>
                  <tbody>
                    {airlines.map((a, i) => (
                      <tr key={a.operator_icao} className="border-t hover:bg-muted/40">
                        <td className="p-2 text-center text-muted-foreground">{i + 1}</td>
                        <td className="p-2 font-mono font-bold text-primary">{a.operator_icao}</td>
                        <td className="p-2 text-muted-foreground">{a.operator_name || '—'}</td>
                        <td className="p-2 font-semibold">{a.total_flights.toLocaleString('ar')}</td>
                        <td className="p-2 text-green-600">{a.active_flights.toLocaleString('ar')}</td>
                        <td className="p-2">
                          {a.avg_flight_duration_min != null
                            ? `${Math.round(a.avg_flight_duration_min).toLocaleString('ar')} د` : '—'}
                        </td>
                        <td className="p-2">
                          {a.total_distance_km != null
                            ? `${Math.round(a.total_distance_km).toLocaleString('ar')} كم` : '—'}
                        </td>
                      </tr>
                    ))}
                    {airlines.length === 0 && (
                      <tr><td colSpan={7} className="p-4 text-center text-muted-foreground">لا توجد بيانات</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-muted-foreground gap-2">
      <span className="text-4xl">📊</span>
      <p className="text-sm">لا توجد بيانات للعرض</p>
      <p className="text-xs">اضغط "تحليل" لتحميل البيانات</p>
    </div>
  );
}
