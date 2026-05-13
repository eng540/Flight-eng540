/**
 * HistorySection.tsx — v2.0 (Entity Intelligence Dashboard)
 *
 * CHANGES:
 * - Transformed from a simple data table into a rich Entity Intelligence Dashboard.
 * - Added Flight Status Distribution chart (PieChart).
 * - Improved Top Routes chart (removed hardcoded slicing, better UI).
 * - Enhanced Stats Cards to highlight Distance and Duration metrics.
 * - Improved table readability and styling.
 */
import { useState, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button }  from '@/components/ui/button';
import { Input }   from '@/components/ui/input';
import { Label }   from '@/components/ui/label';
import {
  Select, SelectContent, SelectItem,
  SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid, Cell,
  PieChart, Pie, Legend
} from 'recharts';
import { historyApi } from '@/api/client';
import type {
  HistoryEntityType, HistoryQueryResponse,
  FlightSearchItem, RouteStats,
} from '@/types';

const ENTITY_META: Record<HistoryEntityType, { label: string; placeholder: string; example: string }> = {
  aircraft: { label: 'ICAO24 الطائرة',  placeholder: 'مثال: 710a1b', example: '710a1b' },
  airport:  { label: 'كود المطار',      placeholder: 'مثال: OERK أو RUH', example: 'OERK' },
  airline:  { label: 'كود الناقل ICAO', placeholder: 'مثال: SVA', example: 'SVA' },
  country:  { label: 'رمز الدولة',      placeholder: 'مثال: SA أو AE', example: 'SA' },
  region:   { label: 'مفتاح المنطقة',   placeholder: 'مثال: middle_east', example: 'middle_east' },
};

const COLORS = ['#3b82f6','#10b981','#f59e0b','#ef4444','#8b5cf6','#06b6d4'];
const STATUS_COLORS: Record<string, string> = {
  'completed': '#10b981', // Green
  'landed': '#3b82f6',    // Blue
  'active': '#f59e0b',    // Yellow
  'lost_signal': '#ef4444' // Red
};

