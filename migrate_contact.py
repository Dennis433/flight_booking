"""
migrate_contact.py
──────────────────
Adds two columns to the `bookings` table:

    contact_email  TEXT  DEFAULT NULL
    contact_phone  TEXT  DEFAULT NULL

Idempotent — skips columns that already exist. Safe to run against a live DB.

Usage:
    python migrate_contact.py
    python migrate_contact.py --db path/to/flight_booking.db
"""

import sqlite3
import argparse
from pathlib import Path

DEFAULT_DB = Path(__file__).parent / 'instance' / 'flight_booking.db'


def column_exists(cursor, table, column):
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())


def run(db_path: Path):
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    print(f"\nConnecting to {db_path}")
    con = sqlite3.connect(db_path)
    cur = con.cursor()

    for col, defn in [
        ('contact_email', 'TEXT DEFAULT NULL'),
        ('contact_phone', 'TEXT DEFAULT NULL'),
    ]:
        if column_exists(cur, 'bookings', col):
            print(f"  skip  bookings.{col} — already exists")
        else:
            cur.execute(f"ALTER TABLE bookings ADD COLUMN {col} {defn}")
            print(f"  added bookings.{col}")

    con.commit()
    con.close()
    print("\n✓ Migration complete\n")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Add contact columns to bookings table')
    parser.add_argument('--db', type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    run(args.db)