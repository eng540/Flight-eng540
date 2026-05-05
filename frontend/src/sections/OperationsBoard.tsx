/**
 * OperationsBoard.tsx — v7.0 (FULL API CAPABILITY EXPOSURE)
 *
 * "قمرة القيادة" — translates complex FR24 capabilities into
 * a simple Arabic wizard: select → configure → review → launch → track.
 *
 * INCLUDES UPGRADES:
 *   - Schema Toggling: Users can now select "Light" vs "Full" schema.
 *   - Universal Filters: Flight Summaries now accepts Airports, Call signs, 
 *     Registrations, and Aircraft Types, not just Operating As.
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button }  from '@/components/ui/button';
import { Input }   from '@/components/ui/input';
import { Label }   from '@/components/ui/label';
import { Badge }   from '@/components/ui/badge';
import {
  Select, SelectContent, SelectItem,
  SelectTrigger, SelectValue,
} from '@/components/ui/select';
import apiClient from '@/api/client';

// ─────────────────────────────────────────────────────────────────────────────
// TYPES (inline — aligned with backend schemas)
// ─────────────────────────────────────────────────────────────────────────────
interface PreflightSummary {
  operation_id: number;
  operation_ref: string;
  capability_type: string;
  capability_label: string;
  estimated_chunks: number;
  estimated_api_calls: number;
  estimated_credits: number;
  estimated_duration_seconds: number;
  estimated_duration_label: string;
  estimated_results: number;
  current_credits_balance: number | null;
  credits_sufficient: boolean | null;
  chunk_plan: ChunkPlan[];
  warnings: Warning[];
}
interface ChunkPlan {
  chunk_index: number;
  label: string;
  date_from?: string;
  date_to?: string;
  entity_id?: string;
  fr24_endpoint: string;
  estimated_credits: number;
}
interface Warning {
  level: 'info' | 'warning' | 'critical';
  code: string;
  message: string;
}
interface OperationProgress {
  id: number;
  operation_ref: string;
  capability_type: string;
  status: string;
  chunks_total: number;
  chunks_completed: number;
  chunks_failed: number;
  progress_pct: number;
  total_results_count: number;
  actual_credits_used: number;
  estimated_credits: number;
  cancel_requested: boolean;
  is_terminal: boolean;
  can_be_cancelled: boolean;
  current_chunk?: Record<string, unknown>;
  last_completed_chunk?: Record<string, unknown>;
}
interface ChunkItem {
  chunk_index: number;
  label: string;
  status: string;
  status_icon: string;
  status_label: string;
  results_count: number;
  credits_used: number;
  last_error?: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// CAPABILITY DEFINITIONS
// ─────────────────────────────────────────────────────────────────────────────
const CAPABILITIES =[
  {
    id: 'live_positions',
    icon: '📡',
    title: 'رصد حي',
    desc: 'أين الطائرات الآن فوق منطقتي؟',
    timing: '⚡ فوري',
    needsDates: false, needsEntity: false, needsFilters: false,
  },
  {
    id: 'flight_summaries',
    icon: '📋',
    title: 'ملخصات الرحلات',
    desc: 'سجل الرحلات مع خيارات فلترة شاملة (مطار، شركة، نوع طائرة)',
    timing: '📅 تاريخي',
    needsDates: true, needsEntity: false, needsFilters: true,
  },
  {
    id: 'flight_tracks',
    icon: '🛤️',
    title: 'مسار رحلة',
    desc: 'أرسم المسار الكامل لرحلة بعينها',
    timing: '📅 تاريخي',
    needsDates: false, needsEntity: true, entityLabel: 'معرّف الرحلة (fr24_id)', needsFilters: false,
  },
  {
    id: 'historic_positions',
    icon: '🕐',
    title: 'مواقع تاريخية',
    desc: 'مواقع الطائرات في فترة ماضية',
    timing: '📅 تاريخي',
    needsDates: true, needsEntity: false, needsFilters: false,
  },
  {
    id: 'static_airport',
    icon: '🏢',
    title: 'بيانات مطار',
    desc: 'معلومات ثابتة عن مطار (اسم، إحداثيات، ارتفاع)',
    timing: '🆓 مجاني',
    needsDates: false, needsEntity: true, entityLabel: 'كود المطار ICAO', needsFilters: false,
  },
  {
    id: 'static_airline',
    icon: '✈️',
    title: 'بيانات ناقل',
    desc: 'معلومات ثابتة عن شركة طيران',
    timing: '🆓 مجاني',
    needsDates: false, needsEntity: true, entityLabel: 'كود الناقل ICAO', needsFilters: false,
  },
];

const REGIONS =[
  { key: 'middle_east',  label: 'الشرق الأوسط' },
  { key: 'north_africa', label: 'شمال أفريقيا' },
  { key: 'central_asia', label: 'آسيا الوسطى' },
  { key: 'east_africa',  label: 'شرق أفريقيا' },
  { key: 'south_asia',   label: 'جنوب آسيا' },
];

// ─────────────────────────────────────────────────────────────────────────────
// MAIN COMPONENT
// ─────────────────────────────────────────────────────────────────────────────
export function OperationsBoard() {
  const [step,       setStep]       = useState<1|2|3|4>(1);
  const [capability, setCapability] = useState<string>('');
  const [regionKey,  setRegionKey]  = useState('middle_east');
  const[dateFrom,   setDateFrom]   = useState('');
  const [dateTo,     setDateTo]     = useState('');
  const [entityId,   setEntityId]   = useState('');

  // Flight Summaries Filters
  const[schemaMode, setSchemaMode] = useState('full');
  const [filterOp, setFilterOp]     = useState('');
  const [filterAirports, setFilterAirports] = useState('');
  const[filterAircraft, setFilterAircraft] = useState('');
  const [filterCallsigns, setFilterCallsigns] = useState('');
  const [filterReg, setFilterReg] = useState('');

  const [preflight,  setPreflight]  = useState<PreflightSummary | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [launching,  setLaunching]  = useState(false);
  const[error,      setError]      = useState('');

  const [operations, setOperations] = useState<OperationProgress[]>([]);
  const [expandedChunks, setExpandedChunks] = useState<Record<number, ChunkItem[]>>({});

  const pollingRefs = useRef<Record<number, ReturnType<typeof setInterval>>>({});

  const capMeta = CAPABILITIES.find(c => c.id === capability);

  // ── Load operations list ────────────────────────────────────────────────
  const loadOperations = useCallback(async () => {
    try {
      const res = await apiClient.get('/api/v1/operations?page_size=20');
      const ops: OperationProgress[] = (res.data.data ||[]).map((op: any) => ({
        ...op,
        is_terminal:      ['completed','failed','cancelled'].includes(op.status),
        can_be_cancelled: ['planned','running','partial'].includes(op.status),
      }));
      setOperations(ops);
    } catch { /* silent */ }
  },[]);

  useEffect(() => {
    loadOperations();
    const interval = setInterval(loadOperations, 5000);
    return () => clearInterval(interval);
  }, [loadOperations]);

  // ── Start polling a specific operation ─────────────────────────────────
  const startPolling = (opId: number) => {
    if (pollingRefs.current[opId]) return;
    pollingRefs.current[opId] = setInterval(async () => {
      try {
        const res = await apiClient.get(`/api/v1/operations/${opId}/progress`);
        const prog: OperationProgress = {
          ...res.data,
          is_terminal:['completed','failed','cancelled'].includes(res.data.status),
          can_be_cancelled:['planned','running','partial'].includes(res.data.status),
        };
        setOperations(prev =>
          prev.map(op => op.id === opId ? { ...op, ...prog } : op)
        );
        if (prog.is_terminal) {
          clearInterval(pollingRefs.current[opId]);
          delete pollingRefs.current[opId];
          loadOperations();
        }
      } catch { /* silent */ }
    }, 3000);
  };

  useEffect(() => {
    return () => {
      Object.values(pollingRefs.current).forEach(clearInterval);
    };
  },[]);

  // ── Step 2 → 3: Submit for pre-flight ──────────────────────────────────
  const submitForPreflight = async () => {
    setSubmitting(true);
    setError('');
    try {
      const scope: Record<string, unknown> = { region_key: regionKey };
      if (capMeta?.needsDates && dateFrom) scope.date_from = dateFrom;
      if (capMeta?.needsDates && dateTo)   scope.date_to   = dateTo;
      if (capMeta?.needsEntity && entityId) scope.entity_id = entityId.trim();

      // Bundle flight_summaries filters
      if (capMeta?.needsFilters) {
        scope.filters = {
          schema_mode: schemaMode,
          operating_as: filterOp.trim().toUpperCase() || undefined,
          airports: filterAirports.trim().toUpperCase() || undefined,
          aircraft: filterAircraft.trim().toUpperCase() || undefined,
          callsigns: filterCallsigns.trim().toUpperCase() || undefined,
          registrations: filterReg.trim().toUpperCase() || undefined,
        };
      }

      const res = await apiClient.post('/api/v1/operations', {
        capability_type: capability,
        scope,
      });
      setPreflight(res.data);
      setStep(3);
    } catch (e: any) {
      setError(e.response?.data?.detail || 'حدث خطأ أثناء حساب ملخص ما قبل التنفيذ');
    }
    setSubmitting(false);
  };

  // ── Step 3 → 4: Approve + launch ───────────────────────────────────────
  const launchOperation = async () => {
    if (!preflight) return;
    setLaunching(true);
    setError('');
    try {
      await apiClient.post(
        `/api/v1/operations/${preflight.operation_id}/approve`,
        { confirmed: true }
      );
      await loadOperations();
      startPolling(preflight.operation_id);
      setStep(4);
      // Reset wizard after short delay
      setTimeout(() => {
        setStep(1); setCapability(''); setPreflight(null);
        setDateFrom(''); setDateTo(''); setEntityId('');
        setFilterOp(''); setFilterAirports(''); setFilterAircraft('');
        setFilterCallsigns(''); setFilterReg('');
      }, 3000);
    } catch (e: any) {
      setError(e.response?.data?.detail || 'فشل إطلاق العملية');
    }
    setLaunching(false);
  };

  // ── Cancel operation ────────────────────────────────────────────────────
  const cancelOperation = async (opId: number) => {
    try {
      await apiClient.post(`/api/v1/operations/${opId}/cancel`, { reason: 'طلب المستخدم (إلغاء فوري)' });
      // Reload immediately to reflect the instant kill status
      loadOperations();
    } catch { /* silent */ }
  };

  // ── Load chunks for an operation ────────────────────────────────────────
  const loadChunks = async (opId: number) => {
    if (expandedChunks[opId]) {
      setExpandedChunks(prev => { const n = {...prev}; delete n[opId]; return n; });
      return;
    }
    try {
      const res = await apiClient.get(`/api/v1/operations/${opId}/chunks`);
      setExpandedChunks(prev => ({ ...prev, [opId]: res.data.data ||[] }));
    } catch { /* silent */ }
  };

  // ─────────────────────────────────────────────────────────────────────────
  // RENDER
  // ─────────────────────────────────────────────────────────────────────────
  return (
    <div className="space-y-6">

      {/* ── Cosmic Status Bar ─────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground bg-muted/50 rounded-lg p-3">
        <span>⚡ FR24 API</span>
        <span>📊 عمليات نشطة: {operations.filter(o => !o.is_terminal).length}</span>
        <span>✅ مكتملة: {operations.filter(o => o.status === 'completed').length}</span>
      </div>

      <div className="grid gap-6 lg:grid-cols-5">

        {/* ═══════════════════════════════════════════════════════════════
            LEFT: New Operation Wizard
        ═══════════════════════════════════════════════════════════════ */}
        <div className="lg:col-span-2 space-y-4">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                🚀 عملية جديدة
                {/* Step indicator */}
                <div className="flex gap-1 mr-auto">
                  {[1,2,3,4].map(s => (
                    <div key={s}
                      className={`w-6 h-1.5 rounded-full transition-colors ${
                        step >= s ? 'bg-primary' : 'bg-muted'
                      }`}
                    />
                  ))}
                </div>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">

              {/* ── STEP 1: Choose capability ─── */}
              {step === 1 && (
                <div className="space-y-3">
                  <p className="text-sm text-muted-foreground">ماذا تريد أن تفعل؟</p>
                  <div className="grid gap-2">
                    {CAPABILITIES.map(cap => (
                      <button key={cap.id}
                        onClick={() => { setCapability(cap.id); setStep(2); }}
                        className={`text-right p-3 rounded-lg border transition-all hover:border-primary ${
                          capability === cap.id
                            ? 'border-primary bg-primary/5'
                            : 'border-border'
                        }`}
                      >
                        <div className="flex items-center gap-2">
                          <span className="text-lg">{cap.icon}</span>
                          <div className="flex-1">
                            <div className="font-medium text-sm">{cap.title}</div>
                            <div className="text-xs text-muted-foreground">{cap.desc}</div>
                          </div>
                          <Badge variant="outline" className="text-xs shrink-0">
                            {cap.timing}
                          </Badge>
                        </div>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* ── STEP 2: Configure scope ─── */}
              {step === 2 && capMeta && (
                <div className="space-y-3">
                  <button onClick={() => setStep(1)}
                    className="text-xs text-muted-foreground hover:text-foreground">
                    ← تغيير القدرة
                  </button>
                  <div className="flex items-center gap-2 p-2 bg-muted/50 rounded">
                    <span>{capMeta.icon}</span>
                    <span className="font-medium text-sm">{capMeta.title}</span>
                  </div>

                  <p className="text-sm text-muted-foreground">على ماذا؟</p>

                  {/* Region (for non-entity, non-filter endpoints) */}
                  {!capMeta.needsEntity && !capMeta.needsFilters && (
                    <div className="space-y-1">
                      <Label className="text-xs">المنطقة الجغرافية</Label>
                      <Select value={regionKey} onValueChange={setRegionKey}>
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          {REGIONS.map(r => (
                            <SelectItem key={r.key} value={r.key}>{r.label}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  )}

                  {/* Dates */}
                  {capMeta.needsDates && (
                    <div className="grid grid-cols-2 gap-2">
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
                  )}

                  {/* Entity */}
                  {capMeta.needsEntity && !capMeta.needsFilters && (
                    <div className="space-y-1">
                      <Label className="text-xs">{capMeta.entityLabel}</Label>
                      <Input placeholder="أدخل المعرّف..."
                        value={entityId}
                        onChange={e => setEntityId(e.target.value)} />
                    </div>
                  )}

                  {/* Flight Summaries Filters (Dynamic Schema) */}
                  {capMeta.needsFilters && (
                    <div className="space-y-3 pt-2 border-t mt-2">
                      
                      <div className="space-y-1">
                        <Label className="text-xs font-bold text-primary">نوع البيانات (Schema)</Label>
                        <Select value={schemaMode} onValueChange={setSchemaMode}>
                          <SelectTrigger><SelectValue /></SelectTrigger>
                          <SelectContent>
                            <SelectItem value="light">بيانات أساسية (أرخص وأسرع)</SelectItem>
                            <SelectItem value="full">بيانات كاملة (تتضمن المدارج والمسافة)</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>

                      <p className="text-xs text-muted-foreground font-medium">يجب تعبئة حقل واحد على الأقل من الفلاتر التالية:</p>

                      <div className="grid grid-cols-2 gap-2">
                        <div className="space-y-1">
                          <Label className="text-xs">كود الشركة (ICAO)</Label>
                          <Input placeholder="مثال: SVA" value={filterOp} onChange={e => setFilterOp(e.target.value)} />
                        </div>
                        <div className="space-y-1">
                          <Label className="text-xs">كود المطار (ICAO/IATA)</Label>
                          <Input placeholder="مثال: inbound:OERK" value={filterAirports} onChange={e => setFilterAirports(e.target.value)} />
                        </div>
                        <div className="space-y-1">
                          <Label className="text-xs">نوع الطائرة (ICAO)</Label>
                          <Input placeholder="مثال: B77W" value={filterAircraft} onChange={e => setFilterAircraft(e.target.value)} />
                        </div>
                        <div className="space-y-1">
                          <Label className="text-xs">تسجيل الطائرة</Label>
                          <Input placeholder="مثال: HZ-AK11" value={filterReg} onChange={e => setFilterReg(e.target.value)} />
                        </div>
                      </div>
                    </div>
                  )}

                  {error && (
                    <p className="text-xs text-destructive bg-destructive/10 p-2 rounded">{error}</p>
                  )}

                  <Button onClick={submitForPreflight}
                    disabled={submitting}
                    className="w-full mt-2">
                    {submitting ? '⏳ جاري الحساب…' : '📋 احسب التكلفة'}
                  </Button>
                </div>
              )}

              {/* ── STEP 3: Pre-flight Review ─── */}
              {step === 3 && preflight && (
                <div className="space-y-3">
                  <div className="bg-muted/50 rounded-lg p-3 space-y-2 text-sm">
                    <div className="font-semibold">📋 إحاطة ما قبل التنفيذ</div>
                    <div className="font-mono text-xs text-muted-foreground">
                      {preflight.operation_ref}
                    </div>

                    <div className="grid grid-cols-2 gap-2 pt-1">
                      {[['🔢 مكالمات API', `${preflight.estimated_api_calls}`],['💳 التكلفة', `~${preflight.estimated_credits.toLocaleString('ar')} نقطة`],
                        ['⏱️ الوقت', preflight.estimated_duration_label],
                        ['📦 النتائج', `~${preflight.estimated_results.toLocaleString('ar')}`],
                      ].map(([label, value]) => (
                        <div key={label} className="bg-background rounded p-2 border">
                          <div className="text-xs text-muted-foreground">{label}</div>
                          <div className="font-bold text-sm">{value}</div>
                        </div>
                      ))}
                    </div>

                    {/* Chunk plan preview */}
                    <div className="space-y-1 pt-1">
                      <div className="text-xs font-medium border-b pb-1 mb-1">خطة تقطيع التنفيذ (Auto-Chunking):</div>
                      <div className="max-h-32 overflow-y-auto space-y-0.5 pr-1">
                        {preflight.chunk_plan.slice(0, 5).map(c => (
                          <div key={c.chunk_index}
                            className="flex justify-between text-xs text-muted-foreground">
                            <span>⏸️ {c.label}</span>
                            <span className="font-mono">{c.estimated_credits} pt</span>
                          </div>
                        ))}
                        {preflight.chunk_plan.length > 5 && (
                          <div className="text-xs text-muted-foreground mt-1 font-medium">
                            + {preflight.chunk_plan.length - 5} دفعات أخرى مجدولة…
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Warnings */}
                    {preflight.warnings.map((w, i) => (
                      <div key={i} className={`text-xs p-2 rounded border mt-2 ${
                        w.level === 'critical' ? 'bg-destructive/10 text-destructive border-destructive/20' :
                        w.level === 'warning'  ? 'bg-yellow-500/10 text-yellow-700 border-yellow-500/20' :
                        'bg-blue-500/10 text-blue-700 border-blue-500/20'
                      }`}>
                        {w.level === 'critical' ? '⚠️ ' :
                         w.level === 'warning'  ? '⚠ ' : 'ℹ️ '} {w.message}
                      </div>
                    ))}
                  </div>

                  {error && <p className="text-xs text-destructive">{error}</p>}

                  <div className="flex gap-2">
                    <Button variant="outline" onClick={() => setStep(2)} className="flex-1">
                      ← تعديل الفلاتر
                    </Button>
                    <Button onClick={launchOperation} disabled={launching || preflight.warnings.some(w => w.level === 'critical')} className="flex-1">
                      {launching ? '⏳ جاري الإطلاق…' : '🚀 إطلاق'}
                    </Button>
                  </div>
                </div>
              )}

              {/* ── STEP 4: Launched confirmation ─── */}
              {step === 4 && (
                <div className="text-center py-8 space-y-2">
                  <div className="text-4xl animate-bounce">🚀</div>
                  <div className="font-bold">تم الإطلاق بنجاح!</div>
                  <div className="text-xs text-muted-foreground">
                    نظام الجدولة الذكي يقوم الآن بالتعامل مع API Flightradar24.
                  </div>
                </div>
              )}

            </CardContent>
          </Card>
        </div>

        {/* ═══════════════════════════════════════════════════════════════
            RIGHT: Live Operations Tracker
        ═══════════════════════════════════════════════════════════════ */}
        <div className="lg:col-span-3 space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-bold">📊 لوحة تتبع المهمات</h2>
            <Button variant="ghost" size="sm" onClick={loadOperations}>🔄 تحديث</Button>
          </div>

          {operations.length === 0 ? (
            <div className="text-center py-16 text-muted-foreground border rounded-lg bg-card">
              <div className="text-4xl mb-2">📭</div>
              <p className="text-sm font-medium">لا توجد عمليات بعد</p>
              <p className="text-xs mt-1">أنشئ عملية جديدة من القائمة على اليمين لتجربة قدرات الـ API</p>
            </div>
          ) : (
            operations.map(op => (
              <OperationCard
                key={op.id}
                op={op}
                chunks={expandedChunks[op.id]}
                onCancel={() => cancelOperation(op.id)}
                onToggleChunks={() => loadChunks(op.id)}
                onExport={() => window.open(
                  `/api/v1/operations/${op.id}/results/export`, '_blank'
                )}
                onPoll={() => startPolling(op.id)}
              />
            ))
          )}
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// OPERATION CARD
// ─────────────────────────────────────────────────────────────────────────────
function OperationCard({
  op, chunks, onCancel, onToggleChunks, onExport, onPoll,
}: {
  op: OperationProgress;
  chunks?: ChunkItem[];
  onCancel: () => void;
  onToggleChunks: () => void;
  onExport: () => void;
  onPoll: () => void;
}) {
  const statusConfig: Record<string, {color: string; icon: string; label: string}> = {
    pending:   { color: 'bg-gray-500',   icon: '⏸️', label: 'في الانتظار' },
    planned:   { color: 'bg-blue-500',   icon: '📋', label: 'مخطط' },
    running:   { color: 'bg-yellow-500', icon: '⚡', label: 'جاري' },
    partial:   { color: 'bg-orange-500', icon: '⚡', label: 'جاري (جزئي)' },
    completed: { color: 'bg-green-500',  icon: '✅', label: 'مكتمل' },
    failed:    { color: 'bg-red-500',    icon: '❌', label: 'فشل' },
    cancelled: { color: 'bg-gray-400',   icon: '🚫', label: 'ملغى' },
  };
  const sc = statusConfig[op.status] || { color: 'bg-gray-500', icon: '❓', label: op.status };

  useEffect(() => {
    if (!op.is_terminal) onPoll();
  }, [op.id]);

  return (
    <Card className={op.is_terminal ? 'opacity-80' : ''}>
      <CardContent className="pt-4 space-y-3">

        {/* Header row */}
        <div className="flex items-start gap-2">
          <span className="text-xl">{sc.icon}</span>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-bold text-sm font-mono">{op.operation_ref}</span>
              <Badge variant="outline" className={`text-xs ${op.status === 'running' ? 'animate-pulse' : ''}`}>{sc.label}</Badge>
              <span className="text-xs text-muted-foreground bg-muted px-2 py-0.5 rounded-full">{op.capability_type}</span>
            </div>
            {op.cancel_requested && !op.is_terminal && (
              <div className="text-xs text-destructive mt-1 font-medium animate-pulse">
                ⏳ جاري إيقاف العملية وإلغاء الدفعات المتبقية...
              </div>
            )}
          </div>
        </div>

        {/* Progress bar */}
        <div className="space-y-1">
          <div className="flex justify-between text-xs text-muted-foreground font-medium">
            <span>{op.chunks_completed} / {op.chunks_total} دفعات</span>
            <span>{op.progress_pct}%</span>
          </div>
          <div className="w-full bg-muted rounded-full h-2 overflow-hidden border">
            <div
              className={`h-full transition-all duration-500 ${sc.color}`}
              style={{ width: `${Math.min(op.progress_pct, 100)}%` }}
            />
          </div>
        </div>

        {/* Stats row */}
        <div className="flex gap-4 text-xs font-medium text-muted-foreground bg-muted/30 p-2 rounded border">
          <span className="flex items-center gap-1">📦 {op.total_results_count.toLocaleString('ar')} نتيجة</span>
          <span className="flex items-center gap-1">💳 {op.actual_credits_used} / {op.estimated_credits} نقطة</span>
          {op.chunks_failed > 0 && (
            <span className="text-destructive flex items-center gap-1">❌ {op.chunks_failed} فشل</span>
          )}
        </div>

        {/* Current chunk indicator */}
        {op.current_chunk && !op.is_terminal && !op.cancel_requested && (
          <div className="text-xs bg-yellow-500/10 border border-yellow-500/20 rounded p-2 text-yellow-800 dark:text-yellow-200">
            <span className="animate-pulse mr-1">⏳</span> جاري الآن: <span className="font-mono" dir="ltr">{String((op.current_chunk as any).date_from || (op.current_chunk as any).entity_id || '—')}</span>
          </div>
        )}
        {op.last_completed_chunk && op.is_terminal && op.status === 'completed' && (
          <div className="text-xs bg-green-500/10 border border-green-500/20 rounded p-2 text-green-800 dark:text-green-200">
            ✅ اكتملت بنجاح: تم سحب <span className="font-bold">{((op.last_completed_chunk as any).results_count || 0).toLocaleString('ar')}</span> نتيجة في آخر دفعة.
          </div>
        )}

        {/* Chunks detail */}
        {chunks && (
          <div className="space-y-0.5 max-h-40 overflow-y-auto bg-background rounded border p-1">
            {chunks.map(c => (
              <div key={c.chunk_index}
                className="flex items-center justify-between text-xs py-1 px-2 border-b last:border-0 hover:bg-muted/50">
                <span className="flex items-center gap-2">
                  <span className="w-4">{c.status_icon}</span> 
                  <span className="font-mono" dir="ltr">{c.label}</span>
                </span>
                <div className="flex gap-3 text-muted-foreground">
                  {c.results_count > 0 && <span className="bg-primary/10 text-primary px-1.5 rounded">{c.results_count.toLocaleString('ar')}</span>}
                  {c.last_error && (
                    <span className="text-destructive truncate max-w-32 bg-destructive/10 px-1.5 rounded" title={c.last_error}>
                      {c.last_error}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Action buttons */}
        <div className="flex gap-2 flex-wrap pt-1">
          <Button variant="secondary" size="sm" className="text-xs h-7"
            onClick={onToggleChunks}>
            {chunks ? '🔼 إخفاء الدفعات' : '🔽 تفاصيل الدفعات'}
          </Button>

          {op.total_results_count > 0 && (
            <Button variant="default" size="sm" className="text-xs h-7 shadow-sm"
              onClick={onExport}>
              📥 تصدير البيانات (CSV)
            </Button>
          )}

          {op.can_be_cancelled && !op.cancel_requested && (
            <Button variant="destructive" size="sm" className="text-xs h-7 ml-auto"
              onClick={onCancel}>
              🛑 إيقاف قسري
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}