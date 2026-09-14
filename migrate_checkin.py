"""
migrate_checkin.py
──────────────────
Adds three columns to the `bookings` table for web check-in support:

    seat_number      TEXT     DEFAULT NULL
    checked_in       INTEGER  DEFAULT 0      (SQLite stores booleans as 0/1)
    checkin_opens_at TEXT     DEFAULT NULL   (ISO-8601 datetime string)

Then backfills `checkin_opens_at` for every existing booking that has a
linked flight, setting it to 48 hours before departure.

Safe to run against a live database:
  • Uses ALTER TABLE … ADD COLUMN, which never rewrites existing rows.
  • Skips each ADD COLUMN if it already exists (idempotent — safe to re-run).
  • Wraps the backfill in a single transaction so it's all-or-nothing.

Usage:
    python migrate_checkin.py
    python migrate_checkin.py --db path/to/other.db   # override DB path
"""

import sqlite3
import argparse
from pathlib import Path
from datetime import datetime, timedelta

# ── Config ────────────────────────────────────────────────────────────────────

DEFAULT_DB = Path(__file__).parent / 'instance' / 'flight_booking.db'
CHECKIN_HOURS_BEFORE = 48   # window opens this many hours before departure
CHECKIN_CLOSES_HOURS = 1    # informational — not stored, but matches checkin_status logic

# ── Helpers ───────────────────────────────────────────────────────────────────

def column_exists(cursor, table: str, column: str) -> bool:
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())


def add_column_if_missing(cursor, table: str, column: str, definition: str):
    if column_exists(cursor, table, column):
        print(f"  skip  {table}.{column} — already exists")
    else:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        print(f"  added {table}.{column}")


# ── Migration ─────────────────────────────────────────────────────────────────

def run(db_path: Path):
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    print(f"\nConnecting to {db_path}")
    con = sqlite3.connect(db_path)
    cur = con.cursor()

    # ── Step 1: add columns ───────────────────────────────────────────────────
    print("\n[1/2] Adding columns to bookings …")
    add_column_if_missing(cur, 'bookings', 'seat_number',      'TEXT    DEFAULT NULL')
    add_column_if_missing(cur, 'bookings', 'checked_in',       'INTEGER DEFAULT 0 NOT NULL')
    add_column_if_missing(cur, 'bookings', 'checkin_opens_at', 'TEXT    DEFAULT NULL')
    con.commit()

    # ── Step 2: backfill checkin_opens_at ────────────────────────────────────
    # Only touch rows where checkin_opens_at is still NULL and a departure
    # time can be resolved through the flights table.
    print("\n[2/2] Backfilling checkin_opens_at …")

    cur.execute("""
        SELECT b.id, f.departure_time
        FROM   bookings b
        JOIN   flights  f ON f.id = b.flight_id
        WHERE  b.checkin_opens_at IS NULL
    """)
    rows = cur.fetchall()

    if not rows:
        print("  nothing to backfill — all rows already have checkin_opens_at")
    else:
        updates = []
        skipped = 0
        for booking_id, departure_raw in rows:
            try:
                # SQLite stores datetimes as strings; handle both formats.
                fmt = '%Y-%m-%d %H:%M:%S' if ' ' in departure_raw else '%Y-%m-%dT%H:%M:%S'
                departure = datetime.strptime(departure_raw[:19], fmt)
                opens_at  = departure - timedelta(hours=CHECKIN_HOURS_BEFORE)
                updates.append((opens_at.strftime('%Y-%m-%d %H:%M:%S'), booking_id))
            except (ValueError, TypeError):
                # Unparseable departure — leave NULL, log it.
                print(f"  warn  booking {booking_id[:8]} — could not parse departure '{departure_raw}', skipping")
                skipped += 1

        if updates:
            cur.executemany(
                "UPDATE bookings SET checkin_opens_at = ? WHERE id = ?",
                updates
            )
            con.commit()
            print(f"  updated {len(updates)} row(s)  |  skipped {skipped}")

    # ── Verify ────────────────────────────────────────────────────────────────
    cur.execute("PRAGMA table_info(bookings)")
    cols = {row[1]: row for row in cur.fetchall()}
    assert 'seat_number'      in cols, "seat_number column missing after migration"
    assert 'checked_in'       in cols, "checked_in column missing after migration"
    assert 'checkin_opens_at' in cols, "checkin_opens_at column missing after migration"

    cur.execute("SELECT COUNT(*) FROM bookings WHERE checkin_opens_at IS NULL AND flight_id IS NOT NULL")
    still_null = cur.fetchone()[0]
    if still_null:
        print(f"\n  note  {still_null} booking(s) still have NULL checkin_opens_at")
        print("        (these have no matching flight row — check referential integrity)")

    con.close()
    print("\n✓ Migration complete\n")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Add check-in columns to bookings table')
    parser.add_argument('--db', type=Path, default=DEFAULT_DB,
                        help=f'Path to SQLite database (default: {DEFAULT_DB})')
    args = parser.parse_args()
    run(args.db)