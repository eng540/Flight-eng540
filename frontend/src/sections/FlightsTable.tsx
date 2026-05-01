import { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { 
  Table, 
  TableBody, 
  TableCell, 
  TableHead, 
  TableHeader, 
  TableRow 
} from '@/components/ui/table';
import { 
  ChevronLeft, 
  ChevronRight, 
  Plane, 
  Download,
  Search,
  Filter,
  Calendar,
  MapPin
} from 'lucide-react';
import { FlightListResponse, FlightFilterParams } from '@/types';
import { flightsApi } from '@/api/client';
import { toast } from 'sonner';

interface FlightsTableProps {
  data: FlightListResponse | null;
  loading: boolean;
  filters: FlightFilterParams;
  onFilterChange: (filters: FlightFilterParams) => void;
  onPageChange: (page: number) => void;
}

export function FlightsTable({ 
  data, 
  loading, 
  filters, 
  onFilterChange, 
  onPageChange 
}: FlightsTableProps) {
  const [searchTerm, setSearchTerm] = useState('');
  const [exporting, setExporting] = useState(false);

  const handleExport = async () => {
    try {
      setExporting(true);
      const blob = await flightsApi.exportFlights(filters);
      
      // Create download link
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `flights_export_${new Date().toISOString().split('T')[0]}.xlsx`);
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
      
      toast.success('Flights exported successfully');
    } catch (error) {
      toast.error('Failed to export flights');
      console.error('Export error:', error);
    } finally {
      setExporting(false);
    }
  };

  const handleSearch = () => {
    onFilterChange({ ...filters, callsign: searchTerm || undefined });
  };

  const formatTimestamp = (timestamp: number | null): string => {
    if (!timestamp) return '-';
    return new Date(timestamp * 1000).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const formatDuration = (seconds: number | null): string => {
    if (!seconds) return '-';
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    return `${hours}h ${minutes}m`;
  };

  if (loading) {
    return (
      <Card>
        <CardHeader>
          <div className="h-6 w-48 bg-muted rounded animate-pulse"></div>
        </CardHeader>
        <CardContent>
          <div className="h-96 bg-muted rounded animate-pulse"></div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <CardTitle className="flex items-center gap-2">
            <Plane className="h-5 w-5" />
            Flights
            {data && (
              <Badge variant="secondary">
                {data.total.toLocaleString()} total
              </Badge>
            )}
          </CardTitle>
          
          <div className="flex flex-col sm:flex-row gap-2">
            {/* Search */}
            <div className="flex gap-2">
              <Input
                placeholder="Search callsign..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                className="w-48"
              />
              <Button variant="outline" size="icon" onClick={handleSearch}>
                <Search className="h-4 w-4" />
              </Button>
            </div>
            
            {/* Export Button */}
            <Button 
              variant="outline" 
              onClick={handleExport}
              disabled={exporting || !data?.data.length}
            >
              <Download className="h-4 w-4 mr-2" />
              {exporting ? 'Exporting...' : 'Export'}
            </Button>
          </div>
        </div>
      </CardHeader>
      
      <CardContent>
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Callsign</TableHead>
                <TableHead>ICAO24</TableHead>
                <TableHead>Origin</TableHead>
                <TableHead>From</TableHead>
                <TableHead>To</TableHead>
                <TableHead>First Seen</TableHead>
                <TableHead>Duration</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data?.data.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} className="text-center py-8 text-muted-foreground">
                    No flights found
                  </TableCell>
                </TableRow>
              ) : (
                data?.data.map((flight) => (
                  <TableRow key={flight.id}>
                    <TableCell>
                      <Badge variant="outline" className="font-mono">
                        {flight.callsign || 'N/A'}
                      </Badge>
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {flight.icao24.toUpperCase()}
                    </TableCell>
                    <TableCell>{flight.origin_country || 'Unknown'}</TableCell>
                    <TableCell>
                      {flight.est_departure_airport ? (
                        <Badge variant="secondary" className="font-mono">
                          <MapPin className="h-3 w-3 mr-1" />
                          {flight.est_departure_airport}
                        </Badge>
                      ) : (
                        '-'
                      )}
                    </TableCell>
                    <TableCell>
                      {flight.est_arrival_airport ? (
                        <Badge variant="secondary" className="font-mono">
                          <MapPin className="h-3 w-3 mr-1" />
                          {flight.est_arrival_airport}
                        </Badge>
                      ) : (
                        '-'
                      )}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1 text-sm">
                        <Calendar className="h-3 w-3" />
                        {formatTimestamp(flight.first_seen)}
                      </div>
                    </TableCell>
                    <TableCell>
                      {formatDuration(flight.duration_seconds)}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>

        {/* Pagination */}
        {data && data.pages > 1 && (
          <div className="flex items-center justify-between mt-4">
            <div className="text-sm text-muted-foreground">
              Page {data.page} of {data.pages}
            </div>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => onPageChange(data.page - 1)}
                disabled={data.page <= 1}
              >
                <ChevronLeft className="h-4 w-4 mr-1" />
                Previous
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => onPageChange(data.page + 1)}
                disabled={data.page >= data.pages}
              >
                Next
                <ChevronRight className="h-4 w-4 ml-1" />
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
