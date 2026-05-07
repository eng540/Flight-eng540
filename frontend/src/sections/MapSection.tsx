/**
 * MapSection.tsx — v4.1 (Multi-Source Indicators)
 *
 * UPGRADES:
 *   - Added visual indicators for data_source (AirLabs, FR24, OpenSky).
 *   - Displays the source in the map popup and the detail panel.
 */
import { useEffect, useRef, useState, useCallback } from 'react';
import {
  Card, CardContent, CardHeader, CardTitle,
} from '@/components/ui/card';
import { Button }  from '@/components/ui/button';
import { Label }   from '@/components/ui/label';
import {
  Select, SelectContent, SelectItem,
  SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Badge }  from '@/components/ui/badge';
import { liveApi, regionsApi } from '@/api/client';
import type { GeoRegion, LivePosition } from '@/types';

/* Leaflet loaded from CDN at runtime */
declare global {
  interface Window { L: typeof import('leaflet') }
}

const REFRESH_INTERVAL_MS = 60_000; // 60 seconds

// Helper to get source icon
const getSourceIcon = (source?: string | null) => {
  if (source === 'AIRLABS') return '✈️ AirLabs';
  if (source === 'FR24')    return '🌍 FR24';
  if (source === 'OPENSKY') return '📡 OpenSky';
  return '❓ غير معروف';
};

