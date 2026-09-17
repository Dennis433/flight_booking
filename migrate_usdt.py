"""
migrate_usdt.py
───────────────
Adds `chain` column to payments table (TEXT DEFAULT NULL).
Idempotent — safe to re-run.

Usage:
    python migrate_usdt.py
    python migrate_usdt.py --db path/to/flight_booking.db
"""
import sqlite3, argparse
from pathlib import Path

DEFAULT_DB = Path(__file__).parent / 'instance' / 'flight_booking.db'

def run(db_path):
    if not db_path.exists():
        raise FileNotFoundError(f"DB not found: {db_path}")
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute("PRAGMA table_info(payments)")
    cols = [r[1] for r in cur.fetchall()]
    if 'chain' in cols:
        print("  skip  payments.chain — already exists")
    else:
        cur.execute("ALTER TABLE payments ADD COLUMN chain TEXT DEFAULT NULL")
        print("  added payments.chain")
    con.commit()
    con.close()
    print("✓ Done")

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--db', type=Path, default=DEFAULT_DB)
    run(p.parse_args().db)
