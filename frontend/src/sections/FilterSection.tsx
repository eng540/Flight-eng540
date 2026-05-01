import { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { 
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Filter, X } from 'lucide-react';
import { FlightFilterParams } from '@/types';
import { useAirlines } from '@/hooks/useAirlines';

interface FilterSectionProps {
  filters: FlightFilterParams;
  onFilterChange: (filters: FlightFilterParams) => void;
}

export function FilterSection({ filters, onFilterChange }: FilterSectionProps) {
  const { data: airlines, loading: airlinesLoading } = useAirlines(0, 100);
  const [localFilters, setLocalFilters] = useState<FlightFilterParams>(filters);

  const handleApplyFilters = () => {
    onFilterChange(localFilters);
  };

  const handleClearFilters = () => {
    const cleared: FlightFilterParams = { page: 1, page_size: 50 };
    setLocalFilters(cleared);
    onFilterChange(cleared);
  };

  const hasActiveFilters = 
    localFilters.airline_id || 
    localFilters.country || 
    localFilters.date_from || 
    localFilters.date_to ||
    localFilters.departure_airport ||
    localFilters.arrival_airport;

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-lg">
          <Filter className="h-5 w-5" />
          Filters
          {hasActiveFilters && (
            <Button 
              variant="ghost" 
              size="sm" 
              onClick={handleClearFilters}
              className="ml-auto"
            >
              <X className="h-4 w-4 mr-1" />
              Clear
            </Button>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
          {/* Airline Filter */}
          <div className="space-y-2">
            <Label htmlFor="airline">Airline</Label>
            <Select
              value={localFilters.airline_id?.toString() || 'all'}
              onValueChange={(value) => 
                setLocalFilters({ 
                  ...localFilters, 
                  airline_id: value === 'all' ? undefined : parseInt(value) 
                })
              }
            >
              <SelectTrigger id="airline">
                <SelectValue placeholder="Select airline" />
              </SelectTrigger>
              <SelectContent>
                {/* تم إصلاح الخطأ هنا: استبدال القيمة الفارغة "" بـ "all" */}
                <SelectItem value="all">All Airlines</SelectItem>
                {airlines.map((airline) => (
                  <SelectItem key={airline.id} value={airline.id.toString()}>
                    {airline.name || airline.icao24.toUpperCase()}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Country Filter */}
          <div className="space-y-2">
            <Label htmlFor="country">Country</Label>
            <Input
              id="country"
              placeholder="e.g., United States"
              value={localFilters.country || ''}
              onChange={(e) => 
                setLocalFilters({ 
                  ...localFilters, 
                  country: e.target.value || undefined 
                })
              }
            />
          </div>

          {/* Date From */}
          <div className="space-y-2">
            <Label htmlFor="date_from">From Date</Label>
            <Input
              id="date_from"
              type="date"
              value={localFilters.date_from || ''}
              onChange={(e) => 
                setLocalFilters({ 
                  ...localFilters, 
                  date_from: e.target.value || undefined 
                })
              }
            />
          </div>

          {/* Date To */}
          <div className="space-y-2">
            <Label htmlFor="date_to">To Date</Label>
            <Input
              id="date_to"
              type="date"
              value={localFilters.date_to || ''}
              onChange={(e) => 
                setLocalFilters({ 
                  ...localFilters, 
                  date_to: e.target.value || undefined 
                })
              }
            />
          </div>

          {/* Departure Airport */}
          <div className="space-y-2">
            <Label htmlFor="departure">Departure (ICAO)</Label>
            <Input
              id="departure"
              placeholder="e.g., KJFK"
              value={localFilters.departure_airport || ''}
              onChange={(e) => 
                setLocalFilters({ 
                  ...localFilters, 
                  departure_airport: e.target.value.toUpperCase() || undefined 
                })
              }
              maxLength={4}
            />
          </div>

          {/* Arrival Airport */}
          <div className="space-y-2">
            <Label htmlFor="arrival">Arrival (ICAO)</Label>
            <Input
              id="arrival"
              placeholder="e.g., EGLL"
              value={localFilters.arrival_airport || ''}
              onChange={(e) => 
                setLocalFilters({ 
                  ...localFilters, 
                  arrival_airport: e.target.value.toUpperCase() || undefined 
                })
              }
              maxLength={4}
            />
          </div>
        </div>

        {/* Apply Button */}
        <div className="mt-4 flex justify-end">
          <Button onClick={handleApplyFilters}>
            <Filter className="h-4 w-4 mr-2" />
            Apply Filters
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}