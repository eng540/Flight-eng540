/**
 * Header.tsx — v4.0 (TIER 4 Arabic + RTL)
 * FIX: All text translated to Arabic.
 * FIX: Icon margin flipped for RTL (mr-2 → ml-2).
 * Evidence: business requirement "ALL frontend must be in Arabic + RTL"
 */
import { Plane, RefreshCw, Activity } from 'lucide-react';
import { Button }  from '@/components/ui/button';
import { Badge }   from '@/components/ui/badge';
import { useHealthCheck } from '@/hooks/useStatistics';
import { toast } from 'sonner';

interface HeaderProps {
  onRefresh: () => void;
  loading?:  boolean;
}

export function Header({ onRefresh, loading }: HeaderProps) {
  const { healthy, loading: healthLoading } = useHealthCheck();

  const handleRefresh = () => {
    onRefresh();
    toast.info('جاري تحديث البيانات…');
  };

  return (
    <header className="border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="container mx-auto px-4 py-4">
        {/* RTL: justify-between keeps logo on right, actions on left */}
        <div className="flex items-center justify-between">

          {/* Logo — right side in RTL */}
          <div className="flex items-center gap-3">
            <div className="bg-primary p-2 rounded-lg">
              <Plane className="h-6 w-6 text-primary-foreground" />
            </div>
            <div>
              <h1 className="text-xl font-bold">منصة استخبارات الطيران</h1>
              <p className="text-xs text-muted-foreground">
                تتبع الرحلات الجوية لحظياً وتحليل البيانات
              </p>
            </div>
          </div>

          {/* Status & Actions — left side in RTL */}
          <div className="flex items-center gap-3">
            {!healthLoading && (
              <Badge
                variant={healthy ? 'default' : 'destructive'}
                className="hidden sm:flex items-center gap-1"
              >
                <Activity className="h-3 w-3" />
                {/* FIX: Arabic status text */}
                {healthy ? 'النظام متصل' : 'النظام غير متصل'}
              </Badge>
            )}

            <Button
              variant="outline"
              size="sm"
              onClick={handleRefresh}
              disabled={loading}
            >
              {/* FIX: ml-2 instead of mr-2 for RTL icon spacing */}
              <RefreshCw className={`h-4 w-4 ml-2 ${loading ? 'animate-spin' : ''}`} />
              تحديث
            </Button>
          </div>
        </div>
      </div>
    </header>
  );
}
