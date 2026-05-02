import os
import sys
import csv
import requests
import logging
from io import StringIO

# إضافة مسار الباك إند لكي يتعرف على قاعدة البيانات
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from app.database import SessionLocal
from app.models import DimGeography, DimOperator

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# روابط قواعد البيانات العالمية المفتوحة للطيران
AIRPORTS_URL = "https://raw.githubusercontent.com/davidmegginson/ourairports-data/main/airports.csv"
AIRLINES_URL = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/airlines.dat"

def seed_airports(db):
    logger.info("📥 جاري تحميل بيانات المطارات العالمية...")
    response = requests.get(AIRPORTS_URL)
    response.raise_for_status()
    
    csv_data = csv.DictReader(StringIO(response.text))
    
    added = 0
    updated = 0
    
    for row in csv_data:
        # نحن نهتم بالمطارات الكبيرة والمتوسطة والصغيرة (تجاهل مهابط الهليكوبتر المغلقة)
        if row['type'] in ['closed']:
            continue
            
        icao = row['ident'].upper() if row['ident'] else None
        if not icao or len(icao) > 4:
            continue
            
        iata = row['iata_code'].upper() if row['iata_code'] else None
        
        # تحويل الارتفاع من قدم إلى متر
        elevation_ft = row['elevation_ft']
        elevation_m = float(elevation_ft) * 0.3048 if elevation_ft else None

        airport = db.query(DimGeography).filter(DimGeography.icao_code == icao).first()
        
        if not airport:
            airport = DimGeography(icao_code=icao)
            db.add(airport)
            added += 1
        else:
            updated += 1
            
        airport.iata_code = iata
        airport.name = row['name']
        airport.city = row['municipality']
        airport.country_code = row['iso_country']
        airport.latitude = float(row['latitude_deg']) if row['latitude_deg'] else None
        airport.longitude = float(row['longitude_deg']) if row['longitude_deg'] else None
        airport.elevation_m = elevation_m
        
    db.commit()
    logger.info(f"✅ تمت تغذية المطارات: تمت إضافة {added}، وتحديث {updated} مطار.")

def seed_airlines(db):
    logger.info("📥 جاري تحميل بيانات شركات الطيران العالمية...")
    response = requests.get(AIRLINES_URL)
    response.raise_for_status()
    
    # ملف OpenFlights لا يحتوي على Header، لذلك نحدد الأعمدة يدوياً
    csv_data = csv.reader(StringIO(response.text))
    
    added = 0
    updated = 0
    
    for row in csv_data:
        if len(row) < 6:
            continue
            
        name = row[1]
        iata = row[3].upper() if row[3] and row[3] != r'\N' else None
        icao = row[4].upper() if row[4] and row[4] != r'\N' else None
        callsign = row[5] if row[5] and row[5] != r'\N' else None
        country = row[6] if row[6] and row[6] != r'\N' else None
        
        if not icao or len(icao) > 3:
            continue
            
        operator = db.query(DimOperator).filter(DimOperator.icao_code == icao).first()
        
        if not operator:
            operator = DimOperator(icao_code=icao)
            db.add(operator)
            added += 1
        else:
            updated += 1
            
        operator.iata_code = iata
        operator.name = name
        operator.country_code = country
        
    db.commit()
    logger.info(f"✅ تمت تغذية شركات الطيران: تمت إضافة {added}، وتحديث {updated} شركة.")

def run_seeder():
    logger.info("🚀 بدء عملية تغذية البيانات الثابتة (Master Data Seeding)...")
    db = SessionLocal()
    try:
        seed_airports(db)
        seed_airlines(db)
        logger.info("🎉 اكتملت العملية بنجاح! قاعدة البيانات الآن تحتوي على كافة بيانات الطيران العالمية.")
    except Exception as e:
        logger.error(f"❌ حدث خطأ أثناء التغذية: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    run_seeder()