export function MapSection() {
  const mapDiv     = useRef<HTMLDivElement>(null);
  const mapRef     = useRef<unknown>(null);
  const markersRef = useRef<unknown>(null);
  const regionsRef = useRef<unknown>(null);
  const refreshRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const [mapReady,   setMapReady]   = useState(false);
  const [regions,    setRegions]    = useState<GeoRegion[]>([]);
  const [positions,  setPositions]  = useState<LivePosition[]>([]);
  const [total,      setTotal]      = useState(0);
  const [active,     setActive]     = useState(0);
  const [loading,    setLoading]    = useState(false);
  const [selected,   setSelected]   = useState<LivePosition | null>(null);
  const [showBoxes,  setShowBoxes]  = useState(true);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  // Filters
  const [regionKey, setRegionKey] = useState('all');
  const [onGround,  setOnGround]  = useState<'all' | 'airborne' | 'ground'>('all');

  // ── Load Leaflet from CDN ─────────────────────────────────────────────────
  useEffect(() => {
    if (window.L) { setMapReady(true); return; }
    const css    = document.createElement('link');
    css.rel      = 'stylesheet';
    css.href     = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
    document.head.appendChild(css);
    const js     = document.createElement('script');
    js.src       = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
    js.onload    = () => setMapReady(true);
    document.head.appendChild(js);
  }, []);

  // ── Init map ──────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!mapReady || !mapDiv.current || mapRef.current) return;
    const L   = window.L;
    const map = L.map(mapDiv.current).setView([24, 45], 4);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '© <a href="https://openstreetmap.org">OpenStreetMap</a>',
      maxZoom: 18,
    }).addTo(map);
    mapRef.current   = map;
    markersRef.current = L.layerGroup().addTo(map);
    regionsRef.current = L.layerGroup().addTo(map);

    // Load regions
    regionsApi.listRegions()
      .then((data: GeoRegion[]) => setRegions(data))
      .catch(console.error);
  }, [mapReady]);

  // ── Draw region rectangles ────────────────────────────────────────────────
  useEffect(() => {
    if (!mapReady || !regionsRef.current) return;
    const L     = window.L;
    const layer = regionsRef.current as ReturnType<typeof L.layerGroup>;
    layer.clearLayers();
    if (!showBoxes) return;
    regions.forEach(r => {
      L.rectangle(
        [[r.lamin, r.lomin], [r.lamax, r.lomax]],
        { color: '#3b82f6', weight: 1.5, fillOpacity: 0.04, dashArray: '5 5' },
      ).bindTooltip(
        `<b>${r.name_ar}</b><br><small>${r.name}</small>`,
        { sticky: true, direction: 'auto' },
      ).addTo(layer);
    });
  }, [mapReady, regions, showBoxes]);

  // ── Fetch live positions ──────────────────────────────────────────────────
  const fetchPositions = useCallback(async () => {
    setLoading(true);
    try {
      const params: Parameters<typeof liveApi.getPositions>[0] = {
        limit: 1000,
      };
      if (regionKey && regionKey !== 'all') params.region_key = regionKey;
      if (onGround === 'airborne') params.on_ground = false;
      if (onGround === 'ground')   params.on_ground = true;

      const res = await liveApi.getPositions(params);
      setPositions(res.data  || []);
      setTotal(res.total  || 0);
      setActive(res.active || 0);
      setLastUpdate(new Date());
    } catch (e) { console.error('[Live Map]', e); }
    setLoading(false);
  }, [regionKey, onGround]);

  // Initial load + auto-refresh every 60s
  useEffect(() => {
    if (!mapReady) return;
    fetchPositions();
    refreshRef.current = setInterval(fetchPositions, REFRESH_INTERVAL_MS);
    return () => {
      if (refreshRef.current) clearInterval(refreshRef.current);
    };
  }, [mapReady, fetchPositions]);

  // ── Draw aircraft markers ─────────────────────────────────────────────────
  useEffect(() => {
    if (!mapReady || !markersRef.current) return;
    const L     = window.L;
    const layer = markersRef.current as ReturnType<typeof L.layerGroup>;
    layer.clearLayers();

    const withPos = positions.filter(p => p.latitude != null && p.longitude != null);
    withPos.forEach(p => {
      const heading = p.heading_deg ?? 0;
      const color = ['7500','7600','7700'].includes(p.squawk || '')
        ? '#ef4444'
        : p.on_ground ? '#6b7280' : '#3b82f6';

      const icon = L.divIcon({
        html: `<div style="transform:rotate(${heading}deg);font-size:18px;line-height:1;color:${color};filter:drop-shadow(0 1px 2px rgba(0,0,0,.4))">✈</div>`,
        className: '',
        iconSize:   [22, 22],
        iconAnchor: [11, 11],
      });

      const sourceLabel = getSourceIcon(p.data_source);

      const popupHtml = `
        <div dir="rtl" style="min-width:200px;font-family:'Tajawal',sans-serif">
          <div style="font-weight:700;font-size:14px;margin-bottom:6px;display:flex;justify-content:space-between;align-items:center">
            <span>✈ ${p.callsign || p.icao24}</span>
            <span style="font-size:10px;background:#f3f4f6;padding:2px 6px;border-radius:4px;color:#374151">${sourceLabel}</span>
          </div>
          <table style="font-size:12px;width:100%;border-collapse:collapse">
            ${row('ICAO24', `<code>${p.icao24}</code>`)}
            ${p.fr24_id ? row('FR24 ID', `<code>${p.fr24_id}</code>`) : ''}
            ${p.operator_name ? row('الناقل', p.operator_name) : ''}
            ${p.aircraft_type ? row('نوع الطائرة', p.aircraft_type) : ''}
            ${p.dep_airport_iata ? row('المغادرة', `🛫 ${p.dep_airport_iata}`) : ''}
            ${p.arr_airport_iata ? row('الوصول',   `🛬 ${p.arr_airport_iata}`) : ''}
            ${p.altitude_m  != null ? row('الارتفاع', `${Math.round(p.altitude_m)} م`) : ''}
            ${p.velocity_kmh != null ? row('السرعة',   `${Math.round(p.velocity_kmh)} كم/س`) : ''}
            ${p.vspeed_fpm  != null ? row('معدل الصعود', `${Math.round(p.vspeed_fpm)} قدم/د`) : ''}
            ${p.heading_deg != null ? row('الاتجاه',  `${Math.round(p.heading_deg)}°`) : ''}
            ${p.squawk ? row('Squawk', `<b>${p.squawk}</b>${['7500','7600','7700'].includes(p.squawk) ? ' ⚠️' : ''}`) : ''}
            ${row('الحالة', p.on_ground ? '🟡 على الأرض' : '🟢 في الجو')}
          </table>
          <div style="margin-top:8px;text-align:center">
            <button onclick="window._selectFlight('${p.icao24}')"
              style="font-size:11px;padding:2px 10px;border:1px solid #e5e7eb;border-radius:4px;cursor:pointer">
              عرض التفاصيل
            </button>
          </div>
        </div>`;

      L.marker([p.latitude!, p.longitude!], { icon })
        .bindPopup(popupHtml, { maxWidth: 280 })
        .addTo(layer);
    });

    (window as unknown as { _selectFlight: (icao24: string) => void })._selectFlight =
      (icao24: string) => {
        const found = positions.find(p => p.icao24 === icao24);
        if (found) setSelected(found);
      };
  }, [mapReady, positions]);

  const flyToRegion = (r: GeoRegion) => {
    if (!mapRef.current) return;
    const L = window.L;
    (mapRef.current as ReturnType<typeof L.map>)
      .fitBounds([[r.lamin, r.lomin], [r.lamax, r.lomax]]);
  };

  const formatTime = (d: Date) =>
    d.toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

  return (
    <div className="space-y-4">

      {/* ── Controls ──────────────────────────────────────────────────────── */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            🗺️ الخريطة الحية
            {total > 0 && (
              <>
                <Badge variant="secondary">{total.toLocaleString('ar')} طائرة</Badge>
                <Badge variant="default">{active.toLocaleString('ar')} في الجو</Badge>
              </>
            )}
            {lastUpdate && (
              <span className="text-xs text-muted-foreground font-normal">
                آخر تحديث: {formatTime(lastUpdate)}
              </span>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 mb-3">

            {/* Region filter */}
            <div className="space-y-1">
              <Label className="text-xs">المنطقة الجغرافية</Label>
              <Select value={regionKey} onValueChange={setRegionKey}>
                <SelectTrigger>
                  <SelectValue placeholder="جميع المناطق" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">جميع المناطق</SelectItem>
                  {regions.map(r => (
                    <SelectItem key={r.key} value={r.key}>{r.name_ar}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* On-ground filter */}
            <div className="space-y-1">
              <Label className="text-xs">الحالة</Label>
              <Select value={onGround}
                onValueChange={(v) => setOnGround(v as 'all' | 'airborne' | 'ground')}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">جميع الطائرات</SelectItem>
                  <SelectItem value="airborne">في الجو فقط ✈️</SelectItem>
                  <SelectItem value="ground">على الأرض فقط 🟡</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* Actions */}
            <div className="space-y-1">
              <Label className="text-xs">الإجراءات</Label>
              <div className="flex gap-2">
                <Button onClick={fetchPositions} disabled={loading} size="sm" className="flex-1">
                  {loading ? '⏳ تحميل…' : '🔄 تحديث'}
                </Button>
                <label className="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer px-2">
                  <input type="checkbox" checked={showBoxes}
                    onChange={e => setShowBoxes(e.target.checked)} className="rounded" />
                  المناطق
                </label>
              </div>
            </div>
          </div>

          {/* Region quick-fly buttons */}
          {regions.length > 0 && (
            <div className="flex gap-1.5 flex-wrap">
              {regions.map(r => (
                <Button key={r.key} variant="outline" size="sm"
                  onClick={() => flyToRegion(r)}
                  className="text-xs h-7">
                  📍 {r.name_ar}
                </Button>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── Map ───────────────────────────────────────────────────────────── */}
      <div className="relative rounded-lg overflow-hidden border bg-muted" style={{ height: 540 }}>
        <div ref={mapDiv} className="w-full h-full" />

        {!mapReady && (
          <div className="absolute inset-0 flex items-center justify-center text-muted-foreground">
            جاري تحميل الخريطة…
          </div>
        )}
        {loading && (
          <div className="absolute top-3 left-3 bg-background/90 rounded-lg px-3 py-1.5 text-xs shadow border">
            ⏳ جاري تحديث المواقع…
          </div>
        )}

        {/* Legend */}
        <div className="absolute bottom-3 right-3 bg-background/90 rounded-lg px-3 py-2 text-xs shadow border space-y-1">
          <div className="flex items-center gap-1.5"><span style={{ color: '#3b82f6' }}>✈</span> في الجو</div>
          <div className="flex items-center gap-1.5"><span style={{ color: '#6b7280' }}>✈</span> على الأرض</div>
          <div className="flex items-center gap-1.5"><span style={{ color: '#ef4444' }}>✈</span> طوارئ</div>
        </div>
      </div>

      {/* ── Selected flight detail ─────────────────────────────────────────── */}
      {selected && (
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-start justify-between">
              <div className="space-y-3 flex-1">
                {/* Title */}
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-xl">✈️</span>
                  <span className="font-bold text-lg">{selected.callsign || selected.icao24}</span>
                  {selected.flight_number && (
                    <Badge variant="outline">{selected.flight_number}</Badge>
                  )}
                  <Badge variant={selected.on_ground ? 'secondary' : 'default'}>
                    {selected.on_ground ? '🟡 على الأرض' : '🟢 في الجو'}
                  </Badge>
                  <Badge variant="outline" className="bg-muted">
                    {getSourceIcon(selected.data_source)}
                  </Badge>
                  {selected.squawk && ['7500','7600','7700'].includes(selected.squawk) && (
                    <Badge variant="destructive">⚠️ طوارئ {selected.squawk}</Badge>
                  )}
                </div>

                {/* Details grid */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-x-6 gap-y-2 text-sm">
                  {[
                    ['ICAO24',        selected.icao24],
                    ['FR24 ID',       selected.fr24_id   || '—'],
                    ['رقم الرحلة',    selected.flight_number || '—'],
                    ['الناقل',        selected.operator_name || '—'],
                    ['نوع الطائرة',   selected.aircraft_type || selected.aircraft_model || '—'],
                    ['المغادرة',      selected.dep_airport_iata ? `🛫 ${selected.dep_airport_iata}` : '—'],
                    ['الوصول',        selected.arr_airport_iata ? `🛬 ${selected.arr_airport_iata}` : '—'],
                    ['الارتفاع',      selected.altitude_m   != null ? `${Math.round(selected.altitude_m)} م` : '—'],
                    ['السرعة',        selected.velocity_kmh != null ? `${Math.round(selected.velocity_kmh)} كم/س` : '—'],
                    ['معدل الصعود',   selected.vspeed_fpm  != null ? `${Math.round(selected.vspeed_fpm)} قدم/د` : '—'],
                    ['الاتجاه',       selected.heading_deg != null ? `${Math.round(selected.heading_deg)}°` : '—'],
                    ['المنطقة',       selected.region_key  || '—'],
                  ].map(([label, value]) => (
                    <div key={label as string}>
                      <span className="text-muted-foreground text-xs">{label}: </span>
                      <span className="font-medium">{value}</span>
                    </div>
                  ))}
                </div>
              </div>

              <Button variant="ghost" size="sm" onClick={() => setSelected(null)}
                className="shrink-0">✕</Button>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ── Helper: table row for popup ───────────────────────────────────────────
function row(label: string, value: string): string {
  return `
    <tr style="border-bottom:1px solid #f3f4f6">
      <td style="padding:2px 4px;color:#6b7280;white-space:nowrap">${label}</td>
      <td style="padding:2px 4px;font-weight:500">${value}</td>
    </tr>`;
}