export function HistorySection() {
  const [entityType, setEntityType] = useState<HistoryEntityType>('airport');
  const [entityId,   setEntityId]   = useState('');
  const [dateFrom,   setDateFrom]   = useState('');
  const [dateTo,     setDateTo]     = useState('');
  const [response,   setResponse]   = useState<HistoryQueryResponse | null>(null);
  const [loading,    setLoading]    = useState(false);
  const [page,       setPage]       = useState(1);

  const PAGE_SIZE = 50;

  const executeQuery = useCallback(async (p = 1) => {
    if (!entityId.trim()) return;
    setLoading(true);
    try {
      const res = await historyApi.query({
        entity_type: entityType,
        entity_id:   entityId.trim().toUpperCase().replace(/\s/g, ''),
        ...(dateFrom && { date_from: dateFrom }),
        ...(dateTo   && { date_to:   dateTo }),
        page:      p,
        page_size: PAGE_SIZE,
      });
      setResponse(res);
      setPage(p);
    } catch (e) { console.error('[History]', e); }
    setLoading(false);
  }, [entityType, entityId, dateFrom, dateTo]);

  const handleExport = () => {
    const url = historyApi.exportCsvUrl({
      entity_type: entityType,
      entity_id:   entityId.trim().toUpperCase(),
      ...(dateFrom && { date_from: dateFrom }),
      ...(dateTo   && { date_to: dateTo }),
    });
    window.open(url, '_blank');
  };

  const meta = ENTITY_META[entityType];

  const durStr = (f: FlightSearchItem) => {
    if (!f.duration_seconds) return '—';
    const h = Math.floor(f.duration_seconds / 3600);
    const m = Math.floor((f.duration_seconds % 3600) / 60);
    return h > 0 ? `${h}س ${m}د` : `${m} د`;
  };

  const statusLabel = (s: string | null) => {
    const map: Record<string, string> = {
      active: 'نشطة', landed: 'هبطت',
      lost_signal: 'انقطع الاتصال', completed: 'مكتملة',
    };
    return map[s || ''] || s || 'غير معروف';
  };

  // Calculate status distribution for the pie chart based on the current page data
  // (Ideally this would come from the backend aggregations, but we use page data as a proxy for now)
  const statusDistribution = response?.data.reduce((acc, flight) => {
    const status = flight.flight_status || 'unknown';
    acc[status] = (acc[status] || 0) + 1;
    return acc;
  }, {} as Record<string, number>);

  const pieData = statusDistribution ? Object.entries(statusDistribution).map(([key, value]) => ({
    name: statusLabel(key),
    value,
    originalKey: key
  })) : [];

  return (
    <div className="space-y-8">

      {/* ── Query Form ───────────────────────────────────────────────────── */}
      <Card className="border-primary/10 shadow-sm">
        <CardHeader className="pb-2">
          <CardTitle className="text-base flex items-center gap-2">
            <span>🔍</span> محدد الكيان (Entity Selector)
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4 items-end">

            {/* Entity type */}
            <div className="space-y-2">
              <Label className="text-xs font-semibold text-muted-foreground">نوع الكيان</Label>
              <Select
                value={entityType}
                onValueChange={v => { setEntityType(v as HistoryEntityType); setEntityId(''); }}
              >
                <SelectTrigger className="bg-muted/50"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="aircraft">✈️ طائرة بعينها</SelectItem>
                  <SelectItem value="airport">🛫 مطار</SelectItem>
                  <SelectItem value="airline">🏢 ناقل جوي</SelectItem>
                  <SelectItem value="country">🌍 دولة</SelectItem>
                  <SelectItem value="region">🗺️ منطقة جغرافية</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* Entity ID */}
            <div className="space-y-2">
              <Label className="text-xs font-semibold text-muted-foreground">{meta.label}</Label>
              <Input
                placeholder={meta.placeholder}
                value={entityId}
                onChange={e => setEntityId(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && executeQuery(1)}
                className="bg-muted/50 font-mono"
              />
            </div>

            {/* Date range */}
            <div className="space-y-2">
              <Label className="text-xs font-semibold text-muted-foreground">من تاريخ</Label>
              <Input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} className="bg-muted/50" />
            </div>
            <div className="space-y-2">
              <Label className="text-xs font-semibold text-muted-foreground">إلى تاريخ</Label>
              <Input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} className="bg-muted/50" />
            </div>
          </div>

          <div className="flex flex-col sm:flex-row justify-between items-center pt-4 border-t gap-4">
            <p className="text-xs text-muted-foreground">
              مثال: ابحث عن {meta.label} <code className="bg-muted px-1 py-0.5 rounded">{meta.example}</code>
            </p>
            <div className="flex gap-2 w-full sm:w-auto">
              {response && response.total > 0 && (
                <Button variant="outline" onClick={handleExport} className="gap-2 shadow-sm">
                  📥 تصدير (CSV)
                </Button>
              )}
              <Button onClick={() => executeQuery(1)} disabled={loading || !entityId.trim()} className="w-full sm:w-40 shadow-md">
                {loading ? '⏳ جاري الاستعلام…' : '🔍 استعلام'}
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* ── Aggregations & Visuals ───────────────────────────────────────── */}
      {response?.aggregations && (
        <div className="space-y-6 animate-in fade-in duration-500">
          
          {/* Stats Cards */}
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
            {/* Context Card */}
            <Card className="border-none shadow-sm bg-primary/5">
              <CardContent className="p-4 flex flex-col justify-center h-full">
                <div className="text-2xl mb-2">📄</div>
                <div className="text-sm text-muted-foreground mb-1">الكيان المستهدف</div>
                <div className="font-bold text-lg text-primary truncate" dir="ltr">{response.entity_id}</div>
                <div className="text-xs text-muted-foreground mt-2">
                  صفحة {response.page} من {response.pages}
                </div>
              </CardContent>
            </Card>

            {[
              ['إجمالي الرحلات',   response.aggregations.total_flights,    '✈️', 'text-blue-600'],
              ['طائرات فريدة',    response.aggregations.unique_aircraft,  '🛩️', 'text-purple-600'],
              ['إجمالي المسافة',
               response.aggregations.total_distance_km != null
                 ? `${Math.round(response.aggregations.total_distance_km).toLocaleString('ar')} كم`
                 : '—', '🌐', 'text-green-600'],
              ['متوسط المدة',
               response.aggregations.avg_duration_min != null
                 ? `${Math.round(response.aggregations.avg_duration_min).toLocaleString('ar')} د`
                 : '—', '⏱️', 'text-amber-600'],
            ].map(([label, value, icon, colorClass]) => (
              <Card key={label as string} className="border-none shadow-sm hover:shadow-md transition-shadow">
                <CardContent className="p-4 flex flex-col items-center text-center h-full justify-center">
                  <div className="text-2xl mb-2">{icon}</div>
                  <div className={`text-2xl font-bold ${colorClass}`}>
                    {typeof value === 'number' ? value.toLocaleString('ar') : value}
                  </div>
                  <div className="text-xs text-muted-foreground mt-1 font-medium">{label}</div>
                </CardContent>
              </Card>
            ))}
          </div>

          {/* Charts Row */}
          <div className="grid gap-6 lg:grid-cols-3">
            
            {/* Top Routes Chart */}
            {response.aggregations.top_routes.length > 0 && (
              <Card className="lg:col-span-2 border-none shadow-sm">
                <CardHeader className="pb-2">
                  <CardTitle className="text-lg">🛤️ أبرز الطرق الجوية للكيان</CardTitle>
                  <CardDescription>أكثر المسارات تكراراً بناءً على نتائج البحث</CardDescription>
                </CardHeader>
                <CardContent>
                  <ResponsiveContainer width="100%" height={250}>
                    <BarChart
                      data={response.aggregations.top_routes.map((r: RouteStats) => ({
                        route:  `${r.departure}←${r.arrival}`,
                        رحلات: r.flight_count,
                      }))}
                      layout="vertical"
                      margin={{ right: 30 }}
                    >
                      <CartesianGrid strokeDasharray="3 3" horizontal={false} strokeOpacity={0.3} />
                      <XAxis type="number" tick={{ fontSize: 12 }} />
                      <YAxis type="category" dataKey="route" tick={{ fontSize: 11, fontFamily: 'monospace', fontWeight: 'bold' }} width={110} />
                      <Tooltip
                        contentStyle={{ fontFamily: 'Tajawal', direction: 'rtl', borderRadius: '8px' }}
                        formatter={(v: number) => [v.toLocaleString('ar'), 'رحلات']}
                        cursor={{ fill: 'var(--muted)' }}
                      />
                      <Bar dataKey="رحلات" radius={[0, 4, 4, 0]} barSize={20}>
                        {response.aggregations.top_routes.map((_: RouteStats, i: number) => (
                          <Cell key={i} fill={COLORS[i % COLORS.length]} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </CardContent>
              </Card>
            )}

            {/* Status Distribution Chart (NEW) */}
            {pieData.length > 0 && (
              <Card className="border-none shadow-sm">
                <CardHeader className="pb-2">
                  <CardTitle className="text-lg">📊 توزيع حالات الرحلات</CardTitle>
                  <CardDescription>بناءً على الصفحة الحالية</CardDescription>
                </CardHeader>
                <CardContent>
                  <ResponsiveContainer width="100%" height={250}>
                    <PieChart>
                      <Pie
                        data={pieData}
                        dataKey="value"
                        nameKey="name"
                        cx="50%" cy="50%" 
                        innerRadius={40}
                        outerRadius={80}
                        paddingAngle={2}
                        label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                        labelLine={false}
                      >
                        {pieData.map((entry, i) => (
                          <Cell key={i} fill={STATUS_COLORS[entry.originalKey] || COLORS[i % COLORS.length]} />
                        ))}
                      </Pie>
                      <Tooltip
                        formatter={(v: number) => [v.toLocaleString('ar'), 'رحلة']}
                        contentStyle={{ fontFamily: 'Tajawal', borderRadius: '8px' }}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                </CardContent>
              </Card>
            )}
          </div>
        </div>
      )}

      {/* ── Results Table ─────────────────────────────────────────────────── */}
      {response && (
        <Card className="border-none shadow-sm animate-in fade-in duration-500">
          <CardHeader className="pb-4 border-b">
            <div className="flex items-center justify-between">
              <CardTitle className="text-lg flex items-center gap-2">
                <span>📋</span> سجل الرحلات التفصيلي
                <Badge variant="secondary" className="mr-2 bg-primary/10 text-primary hover:bg-primary/20">
                  {response.total.toLocaleString('ar')} رحلة
                </Badge>
              </CardTitle>
            </div>
          </CardHeader>
          <CardContent className="pt-0 p-0">
            {response.data.length === 0 ? (
              <div className="text-center py-16 text-muted-foreground bg-muted/10">
                <span className="text-5xl block mb-4 opacity-50">📭</span>
                <p className="text-lg font-medium">لا توجد رحلات مطابقة</p>
                <p className="text-sm opacity-70">حاول تغيير الكيان أو النطاق الزمني</p>
              </div>
            ) : (
              <div className="overflow-auto">
                <table className="w-full text-sm">
                  <thead className="bg-muted/50 sticky top-0">
                    <tr>
                      <th className="p-3 text-right font-medium whitespace-nowrap">رمز الاستدعاء</th>
                      <th className="p-3 text-right font-medium whitespace-nowrap">الناقل</th>
                      <th className="p-3 text-right font-medium whitespace-nowrap">الطائرة</th>
                      <th className="p-3 text-right font-medium whitespace-nowrap">المغادرة</th>
                      <th className="p-3 text-right font-medium whitespace-nowrap">الوصول</th>
                      <th className="p-3 text-right font-medium whitespace-nowrap">وقت الإقلاع</th>
                      <th className="p-3 text-right font-medium whitespace-nowrap">المدة</th>
                      <th className="p-3 text-right font-medium whitespace-nowrap">المسافة</th>
                      <th className="p-3 text-right font-medium whitespace-nowrap">الحالة</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {response.data.map((f: FlightSearchItem) => (
                      <tr key={f.session_id} className="hover:bg-muted/30 transition-colors">
                        <td className="p-3 font-mono font-bold text-base">
                          {f.callsign || '—'}
                          {f.flight_number && (
                            <span className="text-muted-foreground text-xs mr-2 font-normal">
                              ({f.flight_number})
                            </span>
                          )}
                        </td>
                        <td className="p-3 font-medium">{f.operator?.icao_code || '—'}</td>
                        <td className="p-3 font-mono text-xs">
                          {f.aircraft?.icao24 || '—'}
                          {f.aircraft?.type_code && (
                            <Badge variant="outline" className="mr-2 text-[10px] py-0 h-4 bg-background">
                              {f.aircraft.type_code}
                            </Badge>
                          )}
                        </td>
                        <td className="p-3 font-mono font-bold text-primary text-base">
                          {f.dep_airport?.icao_code || '—'}
                        </td>
                        <td className="p-3 font-mono font-bold text-primary text-base">
                          {f.arr_airport?.icao_code || '—'}
                        </td>
                        <td className="p-3 text-xs text-muted-foreground whitespace-nowrap">
                          {f.actual_takeoff_ts || f.first_seen_ts
                            ? new Date(f.actual_takeoff_ts || f.first_seen_ts!).toLocaleString('ar-SA', {
                                dateStyle: 'short', timeStyle: 'short',
                              })
                            : '—'}
                        </td>
                        <td className="p-3 text-sm font-medium">{durStr(f)}</td>
                        <td className="p-3 text-sm font-medium">
                          {f.total_distance_km != null
                            ? `${Math.round(f.total_distance_km).toLocaleString('ar')} كم` : '—'}
                        </td>
                        <td className="p-3">
                          <Badge 
                            variant="outline" 
                            style={{ 
                              borderColor: STATUS_COLORS[f.flight_status || ''] || '#ccc',
                              color: STATUS_COLORS[f.flight_status || ''] || '#666',
                              backgroundColor: `${STATUS_COLORS[f.flight_status || ''] || '#ccc'}15`
                            }}
                          >
                            {statusLabel(f.flight_status)}
                          </Badge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            
            {/* Pagination Controls */}
            {response.pages > 1 && (
              <div className="flex items-center justify-between p-4 border-t bg-muted/10">
                <Button variant="outline" size="sm" disabled={page <= 1 || loading} onClick={() => executeQuery(page - 1)}>
                  السابق
                </Button>
                <span className="text-sm font-medium text-muted-foreground">
                  صفحة {page} من {response.pages}
                </span>
                <Button variant="outline" size="sm" disabled={page >= response.pages || loading} onClick={() => executeQuery(page + 1)}>
                  التالي
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}