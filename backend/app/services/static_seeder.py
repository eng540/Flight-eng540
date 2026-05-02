import csv
import requests
import logging
from io import StringIO
from sqlalchemy.orm import Session
from app.models import DimGeography, DimOperator

logger = logging.getLogger(__name__)

AIRPORTS_URL = "https://raw.githubusercontent.com/davidmegginson/ourairports-data/main/airports.csv"
AIRLINES_URL = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/airlines.dat"

def seed_all_static_data(db: Session):
    results = {"airports_added": 0, "airports_updated": 0, "airlines_added": 0, "airlines_updated": 0}
    
    try:
        # 1. المطارات
        logger.info("Fetching Airports...")
        res_airports = requests.get(AIRPORTS_URL, timeout=30)
        res_airports.raise_for_status()
        csv_data = csv.DictReader(StringIO(res_airports.text))
        
        for row in csv_data:
            if row['type'] in['closed']: continue
            icao = row['ident'].upper() if row['ident'] else None
            if not icao or len(icao) > 4: continue
            
            iata = row['iata_code'].upper() if row['iata_code'] else None
            elevation_ft = row['elevation_ft']
            elevation_m = float(elevation_ft) * 0.3048 if elevation_ft else None

            airport = db.query(DimGeography).filter(DimGeography.icao_code == icao).first()
            if not airport:
                airport = DimGeography(icao_code=icao)
                db.add(airport)
                results["airports_added"] += 1
            else:
                results["airports_updated"] += 1
                
            airport.iata_code = iata
            airport.name = row['name']
            airport.city = row['municipality']
            airport.country_code = row['iso_country']
            airport.latitude = float(row['latitude_deg']) if row['latitude_deg'] else None
            airport.longitude = float(row['longitude_deg']) if row['longitude_deg'] else None
            airport.elevation_m = elevation_m

        db.commit()

        # 2. الشركات
        logger.info("Fetching Airlines...")
        res_airlines = requests.get(AIRLINES_URL, timeout=30)
        res_airlines.raise_for_status()
        csv_data_airlines = csv.reader(StringIO(res_airlines.text))
        
        for row in csv_data_airlines:
            if len(row) < 6: continue
            name = row[1]
            iata = row[3].upper() if row[3] and row[3] != r'\N' else None
            icao = row[4].upper() if row[4] and row[4] != r'\N' else None
            country = row[6] if row[6] and row[6] != r'\N' else None
            
            if not icao or len(icao) > 3: continue
                
            operator = db.query(DimOperator).filter(DimOperator.icao_code == icao).first()
            if not operator:
                operator = DimOperator(icao_code=icao)
                db.add(operator)
                results["airlines_added"] += 1
            else:
                results["airlines_updated"] += 1
                
            operator.iata_code = iata
            operator.name = name
            operator.country_code = country
            
        db.commit()
        return {"status": "success", "details": results}

    except Exception as e:
        db.rollback()
        logger.error(f"Seeding failed: {e}")
        return {"status": "error", "message": str(e)}