import requests
from app import app
from models import db, Airport
from sqlalchemy.dialects.postgresql import insert

AIRPORTS_URL = "https://raw.githubusercontent.com/mwgg/Airports/master/airports.json"
BATCH_SIZE   = 100

def seed():
    print("Fetching airports...")
    res  = requests.get(AIRPORTS_URL, timeout=30)
    data = res.json()

    # Build deduplicated list of valid airports
    airports = {}
    for code, info in data.items():
        iata = info.get('iata', '').strip().upper()
        if not iata or len(iata) != 3:
            continue
        airports[iata] = {
            'iata_code': iata,
            'name':      info.get('name', '')[:200],
            'city':      info.get('city', '')[:100],
            'country':   info.get('country', '')[:100],
            'latitude':  float(info.get('lat', 0.0)),
            'longitude': float(info.get('lon', 0.0)),
        }

    rows  = list(airports.values())
    total = len(rows)
    print(f"Inserting {total} airports in batches of {BATCH_SIZE}...")

    with app.app_context():
        inserted = 0
        for i in range(0, total, BATCH_SIZE):
            batch = rows[i:i + BATCH_SIZE]
            stmt  = (
                insert(Airport)
                .values(batch)
                .on_conflict_do_nothing(index_elements=['iata_code'])
            )
            db.session.execute(stmt)
            db.session.commit()
            inserted += len(batch)
            print(f"  {inserted}/{total}", end='\r')

        print(f"\nDone — {total} airports seeded.")

if __name__ == '__main__':
    seed()