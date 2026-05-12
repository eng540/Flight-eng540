/**
 * App.tsx — v5.0 (Enterprise UX Overhaul)
 *
 * CHANGES:
 * - Consolidated 8 fragmented tabs into 4 Professional Command Centers.
 * - Improved visual hierarchy and layout grouping.
 * - Maintained full RTL and Arabic localization.
 */
import { useState } from 'react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Card, CardContent } from '@/components/ui/card';
import { Toaster } from '@/components/ui/sonner';
import { Header }         from '@/sections/Header';
import { StatsCards }     from '@/sections/StatsCards';
import { ChartsSection }  from '@/sections/ChartsSection';
import { FlightsTable }   from '@/sections/FlightsTable';
import { FilterSection }  from '@/sections/FilterSection';
import { AnalyticsSection } from '@/sections/AnalyticsSection';
import { MapSection }     from '@/sections/MapSection';
import { IngestionSection } from '@/sections/IngestionSection';
import { HistorySection }     from '@/sections/HistorySection';
import { SearchSection }      from '@/sections/SearchSection';
import { OperationsBoard }    from '@/sections/OperationsBoard';
import { useStatistics }   from '@/hooks/useStatistics';
import { useFilteredFlights } from '@/hooks/useFlights';
import { FlightFilterParams } from '@/types';
import './App.css';

function App() {
  const [filters, setFilters] = useState<FlightFilterParams>({ page: 1, page_size: 50 });

  const { data: stats, loading: statsLoading, refetch: refetchStats } = useStatistics();
  const { data: flightsData, loading: flightsLoading, refetch: refetchFlights } =
    useFilteredFlights(filters);

  const handleRefresh  = () => { refetchStats(); refetchFlights(); };
  const handleFilterChange = (f: FlightFilterParams) => setFilters({ ...f, page: 1 });
  const handlePageChange   = (page: number) => setFilters(prev => ({ ...prev, page }));

  return (
    <div className="min-h-screen bg-background" dir="rtl">
      <Toaster position="top-left" richColors />

      <Header onRefresh={handleRefresh} loading={statsLoading || flightsLoading} />

      <main className="container mx-auto px-4 py-6">
        <Tabs defaultValue="live" className="space-y-8">
          
          {/* ── Enterprise Command Centers Navigation ── */}
          <div className="flex justify-center mb-8">
            <TabsList className="grid w-full max-w-3xl grid-cols-2 lg:grid-cols-4 gap-1 h-auto p-1">
              <TabsTrigger value="live" className="py-2.5 text-sm md:text-base">📡 المركز اللحظي</TabsTrigger>
              <TabsTrigger value="intelligence" className="py-2.5 text-sm md:text-base">📈 مركز الاستخبارات</TabsTrigger>
              <TabsTrigger value="explorer" className="py-2.5 text-sm md:text-base">🔍 مستكشف البيانات</TabsTrigger>
              <TabsTrigger value="system" className="py-2.5 text-sm md:text-base">⚙️ إدارة النظام</TabsTrigger>
            </TabsList>
          </div>

          {/* ══════════════════════════════════════════════════════════════════════
              1. المركز اللحظي (LIVE COMMAND CENTER)
          ══════════════════════════════════════════════════════════════════════ */}
          <TabsContent value="live" className="space-y-6 animate-in fade-in duration-500">
            <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
              {/* Map takes up 2/3 of the width on large screens */}
              <div className="xl:col-span-2">
                <MapSection />
              </div>
              {/* Quick stats take up 1/3 */}
              <div className="space-y-6">
                <StatsCards stats={stats} loading={statsLoading} />
                <ChartsSection stats={stats} loading={statsLoading} />
              </div>
            </div>
            
            <div className="pt-4 border-t">
              <h3 className="text-lg font-bold mb-4">جدول الرحلات النشطة</h3>
              <FilterSection filters={filters} onFilterChange={handleFilterChange} />
              <div className="mt-4">
                <FlightsTable
                  data={flightsData}
                  loading={flightsLoading}
                  filters={filters}
                  onFilterChange={handleFilterChange}
                  onPageChange={handlePageChange}
                />
              </div>
            </div>
          </TabsContent>

          {/* ══════════════════════════════════════════════════════════════════════
              2. مركز الاستخبارات والتحليلات (INTELLIGENCE & ANALYTICS)
          ══════════════════════════════════════════════════════════════════════ */}
          <TabsContent value="intelligence" className="space-y-12 animate-in fade-in duration-500">
            <section>
              <div className="mb-6">
                <h2 className="text-2xl font-bold tracking-tight text-primary">التحليلات الشاملة</h2>
                <p className="text-muted-foreground">نظرة عامة على أداء الطيران، المطارات، والمسارات الجوية.</p>
              </div>
              <AnalyticsSection />
            </section>

            <section className="pt-8 border-t">
              <div className="mb-6">
                <h2 className="text-2xl font-bold tracking-tight text-primary">محرك البيانات التاريخية</h2>
                <p className="text-muted-foreground">استعلام مفصل عن كيانات محددة (طائرة، مطار، شركة طيران) واستخراج تقارير مخصصة.</p>
              </div>
              <HistorySection />
            </section>
          </TabsContent>

          {/* ══════════════════════════════════════════════════════════════════════
              3. مستكشف البيانات (DATA EXPLORER)
          ══════════════════════════════════════════════════════════════════════ */}
          <TabsContent value="explorer" className="animate-in fade-in duration-500">
            <div className="mb-6">
              <h2 className="text-2xl font-bold tracking-tight text-primary">مستكشف الرحلات</h2>
              <p className="text-muted-foreground">بحث متقدم متعدد الحقول في قاعدة البيانات التاريخية واللحظية.</p>
            </div>
            <SearchSection />
          </TabsContent>

          {/* ══════════════════════════════════════════════════════════════════════
              4. إدارة النظام (SYSTEM OPERATIONS)
          ══════════════════════════════════════════════════════════════════════ */}
          <TabsContent value="system" className="space-y-8 animate-in fade-in duration-500">
            <div className="mb-2">
              <h2 className="text-2xl font-bold tracking-tight text-primary">لوحة تحكم النظام</h2>
              <p className="text-muted-foreground">إدارة عمليات جلب البيانات، مراقبة الاستهلاك، وحالة الخوادم.</p>
            </div>
            
            <OperationsBoard />
            
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 pt-6 border-t">
              <IngestionSection />
              <div className="space-y-6">
                <Card className="border-primary/20 shadow-sm">
                  <CardContent className="pt-6">
                    <CreditsSection />
                  </CardContent>
                </Card>
              </div>
            </div>
          </TabsContent>

        </Tabs>
      </main>

      <footer className="border-t mt-12 py-6 bg-muted/20">
        <div className="container mx-auto px-4 text-center text-sm text-muted-foreground">
          <p>منصة استخبارات الطيران &copy; {new Date().getFullYear()}</p>
          <p className="mt-1">
            البيانات: <a href="https://fr24api.flightradar24.com" target="_blank"
              rel="noreferrer" className="underline hover:text-primary">Flightradar24 API</a>
            {' · '}المناطق: الشرق الأوسط · شمال أفريقيا · آسيا الوسطى · شرق أفريقيا · جنوب آسيا
          </p>
        </div>
      </footer>
    </div>
  );
}

