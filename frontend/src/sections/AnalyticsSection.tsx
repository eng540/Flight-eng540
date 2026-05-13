/**
 * AnalyticsSection.tsx — v6.0 (Data Liberation & Deep Filtering)
 *
 * CHANGES:
 * - Removed hardcoded `.slice()` from tables. Data is now fully accessible.
 * - Added Pagination controls (Next/Prev) for all data tables.
 * - Added Deep Filters (Operator, Airport, Region) alongside Date filters.
 * - Fixed Timezone issue in Time Distribution chart (UTC -> Local Time).
 */
import { useState, useEffect, useCallback } from 'react';
import {
  Card, CardContent, CardHeader, CardTitle, CardDescription
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
  CartesianGrid, Cell, PieChart, Pie, Legend, AreaChart, Area
} from 'recharts';
import { analyticsV1Api, regionsApi } from '@/api/client';
import type {
  RouteStats, AirportStats,
  AirlinePerformanceItem, DailySummary, GeoRegion
} from '@/types';

const COLORS = [
  '#3b82f6','#10b981','#f59e0b','#ef4444','#8b5cf6',
  '#06b6d4','#ec4899','#84cc16','#f97316','#6366f1',
];

export function AnalyticsSection() {
  // Filters State
  const [dateFrom,   setDateFrom]   = useState('');
  const [dateTo,     setDateTo]     = useState('');
  const [operatorIcao, setOperatorIcao] = useState('');
  const [airportIcao,  setAirportIcao]  = useState('');
  const [regionKey,    setRegionKey]    = useState('all');
  const [regions,      setRegions]      = useState<GeoRegion[]>([]);
  
  // Data State
  const [topAirports, setTopAirports] = useState<AirportStats[]>([]);
  const [topRoutes,   setTopRoutes]   = useState<RouteStats[]>([]);
  const [airlines,    setAirlines]    = useState<AirlinePerformanceItem[]>([]);
  const [dailySummary, setDailySummary] = useState<DailySummary | null>(null);
  const [timeDist,    setTimeDist]    = useState<{hour: number, flight_count: number, localHourLabel: string}[]>([]);
  
  // Pagination State
  const [routesPage, setRoutesPage] = useState(1);
  const [routesPages, setRoutesPages] = useState(1);
  const [airportsPage, setAirportsPage] = useState(1);
  const [airportsPages, setAirportsPages] = useState(1);
  const [airlinesPage, setAirlinesPage] = useState(1);
  const [airlinesPages, setAirlinesPages] = useState(1);

  const [loading,     setLoading]     = useState(false);
  const [activeChart, setActiveChart] = useState<'time'|'routes'|'airports'|'airlines'>('time');

  // Load Regions on mount
  useEffect(() => {
    regionsApi.listRegions().then(setRegions).catch(console.error);
  }, []);

  // ── Params builder ────────────────────────────────────────────────────────
  const buildParams = useCallback((page = 1, limit = 10) => {
    const p: Record<string, any> = { page, limit };
    if (dateFrom) p.date_from = dateFrom;
    if (dateTo)   p.date_to   = dateTo;
    if (operatorIcao) p.operator_icao = operatorIcao.trim().toUpperCase();
    if (airportIcao) {
      // If user enters an airport, we apply it to both dep and arr to get all traffic
      p.dep_icao = airportIcao.trim().toUpperCase();
      p.arr_icao = airportIcao.trim().toUpperCase();
    }
    if (regionKey && regionKey !== 'all') p.region_key = regionKey;
    return p;
  }, [dateFrom, dateTo, operatorIcao, airportIcao, regionKey]);

  // ── Main Analysis Runner ──────────────────────────────────────────────────
  const runAnalysis = useCallback(async () => {
    setLoading(true);
    try {
      // Reset pages on new filter application
      setRoutesPage(1); setAirportsPage(1); setAirlinesPage(1);

      const pRoutes = buildParams(1, 15);
      const pAirports = buildParams(1, 15);
      const pAirlines = buildParams(1, 15);
      const pGlobal = buildParams(1, 1); // Page/limit ignored by summary/time endpoints

      const [airportsRes, routesRes, airlinesRes, dailyRes, timeRes] = await Promise.all([
        analyticsV1Api.getBusiestAirports(pAirports),
        analyticsV1Api.getTopRoutes(pRoutes),
        analyticsV1Api.getAirlinePerformance(pAirlines),
        import('@/api/client').then(m => m.default.get('/api/v1/analytics/daily-summary', { params: pGlobal }).then(r => r.data)),
        import('@/api/client').then(m => m.default.get('/api/v1/analytics/time-distribution', { params: pGlobal }).then(r => r.data))
      ]);
      
      setTopAirports(airportsRes.data || []);
      setAirportsPages(airportsRes.pages || 1);

      setTopRoutes(routesRes.data || []);
      setRoutesPages(routesRes.pages || 1);

      setAirlines(airlinesRes.data || []);
      setAirlinesPages(airlinesRes.pages || 1);

      setDailySummary(dailyRes || null);

      // Timezone Correction: Convert UTC hour to Local Browser Hour
      const localOffset = -(new Date().getTimezoneOffset() / 60);
      const correctedTimeDist = (timeRes.data || []).map((d: any) => {
        let localHour = (d.hour + localOffset) % 24;
        if (localHour < 0) localHour += 24;
        return {
          ...d,
          localHourLabel: `${Math.floor(localHour).toString().padStart(2, '0')}:00`
        };
      });
      // Sort by local hour to keep the chart chronological
      correctedTimeDist.sort((a: any, b: any) => parseInt(a.localHourLabel) - parseInt(b.localHourLabel));
      setTimeDist(correctedTimeDist);

    } catch (e) { console.error('[Analytics]', e); }
    setLoading(false);
  }, [buildParams]);

  // Run once on mount
  useEffect(() => { runAnalysis(); }, []);

  // ── Pagination Handlers ───────────────────────────────────────────────────
  const loadRoutesPage = async (newPage: number) => {
    setLoading(true);
    try {
      const res = await analyticsV1Api.getTopRoutes(buildParams(newPage, 15));
      setTopRoutes(res.data || []);
      setRoutesPage(newPage);
    } catch (e) { console.error(e); }
    setLoading(false);
  };

  const loadAirportsPage = async (newPage: number) => {
    setLoading(true);
    try {
      const res = await analyticsV1Api.getBusiestAirports(buildParams(newPage, 15));
      setTopAirports(res.data || []);
      setAirportsPage(newPage);
    } catch (e) { console.error(e); }
    setLoading(false);
  };

  const loadAirlinesPage = async (newPage: number) => {
    setLoading(true);
    try {
      const res = await analyticsV1Api.getAirlinePerformance(buildParams(newPage, 15));
      setAirlines(res.data || []);
      setAirlinesPage(newPage);
    } catch (e) { console.error(e); }
    setLoading(false);
  };

  // ── Export Handler ────────────────────────────────────────────────────────
  const handleExport = (type: 'routes' | 'airports' | 'airlines') => {
    const p = buildParams(1, 50000); // Request up to 50k rows for export
    window.open(analyticsV1Api.exportCsvUrl(type, p), '_blank');
  };

  return (
    <div className="space-y-8">

      {/* ── Deep Filter Bar ──────────────────────────────────────────────── */}
      <Card className="border-primary/10 shadow-sm">
        <CardHeader className="pb-2">
          <CardTitle className="text-base flex items-center gap-2">
            <span>🔍</span> فلاتر التحليلات العميقة
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5 items-end">
            <div className="space-y-2">
              <Label className="text-xs font-semibold text-muted-foreground">من تاريخ</Label>
              <Input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} className="bg-muted/50" />
            </div>
            <div className="space-y-2">
              <Label className="text-xs font-semibold text-muted-foreground">إلى تاريخ</Label>
              <Input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} className="bg-muted/50" />
            </div>
            <div className="space-y-2">
              <Label className="text-xs font-semibold text-muted-foreground">كود الشركة (ICAO)</Label>
              <Input placeholder="مثال: SVA" value={operatorIcao} onChange={e => setOperatorIcao(e.target.value)} className="bg-muted/50" />
            </div>
            <div className="space-y-2">
              <Label className="text-xs font-semibold text-muted-foreground">كود المطار (ICAO)</Label>
              <Input placeholder="مثال: OERK" value={airportIcao} onChange={e => setAirportIcao(e.target.value)} className="bg-muted/50" />
            </div>
            <div className="space-y-2">
              <Label className="text-xs font-semibold text-muted-foreground">المنطقة</Label>
              <Select value={regionKey} onValueChange={setRegionKey}>
                <SelectTrigger className="bg-muted/50"><SelectValue placeholder="جميع المناطق" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">جميع المناطق</SelectItem>
                  {regions.map(r => <SelectItem key={r.key} value={r.key}>{r.name_ar}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          </div>
          
          <div className="flex flex-col sm:flex-row justify-between items-center mt-6 pt-4 border-t gap-4">
            <div className="flex gap-2 w-full sm:w-auto">
              <span className="text-xs font-semibold text-muted-foreground self-center ml-2">تصدير (CSV):</span>
              <Button size="sm" variant="outline" className="text-xs" onClick={() => handleExport('routes')}>الطرق</Button>
              <Button size="sm" variant="outline" className="text-xs" onClick={() => handleExport('airports')}>المطارات</Button>
              <Button size="sm" variant="outline" className="text-xs" onClick={() => handleExport('airlines')}>الناقلون</Button>
            </div>
            <Button onClick={runAnalysis} disabled={loading} className="w-full sm:w-40 shadow-md">
              {loading ? '⏳ جاري...' : '📈 تطبيق الفلاتر'}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* ── Summary counters ─────────────────────────────────────── */}
      {dailySummary && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
          {[
            { label: 'إجمالي الرحلات',  value: dailySummary.total_flights,    icon: '✈️', color: 'text-blue-600', bg: 'bg-blue-100 dark:bg-blue-900/20' },
            { label: 'رحلات نشطة',      value: dailySummary.active_flights,   icon: '🟢', color: 'text-green-600', bg: 'bg-green-100 dark:bg-green-900/20' },
            { label: 'هبطت / اكتملت',   value: dailySummary.landed_flights,   icon: '🛬', color: 'text-slate-600', bg: 'bg-slate-100 dark:bg-slate-800' },
            { label: 'حوادث طوارئ',    value: dailySummary.emergency_events,  icon: '⚠️', color: 'text-red-600', bg: 'bg-red-100 dark:bg-red-900/20' },
            { label: 'طائرات فريدة',   value: dailySummary.unique_aircraft,  icon: '🛩️', color: 'text-purple-600', bg: 'bg-purple-100 dark:bg-purple-900/20' },
            { label: 'ناقلون فريدون',  value: dailySummary.unique_operators, icon: '🏢', color: 'text-amber-600', bg: 'bg-amber-100 dark:bg-amber-900/20' },
          ].map(c => (
            <Card key={c.label} className="border-none shadow-sm bg-card hover:shadow-md transition-shadow">
              <CardContent className="p-4 flex flex-col items-center text-center">
                <div className={`p-3 rounded-full ${c.bg} mb-3`}>
                  <span className="text-xl">{c.icon}</span>
                </div>
                <div className={`text-2xl font-bold ${c.color}`}>
                  {(c.value || 0).toLocaleString('ar')}
                </div>
                <div className="text-xs text-muted-foreground mt-1 font-medium">{c.label}</div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* ── Chart tabs ──────────────────────────────────────────────────── */}
      <div className="flex gap-1 border-b pb-0 overflow-x-auto hide-scrollbar">
        {([
          ['time',     '🕒 أوقات الذروة'],
          ['routes',   '🛤️ أبرز الطرق'],
          ['airports', '🛫 حركة المطارات'],
          ['airlines', '🏢 أداء الناقلين'],
        ] as const).map(([key, label]) => (
          <button key={key} onClick={() => setActiveChart(key)}
            className={`px-5 py-2.5 text-sm rounded-t-lg transition-all whitespace-nowrap ${
              activeChart === key
                ? 'bg-primary text-primary-foreground font-bold shadow-sm'
                : 'text-muted-foreground hover:bg-muted/50 hover:text-foreground font-medium'
            }`}>
            {label}
          </button>
        ))}
      </div>

      {/* ── Time Distribution Chart ────────────────────────────────── */}
      {activeChart === 'time' && (
        <Card className="border-none shadow-sm">
          <CardHeader>
            <CardTitle className="text-lg">🕒 التوزيع الزمني للرحلات (أوقات الذروة)</CardTitle>
            <CardDescription>عدد الرحلات المكتشفة موزعة حسب ساعات اليوم (بالتوقيت المحلي لجهازك)</CardDescription>
          </CardHeader>
          <CardContent>
            {timeDist.length === 0 ? <EmptyState /> : (
              <ResponsiveContainer width="100%" height={350}>
                <AreaChart data={timeDist} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="colorFlights" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.8}/>
                      <stop offset="95%" stopColor="#3b82f6" stopOpacity={0}/>
                    </linearGradient>
                  </defs>
                  <XAxis 
                    dataKey="localHourLabel" 
                    tick={{ fontSize: 12, fontFamily: 'Tajawal' }} 
                  />
                  <YAxis tick={{ fontSize: 12, fontFamily: 'Tajawal' }} />
                  <CartesianGrid strokeDasharray="3 3" vertical={false} strokeOpacity={0.3} />
                  <Tooltip 
                    labelFormatter={(h) => `الساعة ${h}`}
                    formatter={(v: number) => [v.toLocaleString('ar'), 'رحلة']}
                    contentStyle={{ fontFamily: 'Tajawal', borderRadius: '8px', border: 'none', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }}
                  />
                  <Area type="monotone" dataKey="flight_count" stroke="#3b82f6" strokeWidth={3} fillOpacity={1} fill="url(#colorFlights)" />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>
      )}

      {/* ── Top Routes chart ─────────────────────────────────────────────── */}
      {activeChart === 'routes' && (
        <div className="grid gap-6 lg:grid-cols-2">
          <Card className="lg:col-span-2 border-none shadow-sm">
            <CardHeader>
              <CardTitle className="text-lg">🛤️ أكثر الطرق الجوية ازدحاماً</CardTitle>
            </CardHeader>
            <CardContent>
              {topRoutes.length === 0 ? <EmptyState /> : (
                <ResponsiveContainer width="100%" height={350}>
                  <BarChart
                    data={topRoutes.slice(0, 15).map(r => ({
                      route: `${r.departure || '??'} ← ${r.arrival || '??'}`,
                      رحلات: r.flight_count,
                    }))}
                    layout="vertical"
                    margin={{ right: 30 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" horizontal={false} strokeOpacity={0.3} />
                    <XAxis type="number" tick={{ fontSize: 12, fontFamily: 'Tajawal' }} />
                    <YAxis type="category" dataKey="route" tick={{ fontSize: 11, fontFamily: 'monospace', fontWeight: 'bold' }} width={120} />
                    <Tooltip
                      formatter={(v: number) => [v.toLocaleString('ar'), 'رحلات']}
                      contentStyle={{ fontFamily: 'Tajawal', direction: 'rtl', borderRadius: '8px' }}
                      cursor={{ fill: 'transparent' }}
                    />
                    <Bar dataKey="رحلات" radius={[0, 6, 6, 0]} barSize={20}>
                      {topRoutes.slice(0, 15).map((_, i) => (
                        <Cell key={i} fill={COLORS[i % COLORS.length]} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              )}
            </CardContent>
          </Card>

          {/* Routes table with Pagination */}
          <Card className="lg:col-span-2 border-none shadow-sm">
            <CardContent className="pt-6">
              <div className="rounded-lg border overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-muted/50">
                    <tr>
                      <th className="p-3 text-right w-12 font-medium">#</th>
                      <th className="p-3 text-right font-medium">مطار المغادرة</th>
                      <th className="p-3 text-center font-medium">المسار</th>
                      <th className="p-3 text-right font-medium">مطار الوصول</th>
                      <th className="p-3 text-left font-medium">إجمالي الرحلات</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {topRoutes.map((r, i) => (
                      <tr key={i} className="hover:bg-muted/30 transition-colors">
                        <td className="p-3 text-muted-foreground text-center">{(routesPage - 1) * 15 + i + 1}</td>
                        <td className="p-3 font-mono font-bold text-primary text-lg">{r.departure || '??'}</td>
                        <td className="p-3 text-center text-muted-foreground">✈️</td>
                        <td className="p-3 font-mono font-bold text-primary text-lg">{r.arrival || '??'}</td>
                        <td className="p-3 font-bold text-left text-lg">{r.flight_count.toLocaleString('ar')}</td>
                      </tr>
                    ))}
                    {topRoutes.length === 0 && (
                      <tr><td colSpan={5} className="p-8 text-center text-muted-foreground">لا توجد بيانات مطابقة للفلتر</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
              {/* Pagination Controls */}
              {routesPages > 1 && (
                <div className="flex items-center justify-between mt-4">
                  <Button variant="outline" size="sm" disabled={routesPage <= 1 || loading} onClick={() => loadRoutesPage(routesPage - 1)}>السابق</Button>
                  <span className="text-sm text-muted-foreground">صفحة {routesPage} من {routesPages}</span>
                  <Button variant="outline" size="sm" disabled={routesPage >= routesPages || loading} onClick={() => loadRoutesPage(routesPage + 1)}>التالي</Button>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}

      {/* ── Busiest Airports chart ───────────────────────────────────────── */}
      {activeChart === 'airports' && (
        <div className="grid gap-6 lg:grid-cols-2">
          <Card className="border-none shadow-sm">
            <CardHeader>
              <CardTitle className="text-lg">🛫 إجمالي الحركة في المطارات</CardTitle>
            </CardHeader>
            <CardContent>
              {topAirports.length === 0 ? <EmptyState /> : (
                <ResponsiveContainer width="100%" height={320}>
                  <BarChart
                    data={topAirports.slice(0, 12).map(a => ({
                      icao: a.airport_icao,
                      مغادرة: a.as_departure,
                      وصول:   a.as_arrival,
                    }))}
                    margin={{ top: 20 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" vertical={false} strokeOpacity={0.3} />
                    <XAxis dataKey="icao" tick={{ fontSize: 11, fontFamily: 'monospace', fontWeight: 'bold' }} />
                    <YAxis tick={{ fontSize: 12, fontFamily: 'Tajawal' }} />
                    <Tooltip
                      contentStyle={{ fontFamily: 'Tajawal', direction: 'rtl', borderRadius: '8px' }}
                      formatter={(v: number, name: string) => [v.toLocaleString('ar'), name]}
                      cursor={{ fill: 'var(--muted)' }}
                    />
                    <Legend wrapperStyle={{ fontFamily: 'Tajawal', paddingTop: '10px' }} />
                    <Bar dataKey="مغادرة" stackId="a" fill="#3b82f6" radius={[0, 0, 4, 4]} maxBarSize={40} />
                    <Bar dataKey="وصول"   stackId="a" fill="#10b981" radius={[4, 4, 0, 0]} maxBarSize={40} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </CardContent>
          </Card>

          <Card className="border-none shadow-sm">
            <CardHeader>
              <CardTitle className="text-lg">🥧 الحصة السوقية للمطارات</CardTitle>
            </CardHeader>
            <CardContent>
              {topAirports.length === 0 ? <EmptyState /> : (
                <ResponsiveContainer width="100%" height={320}>
                  <PieChart>
                    <Pie
                      data={topAirports.slice(0, 8).map(a => ({
                        name:  a.airport_icao,
                        value: a.flight_count,
                      }))}
                      dataKey="value"
                      nameKey="name"
                      cx="50%" cy="50%" 
                      innerRadius={60}
                      outerRadius={100}
                      paddingAngle={2}
                      label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                      labelLine={true}
                    >
                      {topAirports.slice(0, 8).map((_, i) => (
                        <Cell key={i} fill={COLORS[i % COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip
                      formatter={(v: number) => [v.toLocaleString('ar'), 'رحلة']}
                      contentStyle={{ fontFamily: 'Tajawal', borderRadius: '8px' }}
                    />
                  </PieChart>
                </ResponsiveContainer>
              )}
            </CardContent>
          </Card>

          {/* Airport ranking list with Pagination */}
          <Card className="lg:col-span-2 border-none shadow-sm">
            <CardContent className="pt-6">
              <div className="space-y-4">
                {topAirports.map((a, i) => {
                  const pct = topAirports[0]?.flight_count
                    ? (a.flight_count / topAirports[0].flight_count) * 100 : 0;
                  return (
                    <div key={a.airport_icao} className="flex items-center gap-4 p-2 hover:bg-muted/50 rounded-lg transition-colors">
                      <div className="flex items-center justify-center w-8 h-8 rounded-full bg-muted text-muted-foreground font-bold text-sm">
                        {(airportsPage - 1) * 15 + i + 1}
                      </div>
                      <span className="font-mono text-lg font-bold text-primary w-16">{a.airport_icao}</span>
                      <div className="flex-1">
                        <div className="flex justify-between text-xs mb-1 text-muted-foreground">
                          <span>إجمالي: {a.flight_count.toLocaleString('ar')}</span>
                          <span>مغادرة: {a.as_departure.toLocaleString('ar')} | وصول: {a.as_arrival.toLocaleString('ar')}</span>
                        </div>
                        <div className="w-full bg-muted rounded-full h-2.5 overflow-hidden">
                          <div className="h-full rounded-full transition-all duration-1000"
                            style={{ width: `${pct}%`, backgroundColor: COLORS[i % COLORS.length] }} />
                        </div>
                      </div>
                    </div>
                  );
                })}
                {topAirports.length === 0 && <EmptyState />}
              </div>
              {/* Pagination Controls */}
              {airportsPages > 1 && (
                <div className="flex items-center justify-between mt-6 pt-4 border-t">
                  <Button variant="outline" size="sm" disabled={airportsPage <= 1 || loading} onClick={() => loadAirportsPage(airportsPage - 1)}>السابق</Button>
                  <span className="text-sm text-muted-foreground">صفحة {airportsPage} من {airportsPages}</span>
                  <Button variant="outline" size="sm" disabled={airportsPage >= airportsPages || loading} onClick={() => loadAirportsPage(airportsPage + 1)}>التالي</Button>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}

      {/* ── Airline Performance ──────────────────────────────────────────── */}
      {activeChart === 'airlines' && (
        <div className="grid gap-6 lg:grid-cols-2">
          <Card className="border-none shadow-sm">
            <CardHeader>
              <CardTitle className="text-lg">✈️ حجم عمليات الناقلين</CardTitle>
            </CardHeader>
            <CardContent>
              {airlines.length === 0 ? <EmptyState /> : (
                <ResponsiveContainer width="100%" height={320}>
                  <BarChart
                    data={airlines.slice(0, 15).map(a => ({
                      ناقل:      a.operator_icao,
                      'رحلات نشطة':  a.active_flights,
                      'رحلات كاملة': a.total_flights - a.active_flights,
                    }))}
                    layout="vertical"
                    margin={{ right: 30 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" horizontal={false} strokeOpacity={0.3} />
                    <XAxis type="number" tick={{ fontSize: 12 }} />
                    <YAxis type="category" dataKey="ناقل" tick={{ fontSize: 11, fontFamily: 'monospace', fontWeight: 'bold' }} width={60} />
                    <Tooltip
                      contentStyle={{ fontFamily: 'Tajawal', direction: 'rtl', borderRadius: '8px' }}
                      formatter={(v: number, n: string) => [v.toLocaleString('ar'), n]}
                      cursor={{ fill: 'var(--muted)' }}
                    />
                    <Legend wrapperStyle={{ fontFamily: 'Tajawal', paddingTop: '10px' }} />
                    <Bar dataKey="رحلات نشطة"  stackId="a" fill="#10b981" maxBarSize={25} />
                    <Bar dataKey="رحلات كاملة" stackId="a" fill="#3b82f6" radius={[0, 4, 4, 0]} maxBarSize={25} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </CardContent>
          </Card>

          <Card className="border-none shadow-sm">
            <CardHeader>
              <CardTitle className="text-lg">⏱️ متوسط مدة الرحلة (دقيقة)</CardTitle>
            </CardHeader>
            <CardContent>
              {airlines.length === 0 ? <EmptyState /> : (
                <ResponsiveContainer width="100%" height={320}>
                  <BarChart
                    data={airlines
                      .slice(0, 15)
                      .filter(a => a.avg_flight_duration_min != null)
                      .map(a => ({
                        ناقل: a.operator_icao,
                        دقائق: Math.round(a.avg_flight_duration_min || 0),
                      }))}
                    layout="vertical"
                    margin={{ right: 30 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" horizontal={false} strokeOpacity={0.3} />
                    <XAxis type="number" tick={{ fontSize: 12 }} />
                    <YAxis type="category" dataKey="ناقل" tick={{ fontSize: 11, fontFamily: 'monospace', fontWeight: 'bold' }} width={60} />
                    <Tooltip
                      contentStyle={{ fontFamily: 'Tajawal', direction: 'rtl', borderRadius: '8px' }}
                      formatter={(v: number) => [`${v.toLocaleString('ar')} دقيقة`, 'متوسط المدة']}
                      cursor={{ fill: 'var(--muted)' }}
                    />
                    <Bar dataKey="دقائق" fill="#f59e0b" radius={[0, 4, 4, 0]} maxBarSize={25} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </CardContent>
          </Card>

          {/* Airline table with Pagination */}
          <Card className="lg:col-span-2 border-none shadow-sm">
            <CardContent className="pt-6">
              <div className="rounded-lg border overflow-auto">
                <table className="w-full text-sm">
                  <thead className="bg-muted/50">
                    <tr>
                      <th className="p-3 text-right font-medium w-12">#</th>
                      <th className="p-3 text-right font-medium">كود الناقل</th>
                      <th className="p-3 text-right font-medium">الاسم التجاري</th>
                      <th className="p-3 text-left font-medium">إجمالي الرحلات</th>
                      <th className="p-3 text-left font-medium">نشطة الآن</th>
                      <th className="p-3 text-left font-medium">متوسط المدة</th>
                      <th className="p-3 text-left font-medium">المسافة المقطوعة</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {airlines.map((a, i) => (
                      <tr key={a.operator_icao} className="hover:bg-muted/30 transition-colors">
                        <td className="p-3 text-center text-muted-foreground">{(airlinesPage - 1) * 15 + i + 1}</td>
                        <td className="p-3 font-mono font-bold text-primary text-base">{a.operator_icao}</td>
                        <td className="p-3 text-muted-foreground font-medium">{a.operator_name || '—'}</td>
                        <td className="p-3 font-bold text-lg text-left">{a.total_flights.toLocaleString('ar')}</td>
                        <td className="p-3 text-green-600 font-bold text-left">{a.active_flights.toLocaleString('ar')}</td>
                        <td className="p-3 text-left text-muted-foreground">
                          {a.avg_flight_duration_min != null
                            ? `${Math.round(a.avg_flight_duration_min).toLocaleString('ar')} د` : '—'}
                        </td>
                        <td className="p-3 text-left text-muted-foreground">
                          {a.total_distance_km != null
                            ? `${Math.round(a.total_distance_km).toLocaleString('ar')} كم` : '—'}
                        </td>
                      </tr>
                    ))}
                    {airlines.length === 0 && (
                      <tr><td colSpan={7} className="p-8 text-center text-muted-foreground">لا توجد بيانات مطابقة للفلتر</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
              {/* Pagination Controls */}
              {airlinesPages > 1 && (
                <div className="flex items-center justify-between mt-4">
                  <Button variant="outline" size="sm" disabled={airlinesPage <= 1 || loading} onClick={() => loadAirlinesPage(airlinesPage - 1)}>السابق</Button>
                  <span className="text-sm text-muted-foreground">صفحة {airlinesPage} من {airlinesPages}</span>
                  <Button variant="outline" size="sm" disabled={airlinesPage >= airlinesPages || loading} onClick={() => loadAirlinesPage(airlinesPage + 1)}>التالي</Button>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-muted-foreground gap-3 bg-muted/20 rounded-lg border border-dashed">
      <span className="text-5xl opacity-50">📊</span>
      <p className="text-base font-medium">لا توجد بيانات للعرض</p>
      <p className="text-sm opacity-70">قم بتغيير النطاق الزمني أو اضغط "تطبيق الفلاتر"</p>
    </div>
  );
}