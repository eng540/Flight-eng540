/**
 * HistorySection.tsx — v1.0 (TIER 4 PART D — NEW)
 * Evidence: business requirement "Historical Engine UI"
 *   - Select entity type (aircraft | airport | airline | country | region)
 *   - Date range
 *   - Full results table
 *   - Aggregated stats
 * All text Arabic. Calls POST /api/v1/history/query.
 */
import { useState, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
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

  return (
    <div className="space-y-5">

      {/* ── Query Form ───────────────────────────────────────────────────── */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">🕐 محرك البيانات التاريخية</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">

            {/* Entity type */}
            <div className="space-y-1">
              <Label className="text-xs">نوع الكيان</Label>
              <Select
                value={entityType}
                onValueChange={v => { setEntityType(v as HistoryEntityType); setEntityId(''); }}
              >
                <SelectTrigger><SelectValue /></SelectTrigger>
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
            <div className="space-y-1">
              <Label className="text-xs">{meta.label}</Label>
              <Input
                placeholder={meta.placeholder}
                value={entityId}
                onChange={e => setEntityId(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && executeQuery(1)}
              />
            </div>

            {/* Date range */}
            <div className="space-y-1">
              <Label className="text-xs">من تاريخ</Label>
              <Input type="date" value={dateFrom}
                onChange={e => setDateFrom(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">إلى تاريخ</Label>
              <Input type="date" value={dateTo}
                onChange={e => setDateTo(e.target.value)} />
            </div>
          </div>

          <div className="flex gap-2">
            <Button onClick={() => executeQuery(1)} disabled={loading || !entityId.trim()}
              className="flex-1 sm:flex-none sm:px-8">
              {loading ? '⏳ جاري الاستعلام…' : '🔍 استعلام'}
            </Button>
            {response && response.total > 0 && (
              <Button variant="outline" onClick={handleExport} className="gap-2">
                📥 تصدير CSV
              </Button>
            )}
          </div>

          {/* Quick example */}
          <p className="text-xs text-muted-foreground">
            مثال: ابحث عن {meta.label} &quot;<code>{meta.example}</code>&quot; مع نطاق تاريخي
          </p>
        </CardContent>
      </Card>

      {/* ── Aggregations ─────────────────────────────────────────────────── */}
      {response?.aggregations && (
        <div className="grid gap-4 lg:grid-cols-2">

          {/* Stats cards */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">📊 إحصائيات إجمالية</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 gap-3">
                {[
                  ['إجمالي الرحلات',   response.aggregations.total_flights,    '✈️'],
                  ['طائرات فريدة',    response.aggregations.unique_aircraft,  '🛩️'],
                  ['ناقلون فريدون',   response.aggregations.unique_operators, '🏢'],
                  ['إجمالي المسافة',
                   response.aggregations.total_distance_km != null
                     ? `${Math.round(response.aggregations.total_distance_km).toLocaleString('ar')} كم`
                     : '—', '🌐'],
                  ['متوسط المدة',
                   response.aggregations.avg_duration_min != null
                     ? `${Math.round(response.aggregations.avg_duration_min).toLocaleString('ar')} د`
                     : '—', '⏱️'],
                ].map(([label, value, icon]) => (
                  <div key={label as string}
                    className="bg-muted/50 rounded-lg p-3 space-y-1">
                    <div className="text-lg">{icon}</div>
                    <div className="text-xl font-bold">
                      {typeof value === 'number'
                        ? value.toLocaleString('ar') : value}
                    </div>
                    <div className="text-xs text-muted-foreground">{label}</div>
                  </div>
                ))}

                {/* Result info */}
                <div className="bg-primary/10 rounded-lg p-3 space-y-1">
                  <div className="text-lg">📄</div>
                  <div className="text-xs text-muted-foreground">
                    نوع: <b>{entityType}</b> · معرّف: <b>{response.entity_id}</b>
                  </div>
                  <div className="text-xs text-muted-foreground">
                    الصفحة {response.page} / {response.pages}
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Top routes chart */}
          {response.aggregations.top_routes.length > 0 && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">🛤️ أبرز الطرق</CardTitle>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart
                    data={response.aggregations.top_routes.slice(0, 5).map((r: RouteStats) => ({
                      route:  `${r.departure}←${r.arrival}`,
                      رحلات: r.flight_count,
                    }))}
                    layout="vertical"
                    margin={{ right: 16 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis type="number" tick={{ fontSize: 10 }} />
                    <YAxis type="category" dataKey="route"
                      tick={{ fontSize: 10, fontFamily: 'Tajawal' }} width={110} />
                    <Tooltip
                      contentStyle={{ fontFamily: 'Tajawal', direction: 'rtl' }}
                      formatter={(v: number) => [v.toLocaleString('ar'), 'رحلات']}
                    />
                    <Bar dataKey="رحلات" radius={[0, 4, 4, 0]}>
                      {response.aggregations.top_routes.slice(0, 5).map((_: RouteStats, i: number) => (
                        <Cell key={i} fill={COLORS[i % COLORS.length]} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {/* ── Results Table ─────────────────────────────────────────────────── */}
      {response && (
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-base">
                نتائج الاستعلام
                <Badge variant="secondary" className="mr-2">
                  {response.total.toLocaleString('ar')} رحلة
                </Badge>
              </CardTitle>
              {response.pages > 1 && (
                <div className="flex items-center gap-2 text-sm">
                  <Button size="sm" variant="outline"
                    disabled={page <= 1} onClick={() => executeQuery(page - 1)}>›</Button>
                  <span className="text-muted-foreground text-xs">
                    {page} / {response.pages}
                  </span>
                  <Button size="sm" variant="outline"
                    disabled={page >= response.pages} onClick={() => executeQuery(page + 1)}>‹</Button>
                </div>
              )}
            </div>
          </CardHeader>
          <CardContent>
            {response.data.length === 0 ? (
              <div className="text-center py-12 text-muted-foreground">
                <span className="text-4xl block mb-3">🕐</span>
                <p>لا توجد رحلات في هذه الفترة</p>
              </div>
            ) : (
              <div className="overflow-auto rounded border">
                <table className="w-full text-sm">
                  <thead className="bg-muted">
                    <tr>
                      <th className="p-2 text-right whitespace-nowrap">رمز الاستدعاء</th>
                      <th className="p-2 text-right whitespace-nowrap">الناقل</th>
                      <th className="p-2 text-right whitespace-nowrap">الطائرة</th>
                      <th className="p-2 text-right whitespace-nowrap">المغادرة</th>
                      <th className="p-2 text-right whitespace-nowrap">الوصول</th>
                      <th className="p-2 text-right whitespace-nowrap">وقت الإقلاع</th>
                      <th className="p-2 text-right whitespace-nowrap">المدة</th>
                      <th className="p-2 text-right whitespace-nowrap">المسافة</th>
                    </tr>
                  </thead>
                  <tbody>
                    {response.data.map((f: FlightSearchItem) => (
                      <tr key={f.session_id} className="border-t hover:bg-muted/40">
                        <td className="p-2 font-mono font-bold">
                          {f.callsign || '—'}
                          {f.flight_number && (
                            <span className="text-muted-foreground text-xs mr-1">
                              ({f.flight_number})
                            </span>
                          )}
                        </td>
                        <td className="p-2">{f.operator?.icao_code || '—'}</td>
                        <td className="p-2 font-mono text-xs">
                          {f.aircraft?.icao24 || '—'}
                          {f.aircraft?.type_code && (
                            <Badge variant="outline" className="mr-1 text-xs py-0 h-4">
                              {f.aircraft.type_code}
                            </Badge>
                          )}
                        </td>
                        <td className="p-2 font-mono font-bold text-primary">
                          {f.dep_airport?.icao_code || '—'}
                        </td>
                        <td className="p-2 font-mono font-bold text-primary">
                          {f.arr_airport?.icao_code || '—'}
                        </td>
                        <td className="p-2 text-xs text-muted-foreground whitespace-nowrap">
                          {f.actual_takeoff_ts || f.first_seen_ts
                            ? new Date(f.actual_takeoff_ts || f.first_seen_ts!).toLocaleString('ar-SA', {
                                dateStyle: 'short', timeStyle: 'short',
                              })
                            : '—'}
                        </td>
                        <td className="p-2 text-xs">{durStr(f)}</td>
                        <td className="p-2 text-xs">
                          {f.total_distance_km != null
                            ? `${Math.round(f.total_distance_km).toLocaleString('ar')} كم` : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