/**
 * CreditsSection — inline component for API budget monitoring.
 */
function CreditsSection() {
  const [data, setData]     = useState<{ data: Array<{ endpoint: string; request_count: number; credits: number }>; total_credits: number } | null>(null);
  const [loading, setLoading] = useState(false);
  const [loaded,  setLoaded]  = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const { systemApi } = await import('@/api/client');
      const result = await systemApi.getCreditsUsage();
      setData(result);
      setLoaded(true);
    } catch { /* silent */ }
    setLoading(false);
  };

  if (!loaded) {
    return (
      <div className="flex flex-col items-center gap-4 py-12">
        <div className="text-4xl">💳</div>
        <p className="text-muted-foreground font-medium">مراقبة استهلاك Flightradar24 API</p>
        <button onClick={load} disabled={loading}
          className="px-6 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors">
          {loading ? 'جاري التحميل…' : 'تحميل بيانات الاعتمادات'}
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between border-b pb-4">
        <h2 className="text-lg font-bold flex items-center gap-2">
          <span>💳</span> استهلاك الاعتمادات
        </h2>
        <span className="text-2xl font-bold text-primary bg-primary/10 px-3 py-1 rounded-lg">
          {data?.total_credits?.toLocaleString('ar')} <span className="text-sm font-normal">نقطة</span>
        </span>
      </div>
      <div className="rounded-lg border overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-muted/50">
            <tr>
              <th className="p-3 text-right font-medium">نوع الطلب (Endpoint)</th>
              <th className="p-3 text-center font-medium">عدد الطلبات</th>
              <th className="p-3 text-left font-medium">الاستهلاك</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {(data?.data || []).map((row, i) => (
              <tr key={i} className="hover:bg-muted/30 transition-colors">
                <td className="p-3 font-mono text-xs text-muted-foreground" dir="ltr">{row.endpoint}</td>
                <td className="p-3 text-center font-medium">{row.request_count.toLocaleString('ar')}</td>
                <td className="p-3 text-left font-bold text-primary">{row.credits.toLocaleString('ar')}</td>
              </tr>
            ))}
            {(!data?.data || data.data.length === 0) && (
              <tr>
                <td colSpan={3} className="p-6 text-center text-muted-foreground">لا يوجد استهلاك مسجل حتى الآن</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="flex justify-end pt-2">
        <button onClick={load} disabled={loading} className="text-xs text-muted-foreground hover:text-primary flex items-center gap-1">
          <span>🔄</span> تحديث البيانات
        </button>
      </div>
    </div>
  );
}

export default App;