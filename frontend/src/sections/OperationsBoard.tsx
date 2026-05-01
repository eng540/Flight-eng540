/**
 * OperationsBoard.tsx — v1.1 (Operations Board UI)
 *
 * "قمرة القيادة" — translates complex FR24 capabilities into
 * a simple Arabic wizard: select → configure → review → launch → track.
 *
 * Two panels:
 *   LEFT:  New Operation Wizard (4 steps)
 *   RIGHT: Live Operations Tracker (card per operation)
 *
 * All text Arabic. Calls /api/v1/operations/* exclusively.
 * Polling: GET /api/v1/operations/{id}/progress every 3 seconds.
 * Evidence: system design §5 Execution Flow + §6 Partial Results
 *
 * FIXES APPLIED (2026-05-01):
 *   [FIX-HE-UI] Removed historic_events from capability cards until backend
 *               supports required params (flight_ids + event_types).
 *               Evidence: FR24 error "The flight ids field is required.,
 *               The event types field is required."
 *   [FIX-SA-UI] Added client-side validation for static_airline ICAO codes.
 *               ICAO must be 3 uppercase letters before preflight request.
 *               Evidence: FR24 error "The provided airline code 'SL'
 *               is not a valid airline ICAO code"
 *   [FIX-FS-UI] flight_summaries now shows an optional airline ICAO field.
 *               Allows user to specify airline when region airports are unavailable.
 *               Field is optional — if left empty, backend will try to use region airports.
 *               Evidence: ValueError "flight_summaries requires an additional filter"
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
const CAPABILITIES = [
  {
    id: 'live_positions',
    icon: '📡',
    title: 'رصد حي',
    desc: 'أين الطائرات الآن فوق منطقتي؟',
    timing: '⚡ فوري',
    needsDates: false, needsEntity: false,
  },
  {
    id: 'flight_summaries',
    icon: '📋',
    title: 'ملخصات الرحلات',
    desc: 'كل الرحلات في فترة زمنية محددة',
    timing: '📅 تاريخي',
    needsDates: true,
    // [FIX-FS-UI] Made entity optional for flight_summaries.
    // When provided, it passes airline_icao to FR24.
    // When empty, backend will try to use region airports.
    needsEntity: true,
    entityLabel: 'رمز الناقل ICAO (اختياري، مثال: UAE)',
    entityOptional: true,
  },
  {
    id: 'flight_tracks',
    icon: '🛤️',
    title: 'مسار رحلة',
    desc: 'أرسم المسار الكامل لرحلة بعينها',
    timing: '📅 تاريخي',
    needsDates: false, needsEntity: true, entityLabel: 'معرّف الرحلة (fr24_id)',
  },
  {
    id: 'historic_positions',
    icon: '🕐',
    title: 'مواقع تاريخية',
    desc: 'مواقع الطائرات في فترة ماضية',
    timing: '📅 تاريخي',
    needsDates: true, needsEntity: false,
  },
  // [FIX-HE-UI] historic_events removed from UI until backend supports required params
  {
    id: 'static_airport',
    icon: '🏢',
    title: 'بيانات مطار',
    desc: 'معلومات ثابتة عن مطار (اسم، إحداثيات، ارتفاع)',
    timing: '🆓 مجاني',
    needsDates: false, needsEntity: true, entityLabel: 'كود المطار ICAO',
  },
  {
    id: 'static_airline',
    icon: '✈️',
    title: 'بيانات ناقل',
    desc: 'معلومات ثابتة عن شركة طيران',
    timing: '🆓 مجاني',
    needsDates: false, needsEntity: true, entityLabel: 'كود الناقل ICAO',
  },
];

const REGIONS = [
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
  const [dateFrom,   setDateFrom]   = useState('');
  const [dateTo,     setDateTo]     = useState('');
  const [entityId,   setEntityId]   = useState('');

  const [preflight,  setPreflight]  = useState<PreflightSummary | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [launching,  setLaunching]  = useState(false);
  const [error,      setError]      = useState('');

  const [operations, setOperations] = useState<OperationProgress[]>([]);
  const [expandedChunks, setExpandedChunks] = useState<Record<number, ChunkItem[]>>({});

  const pollingRefs = useRef<Record<number, ReturnType<typeof setInterval>>>({});

  const capMeta = CAPABILITIES.find(c => c.id === capability);

  // ── Load operations list ────────────────────────────────────────────────
  const loadOperations = useCallback(async () => {
    try {
      const res = await apiClient.get('/api/v1/operations?page_size=20');
      const ops: OperationProgress[] = (res.data.data || []).map((op: any) => ({
        ...op,
        is_terminal:      ['completed','failed','cancelled'].includes(op.status),
        can_be_cancelled: ['planned','running','partial'].includes(op.status),
      }));
      setOperations(ops);
    } catch { /* silent */ }
  }, []);

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
          is_terminal:      ['completed','failed','cancelled'].includes(res.data.status),
          can_be_cancelled: ['planned','running','partial'].includes(res.data.status),
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
  }, []);

  // ── Step 2 → 3: Submit for pre-flight ──────────────────────────────────
  const submitForPreflight = async () => {
    setSubmitting(true);
    setError('');

    // [FIX-SA-UI] Validate static_airline ICAO code before submission
    if (capability === 'static_airline' && entityId) {
      const icao = entityId.trim().toUpperCase();
      if (icao.length !== 3 || !/^[A-Z]{3}$/.test(icao)) {
        setError('رمز ICAO يجب أن يكون 3 أحرف (مثال: UAE، SVA)');
        setSubmitting(false);
        return;
      }
    }

    // [FIX-FS-UI] Validate flight_summaries airline ICAO if provided
    if (capability === 'flight_summaries' && entityId) {
      const icao = entityId.trim().toUpperCase();
      if (icao.length > 0 && (icao.length !== 3 || !/^[A-Z]{3}$/.test(icao))) {
        setError('رمز ICAO يجب أن يكون 3 أحرف (مثال: UAE، SVA) أو يُترك فارغاً');
        setSubmitting(false);
        return;
      }
    }

    try {
      const scope: Record<string, unknown> = { region_key: regionKey };
      if (capMeta?.needsDates && dateFrom) scope.date_from = dateFrom;
      if (capMeta?.needsDates && dateTo)   scope.date_to   = dateTo;
      if (capMeta?.needsEntity && entityId) scope.entity_id = entityId.trim().toUpperCase();

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
      }, 3000);
    } catch (e: any) {
      setError(e.response?.data?.detail || 'فشل إطلاق العملية');
    }
    setLaunching(false);
  };

  // ── Cancel operation ────────────────────────────────────────────────────
  const cancelOperation = async (opId: number) => {
    try {
      await apiClient.post(`/api/v1/operations/${opId}/cancel`, { reason: 'طلب المستخدم' });
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
      setExpandedChunks(prev => ({ ...prev, [opId]: res.data.data || [] }));
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

                  {/* Region */}
                  {!capMeta.needsEntity && (
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
                  {capMeta.needsEntity && (
                    <div className="space-y-1">
                      <Label className="text-xs">{capMeta.entityLabel}</Label>
                      <Input placeholder="أدخل المعرّف..."
                        value={entityId}
                        onChange={e => setEntityId(e.target.value)} />
                      {/* [FIX-FS-UI] Show optional hint for flight_summaries */}
                      {(capability === 'flight_summaries') && (
                        <p className="text-xs text-muted-foreground">
                          يمكنك تركه فارغاً لاستخدام مطارات المنطقة تلقائياً
                        </p>
                      )}
                    </div>
                  )}

                  {/* [FIX-FS-UI] Region selector also shown for flight_summaries */}
                  {(capability === 'flight_summaries') && (
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

                  {error && (
                    <p className="text-xs text-destructive">{error}</p>
                  )}

                  <Button onClick={submitForPreflight}
                    disabled={submitting || (capMeta.needsEntity && !(capMeta as any).entityOptional && !entityId)}
                    className="w-full">
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
                      {[
                        ['🔢 مكالمات API', `${preflight.estimated_api_calls}`],
                        ['💳 التكلفة', `~${preflight.estimated_credits.toLocaleString('ar')} نقطة`],
                        ['⏱️ الوقت', preflight.estimated_duration_label],
                        ['📦 النتائج', `~${preflight.estimated_results.toLocaleString('ar')}`],
                      ].map(([label, value]) => (
                        <div key={label} className="bg-background rounded p-2">
                          <div className="text-xs text-muted-foreground">{label}</div>
                          <div className="font-bold text-sm">{value}</div>
                        </div>
                      ))}
                    </div>

                    {/* Chunk plan preview */}
                    <div className="space-y-1 pt-1">
                      <div className="text-xs font-medium">خطة التنفيذ:</div>
                      <div className="max-h-32 overflow-y-auto space-y-0.5">
                        {preflight.chunk_plan.slice(0, 5).map(c => (
                          <div key={c.chunk_index}
                            className="flex justify-between text-xs text-muted-foreground">
                            <span>⏸️ {c.label}</span>
                            <span>{c.estimated_credits} نقطة</span>
                          </div>
                        ))}
                        {preflight.chunk_plan.length > 5 && (
                          <div className="text-xs text-muted-foreground">
                            + {preflight.chunk_plan.length - 5} مزيد…
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Warnings */}
                    {preflight.warnings.map((w, i) => (
                      <div key={i} className={`text-xs p-2 rounded ${
                        w.level === 'critical' ? 'bg-destructive/10 text-destructive' :
                        w.level === 'warning'  ? 'bg-yellow-500/10 text-yellow-700' :
                        'bg-blue-500/10 text-blue-700'
                      }`}>
                        {w.level === 'critical' ? '⚠️' :
                         w.level === 'warning'  ? '⚠' : 'ℹ️'} {w.message}
                      </div>
                    ))}
                  </div>

                  {error && <p className="text-xs text-destructive">{error}</p>}

                  <div className="flex gap-2">
                    <Button variant="outline" onClick={() => setStep(2)} className="flex-1">
                      ← تعديل
                    </Button>
                    <Button onClick={launchOperation} disabled={launching} className="flex-1">
                      {launching ? '⏳ جاري الإطلاق…' : '🚀 إطلاق'}
                    </Button>
                  </div>
                </div>
              )}

              {/* ── STEP 4: Launched confirmation ─── */}
              {step === 4 && (
                <div className="text-center py-8 space-y-2">
                  <div className="text-4xl">🚀</div>
                  <div className="font-bold">تم إطلاق العملية!</div>
                  <div className="text-xs text-muted-foreground">
                    تابع التقدم في لوحة المهمات →
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
            <Button variant="ghost" size="sm" onClick={loadOperations}>🔄</Button>
          </div>

          {operations.length === 0 ? (
            <div className="text-center py-16 text-muted-foreground">
              <div className="text-4xl mb-2">📭</div>
              <p className="text-sm">لا توجد عمليات بعد</p>
              <p className="text-xs">أنشئ عملية جديدة من القائمة على اليمين</p>
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
              <span className="font-bold text-sm">{op.operation_ref}</span>
              <Badge variant="outline" className="text-xs">{sc.label}</Badge>
              <span className="text-xs text-muted-foreground">{op.capability_type}</span>
            </div>
          </div>
        </div>

        {/* Progress bar */}
        <div className="space-y-1">
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>{op.chunks_completed} / {op.chunks_total} chunks</span>
            <span>{op.progress_pct}%</span>
          </div>
          <div className="w-full bg-muted rounded-full h-2">
            <div
              className={`h-2 rounded-full transition-all ${sc.color}`}
              style={{ width: `${Math.min(op.progress_pct, 100)}%` }}
            />
          </div>
        </div>

        {/* Stats row */}
        <div className="flex gap-4 text-xs text-muted-foreground">
          <span>📦 {op.total_results_count.toLocaleString('ar')} نتيجة</span>
          <span>💳 {op.actual_credits_used} / {op.estimated_credits} نقطة</span>
          {op.chunks_failed > 0 && (
            <span className="text-destructive">❌ {op.chunks_failed} فشل</span>
          )}
        </div>

        {/* Current chunk indicator */}
        {op.current_chunk && !op.is_terminal && (
          <div className="text-xs bg-yellow-500/10 rounded p-2">
            ⏳ جاري الآن: {String((op.current_chunk as any).date_from || (op.current_chunk as any).entity_id || '—')}
          </div>
        )}
        {op.last_completed_chunk && (
          <div className="text-xs bg-green-500/10 rounded p-2">
            ✅ آخر مكتمل: {String((op.last_completed_chunk as any).date_from || '—')}
            {' · '}{((op.last_completed_chunk as any).results_count || 0).toLocaleString('ar')} نتيجة
          </div>
        )}

        {/* Chunks detail */}
        {chunks && (
          <div className="space-y-0.5 max-h-40 overflow-y-auto">
            {chunks.map(c => (
              <div key={c.chunk_index}
                className="flex items-center justify-between text-xs py-0.5">
                <span>{c.status_icon} {c.label}</span>
                <div className="flex gap-3 text-muted-foreground">
                  {c.results_count > 0 && <span>{c.results_count.toLocaleString('ar')}</span>}
                  {c.last_error && (
                    <span className="text-destructive truncate max-w-24" title={c.last_error}>
                      خطأ
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Action buttons */}
        <div className="flex gap-1.5 flex-wrap">
          <Button variant="outline" size="sm" className="text-xs h-7"
            onClick={onToggleChunks}>
            {chunks ? '🔼 إخفاء' : '🔽 تفاصيل'}
          </Button>

          {op.total_results_count > 0 && (
            <Button variant="outline" size="sm" className="text-xs h-7"
              onClick={onExport}>
              📥 تصدير CSV
            </Button>
          )}

          {op.can_be_cancelled && (
            <Button variant="outline" size="sm" className="text-xs h-7 text-destructive"
              onClick={onCancel}>
              🛑 إلغاء
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}