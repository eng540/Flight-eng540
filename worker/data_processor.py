"""Data processor for cleaning and transforming OpenSky flight data."""
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
import hashlib

logger = logging.getLogger(__name__)


class FlightDataProcessor:
    """Processor for cleaning and transforming flight data."""
    
    @staticmethod
    def clean_callsign(callsign: Optional[str]) -> Optional[str]:
        """Clean and normalize callsign.
        
        Args:
            callsign: Raw callsign string
            
        Returns:
            Cleaned callsign or None
        """
        if not callsign:
            return None
        
        # Remove whitespace and convert to uppercase
        cleaned = callsign.strip().upper()
        
        # Remove empty strings
        if not cleaned:
            return None
        
        return cleaned
    
    @staticmethod
    def clean_icao24(icao24: Optional[str]) -> Optional[str]:
        """Clean and normalize ICAO 24-bit address.
        
        Args:
            icao24: Raw ICAO24 string
            
        Returns:
            Cleaned ICAO24 (lowercase) or None
        """
        if not icao24:
            return None
        
        # Remove whitespace and convert to lowercase
        cleaned = icao24.strip().lower()
        
        # Validate length (should be 6 hex characters)
        if len(cleaned) != 6:
            logger.warning(f"Invalid ICAO24 length: {cleaned}")
            return cleaned[:6] if len(cleaned) > 6 else cleaned.zfill(6)
        
        return cleaned
    
    @staticmethod
    def clean_airport_code(code: Optional[str]) -> Optional[str]:
        """Clean and normalize airport ICAO code.
        
        Args:
            code: Raw airport code
            
        Returns:
            Cleaned airport code (uppercase) or None
        """
        if not code:
            return None
        
        cleaned = code.strip().upper()
        
        # ICAO codes should be 4 characters
        if len(cleaned) != 4:
            logger.warning(f"Invalid airport code length: {cleaned}")
        
        return cleaned if cleaned else None
    
    @staticmethod
    def clean_country(country: Optional[str]) -> Optional[str]:
        """Clean and normalize country name.
        
        Args:
            country: Raw country name
            
        Returns:
            Cleaned country name or None
        """
        if not country:
            return None
        
        cleaned = country.strip()
        
        # Title case for country names
        return cleaned.title() if cleaned else None
    
    @staticmethod
    def generate_unique_flight_id(flight_data: Dict[str, Any]) -> str:
        """Generate unique identifier for a flight.
        
        Creates a unique ID based on ICAO24, callsign, and timestamps
        to prevent duplicate entries.
        
        Args:
            flight_data: Flight data dictionary
            
        Returns:
            Unique flight identifier string
        """
        icao24 = flight_data.get("icao24", "")
        callsign = flight_data.get("callsign", "")
        first_seen = flight_data.get("firstSeen", "")
        last_seen = flight_data.get("lastSeen", "")
        
        # Create unique string
        unique_string = f"{icao24}_{callsign}_{first_seen}_{last_seen}"
        
        # Generate hash
        return hashlib.md5(unique_string.encode()).hexdigest()
    
    @staticmethod
    def process_flight(flight_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Process and clean a single flight record.
        
        Args:
            flight_data: Raw flight data from OpenSky API
            
        Returns:
            Cleaned flight data or None if invalid
        """
        try:
            # Extract ICAO24 (required field)
            icao24 = FlightDataProcessor.clean_icao24(flight_data.get("icao24"))
            if not icao24:
                logger.warning("Skipping flight with missing ICAO24")
                return None
            
            # Clean other fields
            callsign = FlightDataProcessor.clean_callsign(flight_data.get("callsign"))
            origin_country = FlightDataProcessor.clean_country(flight_data.get("origin_country"))
            
            # Generate unique ID
            unique_flight_id = FlightDataProcessor.generate_unique_flight_id(flight_data)
            
            # Build processed flight data
            processed = {
                "icao24": icao24,
                "callsign": callsign,
                "origin_country": origin_country,
                "first_seen": flight_data.get("firstSeen"),
                "last_seen": flight_data.get("lastSeen"),
                "est_departure_airport": FlightDataProcessor.clean_airport_code(
                    flight_data.get("estDepartureAirport")
                ),
                "est_departure_airport_horiz_distance": flight_data.get("estDepartureAirportHorizDistance"),
                "est_departure_airport_vert_distance": flight_data.get("estDepartureAirportVertDistance"),
                "est_arrival_airport": FlightDataProcessor.clean_airport_code(
                    flight_data.get("estArrivalAirport")
                ),
                "est_arrival_airport_horiz_distance": flight_data.get("estArrivalAirportHorizDistance"),
                "est_arrival_airport_vert_distance": flight_data.get("estArrivalAirportVertDistance"),
                "est_departure_time": flight_data.get("estDepartureTime"),
                "est_arrival_time": flight_data.get("estArrivalTime"),
                "unique_flight_id": unique_flight_id,
            }
            
            return processed
            
        except Exception as e:
            logger.error(f"Error processing flight data: {e}")
            return None
    
    @staticmethod
    def process_flights(flights_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process multiple flight records.
        
        Args:
            flights_data: List of raw flight data from OpenSky API
            
        Returns:
            List of cleaned flight data
        """
        processed = []
        
        for flight_data in flights_data:
            cleaned = FlightDataProcessor.process_flight(flight_data)
            if cleaned:
                processed.append(cleaned)
        
        logger.info(f"Processed {len(processed)} valid flights out of {len(flights_data)} total")
        return processed
    
    @staticmethod
    def extract_airline_info(flight_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extract airline information from flight data.
        
        Args:
            flight_data: Processed flight data
            
        Returns:
            Airline information dictionary or None
        """
        icao24 = flight_data.get("icao24")
        if not icao24:
            return None
        
        # Extract callsign prefix (first 3 characters of callsign)
        callsign = flight_data.get("callsign", "")
        callsign_prefix = callsign[:3] if callsign else None
        
        return {
            "icao24": icao24,
            "callsign_prefix": callsign_prefix,
            "country_name": flight_data.get("origin_country")
        }
    
    @staticmethod
    def remove_duplicates(flights: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove duplicate flights based on unique_flight_id.
        
        Args:
            flights: List of flight data
            
        Returns:
            List of unique flights
        """
        seen_ids = set()
        unique_flights = []
        
        for flight in flights:
            unique_id = flight.get("unique_flight_id")
            if unique_id and unique_id not in seen_ids:
                seen_ids.add(unique_id)
                unique_flights.append(flight)
        
        duplicates_removed = len(flights) - len(unique_flights)
        if duplicates_removed > 0:
            logger.info(f"Removed {duplicates_removed} duplicate flights")
        
        return unique_flights
