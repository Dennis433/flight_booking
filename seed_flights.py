from app import app
from models import db, Airport, Flight
from datetime import datetime, timedelta
import random
import uuid

ROUTES = [
    ('LOS', 'LHR'),
    ('LHR', 'JFK'),
    ('JFK', 'LAX'),
    ('LAX', 'NRT'),
    ('NRT', 'DXB'),
    ('DXB', 'LOS'),
    ('CDG', 'JFK'),
    ('JFK', 'CDG'),
    ('LHR', 'DXB'),
    ('DXB', 'BOM'),
    ('SIN', 'NRT'),
    ('JFK', 'LHR'),
]

AIRLINES = ['SC', 'SK', 'SX']
CABINS   = ['economy', 'business', 'first']
PRICES   = {'economy': (300, 900), 'business': (1200, 4000), 'first': (4000, 12000)}

def seed():
    with app.app_context():
        # Load all needed airports in one query
        iata_codes = list({code for pair in ROUTES for code in pair})
        airport_map = {
            a.iata_code: a
            for a in Airport.query.filter(Airport.iata_code.in_(iata_codes)).all()
        }

        flights = []
        for origin_iata, dest_iata in ROUTES:
            origin = airport_map.get(origin_iata)
            dest   = airport_map.get(dest_iata)
            if not origin or not dest:
                print(f'Skipping {origin_iata} → {dest_iata} (airport not found)')
                continue

            for days_ahead in [3, 7, 14, 21, 28, 35]:
                for cabin in CABINS:
                    hour      = random.choice([6, 8, 10, 13, 16, 19, 22])
                    departure = datetime.utcnow().replace(
                        hour=hour, minute=0, second=0, microsecond=0
                    ) + timedelta(days=days_ahead)
                    duration_hrs = random.randint(2, 14)
                    arrival      = departure + timedelta(hours=duration_hrs)
                    low, high    = PRICES[cabin]

                    flights.append({
                        'id':              str(uuid.uuid4()),
                        'flight_number':   f'{random.choice(AIRLINES)}{random.randint(100,999)}',
                        'origin_id':       origin.id,
                        'destination_id':  dest.id,
                        'departure_time':  departure,
                        'arrival_time':    arrival,
                        'price_usd':       round(random.uniform(low, high), 2),
                        'seats_available': random.randint(20, 150),
                        'cabin_class':     cabin,
                    })

        # Commit in batches of 50
        BATCH = 50
        for i in range(0, len(flights), BATCH):
            batch = flights[i:i + BATCH]
            db.session.bulk_insert_mappings(Flight, batch)
            db.session.commit()
            print(f"  {min(i+BATCH, len(flights))}/{len(flights)} flights", end='\r')

        print(f"\nDone — {len(flights)} flights seeded.")

if __name__ == '__main__':
    seed()