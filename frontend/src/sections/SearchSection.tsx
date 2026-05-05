/**
 * SearchSection.tsx — v1.0 (TIER 4 PART D — NEW)
 * Evidence: business requirement "Search System"
 *   - Multi-field search
 *   - Filters (date, airline, airport)
 *   - Results table
 *   - CSV export
 * All text Arabic. Calls GET /api/v1/flights/search.
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
import { Badge }   from '@/components/ui/badge';
import { flightsV1Api } from '@/api/client';
import type { FlightSearchItem } from '@/types';

export function SearchSection() {
  // Search fields
  const [callsign,     setCallsign]     = useState('');
  const [icao24,       setIcao24]       = useState('');
  const [flightNumber, setFlightNumber] = useState('');
  const [operatorIcao, setOperatorIcao] = useState('');
  const [depIcao,      setDepIcao]      = useState('');
  const [arrIcao,      setArrIcao]      = useState('');
  const [status,       setStatus]       = useState('all');
  const [dateFrom,     setDateFrom]     = useState('');
  const [dateTo,       setDateTo]       = useState('');

  // Results state
  const [results,   setResults]   = useState<FlightSearchItem[]>([]);
  const [total,     setTotal]     = useState(0);
  const [page,      setPage]      = useState(1);
  const [pages,     setPages]     = useState(1);
  const [loading,   setLoading]   = useState(false);
  const [searched,  setSearched]  = useState(false);

  const PAGE_SIZE = 50;

  const buildParams = useCallback((p = 1) => ({
    ...(callsign     && { callsign }),
    ...(icao24       && { icao24 }),
    ...(flightNumber && { flight_number: flightNumber }),
    ...(operatorIcao && { operator_icao: operatorIcao }),
    ...(depIcao      && { dep_icao: depIcao }),
    ...(arrIcao      && { arr_icao: arrIcao }),
    ...(status !== 'all' && { status }),
    ...(dateFrom     && { date_from: dateFrom }),
    ...(dateTo       && { date_to:   dateTo }),
    page: p, page_size: PAGE_SIZE,
  }), [callsign, icao24, flightNumber, operatorIcao, depIcao, arrIcao, status, dateFrom, dateTo]);

  const search = useCallback(async (p = 1) => {
    setLoading(true);
    try {
      const res = await flightsV1Api.search(buildParams(p));
      setResults(res.data  || []);
      setTotal(res.total   || 0);
      setPage(res.page     || 1);
      setPages(res.pages   || 1);
      setSearched(true);
    } catch (e) { console.error('[Search]', e); }
    setLoading(false);
  }, [buildParams]);

  const handleExport = () => {
    const url = flightsV1Api.exportCsv(buildParams(1) as Record<string, unknown>);
    window.open(url, '_blank');
  };

  const statusLabel = (s: string | null) => {
    const map: Record<string, string> = {
      active: '🟢 نشطة', landed: '🛬 هبطت',
      lost_signal: '📡 انقطع الاتصال', completed: '✅ مكتملة',
    };
    return map[s || ''] || s || '—';
  };

  return (
    <div className="space-y-5">

      {/* ── Search Form ─────────────────────────────────────────────────── */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">🔍 البحث في الرحلات</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <div className="space-y-1">
              <Label className="text-xs">رمز الاستدعاء (Callsign)</Label>
              <Input placeholder="مثال: SVA462" value={callsign}
                onChange={e => setCallsign(e.target.value.toUpperCase())} />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">ICAO24 الطائرة</Label>
              <Input placeholder="مثال: 710a1b" value={icao24}
                onChange={e => setIcao24(e.target.value.toLowerCase())} />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">رقم الرحلة التجاري</Label>
              <Input placeholder="مثال: SV462" value={flightNumber}
                onChange={e => setFlightNumber(e.target.value.toUpperCase())} />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">كود الناقل ICAO</Label>
              <Input placeholder="مثال: SVA" value={operatorIcao}
                onChange={e => setOperatorIcao(e.target.value.toUpperCase())} />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">مطار المغادرة ICAO</Label>
              <Input placeholder="مثال: OERK" value={depIcao}
                onChange={e => setDepIcao(e.target.value.toUpperCase())} />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">مطار الوصول ICAO</Label>
              <Input placeholder="مثال: OMDB" value={arrIcao}
                onChange={e => setArrIcao(e.target.value.toUpperCase())} />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">حالة الرحلة</Label>
              <Select value={status} onValueChange={setStatus}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">جميع الحالات</SelectItem>
                  <SelectItem value="active">🟢 نشطة</SelectItem>
                  <SelectItem value="landed">🛬 هبطت</SelectItem>
                  <SelectItem value="lost_signal">📡 انقطع الاتصال</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">من تاريخ</Label>
              <Input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">إلى تاريخ</Label>
              <Input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} />
            </div>
          </div>

          <div className="flex gap-2 pt-1">
            <Button onClick={() => search(1)} disabled={loading} className="flex-1 sm:flex-none sm:px-8">
              {loading ? '⏳ جاري البحث…' : '🔍 بحث'}
            </Button>
            {searched && results.length > 0 && (
              <Button variant="outline" onClick={handleExport} className="gap-2">
                📥 تصدير CSV
              </Button>
            )}
            <Button variant="ghost" onClick={() => {
              setCallsign(''); setIcao24(''); setFlightNumber('');
              setOperatorIcao(''); setDepIcao(''); setArrIcao('');
              setStatus('all'); setDateFrom(''); setDateTo('');
              setResults([]); setSearched(false);
            }}>
              مسح
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* ── Results ─────────────────────────────────────────────────────── */}
      {searched && (
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-base">
                نتائج البحث
                <Badge variant="secondary" className="mr-2">
                  {total.toLocaleString('ar')} رحلة
                </Badge>
              </CardTitle>
              {pages > 1 && (
                <div className="flex items-center gap-2 text-sm">
                  <Button size="sm" variant="outline"
                    disabled={page <= 1} onClick={() => search(page - 1)}>
                    ›
                  </Button>
                  <span className="text-muted-foreground">
                    {page} / {pages}
                  </span>
                  <Button size="sm" variant="outline"
                    disabled={page >= pages} onClick={() => search(page + 1)}>
                    ‹
                  </Button>
                </div>
              )}
            </div>
          </CardHeader>
          <CardContent>
            {results.length === 0 ? (
              <div className="text-center py-12 text-muted-foreground">
                <span className="text-4xl block mb-3">🔍</span>
                <p>لا توجد نتائج مطابقة لمعايير البحث</p>
              </div>
            ) : (
              <div className="overflow-auto rounded border">
                <table className="w-full text-sm">
                  <thead className="bg-muted">
                    <tr>
                      <th className="p-2 text-right whitespace-nowrap">رمز الاستدعاء</th>
                      <th className="p-2 text-right whitespace-nowrap">رقم الرحلة</th>
                      <th className="p-2 text-right whitespace-nowrap">الناقل</th>
                      <th className="p-2 text-right whitespace-nowrap">الطائرة</th>
                      <th className="p-2 text-right whitespace-nowrap">المغادرة</th>
                      <th className="p-2 text-right whitespace-nowrap">الوصول</th>
                      <th className="p-2 text-right whitespace-nowrap">وقت الإقلاع</th>
                      <th className="p-2 text-right whitespace-nowrap">المدة</th>
                      <th className="p-2 text-right whitespace-nowrap">الحالة</th>
                    </tr>
                  </thead>
                  <tbody>
                    {results.map(f => {
                      const dur = f.duration_seconds
                        ? `${Math.floor(f.duration_seconds / 3600)}س ${Math.floor((f.duration_seconds % 3600) / 60)}د`
                        : '—';
                      return (
                        <tr key={f.session_id} className="border-t hover:bg-muted/40">
                          <td className="p-2 font-mono font-bold">{f.callsign || '—'}</td>
                          <td className="p-2 font-mono">{f.flight_number || '—'}</td>
                          <td className="p-2">{f.operator?.icao_code || '—'}</td>
                          <td className="p-2 font-mono text-xs">
                            {f.aircraft?.icao24 || '—'}
                            {f.aircraft?.type_code && (
                              <span className="text-muted-foreground"> · {f.aircraft.type_code}</span>
                            )}
                          </td>
                          <td className="p-2 font-mono font-bold text-primary">
                            {f.dep_airport?.icao_code || '—'}
                          </td>
                          <td className="p-2 font-mono font-bold text-primary">
                            {f.arr_airport?.icao_code || '—'}
                          </td>
                          <td className="p-2 text-xs text-muted-foreground whitespace-nowrap">
                            {f.actual_takeoff_ts
                              ? new Date(f.actual_takeoff_ts).toLocaleString('ar-SA', {
                                  dateStyle: 'short', timeStyle: 'short',
                                })
                              : f.first_seen_ts
                                ? new Date(f.first_seen_ts).toLocaleString('ar-SA', {
                                    dateStyle: 'short', timeStyle: 'short',
                                  })
                                : '—'}
                          </td>
                          <td className="p-2 text-xs">{dur}</td>
                          <td className="p-2 whitespace-nowrap">{statusLabel(f.flight_status)}</td>
                        </tr>
                      );
                    })}
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
