/**
 * App.tsx — v4.0 (TIER 4 Arabic + RTL)
 *
 * FIX: All tab labels translated to Arabic.
 * Evidence: business requirement "ALL frontend must be in Arabic"
 *
 * FIX: Footer "OpenSky Network" → "Flightradar24 API"
 * Evidence: data source changed to FR24; OpenSky no longer used.
 *
 * NEW: Added "تاريخية" (History) + "بحث" (Search) tabs.
 * Evidence: business requirement — Historical Engine UI + Search System.
 *
 * NEW: Added "اعتمادات" (Credits) tab for API budget monitoring.
 * Evidence: business requirement GET /api/v1/system/credits-usage
 */
import { useState } from 'react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
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
        <Tabs defaultValue="dashboard" className="space-y-6">
          {/*
            FIX: TabsList grid updated to 7 columns for new tabs.
            All labels in Arabic — business requirement "Arabic labels ONLY".
          */}
          <TabsList className="grid w-full grid-cols-4 sm:grid-cols-4 lg:grid-cols-8 gap-1">
            <TabsTrigger value="dashboard">📊 لوحة البيانات</TabsTrigger>
            <TabsTrigger value="map">🗺️ الخريطة الحية</TabsTrigger>
            <TabsTrigger value="analytics">📈 التحليلات</TabsTrigger>
            <TabsTrigger value="search">🔍 البحث</TabsTrigger>
            <TabsTrigger value="history">🕐 التاريخية</TabsTrigger>
            <TabsTrigger value="operations">⚡ لوحة العمليات</TabsTrigger>
            <TabsTrigger value="ingestion">📥 الاستيعاب</TabsTrigger>
            <TabsTrigger value="credits">💳 الاعتمادات</TabsTrigger>
          </TabsList>

          {/* ── لوحة البيانات ── */}
          <TabsContent value="dashboard" className="space-y-6">
            <StatsCards stats={stats} loading={statsLoading} />
            <ChartsSection stats={stats} loading={statsLoading} />
            <FilterSection filters={filters} onFilterChange={handleFilterChange} />
            <FlightsTable
              data={flightsData}
              loading={flightsLoading}
              filters={filters}
              onFilterChange={handleFilterChange}
              onPageChange={handlePageChange}
            />
          </TabsContent>

          {/* ── الخريطة الحية ── */}
          <TabsContent value="map">
            <MapSection />
          </TabsContent>

          {/* ── التحليلات ── */}
          <TabsContent value="analytics">
            <AnalyticsSection />
          </TabsContent>

          {/* ── البحث ── */}
          <TabsContent value="search">
            <SearchSection />
          </TabsContent>

          {/* ── التاريخية ── */}
          <TabsContent value="history">
            <HistorySection />
          </TabsContent>

          {/* ── لوحة العمليات ── */}
          <TabsContent value="operations">
            <OperationsBoard />
          </TabsContent>

          {/* ── الاستيعاب ── */}
          <TabsContent value="ingestion">
            <IngestionSection />
          </TabsContent>

          {/* ── الاعتمادات ── */}
          <TabsContent value="credits">
            <CreditsSection />
          </TabsContent>
        </Tabs>
      </main>

      {/*
        FIX: Footer updated — "OpenSky Network" → "Flightradar24 API"
        Evidence: data source changed in TIER 1; footer was misleading users.
        All text Arabic per business requirement.
      */}
      <footer className="border-t mt-12 py-6">
        <div className="container mx-auto px-4 text-center text-sm text-muted-foreground">
          <p>منصة استخبارات الطيران &copy; {new Date().getFullYear()}</p>
          <p className="mt-1">
            البيانات: <a href="https://fr24api.flightradar24.com" target="_blank"
              rel="noreferrer" className="underline">Flightradar24 API</a>
            {' · '}المناطق: الشرق الأوسط · شمال أفريقيا · آسيا الوسطى · شرق أفريقيا · جنوب آسيا
          </p>
        </div>
      </footer>
    </div>
  );
}

/**
 * CreditsSection — inline component for API budget monitoring.
 * Calls GET /api/v1/system/credits-usage
 * Evidence: business requirement "GET /api/v1/system/credits-usage"
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
      <div className="flex flex-col items-center gap-4 py-16">
        <p className="text-muted-foreground">اضغط لتحميل بيانات استهلاك API</p>
        <button onClick={load} disabled={loading}
          className="px-6 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium">
          {loading ? 'جاري التحميل…' : '💳 تحميل الاعتمادات'}
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold">استهلاك اعتمادات Flightradar24 API</h2>
        <span className="text-2xl font-bold text-primary">{data?.total_credits?.toLocaleString('ar')} نقطة</span>
      </div>
      <div className="rounded-lg border overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-muted">
            <tr>
              <th className="p-3 text-right">نوع الطلب</th>
              <th className="p-3 text-right">عدد الطلبات</th>
              <th className="p-3 text-right">الاعتمادات المستهلكة</th>
            </tr>
          </thead>
          <tbody>
            {(data?.data || []).map((row, i) => (
              <tr key={i} className="border-t">
                <td className="p-3 font-mono">{row.endpoint}</td>
                <td className="p-3">{row.request_count.toLocaleString('ar')}</td>
                <td className="p-3 font-bold">{row.credits.toLocaleString('ar')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default App;
