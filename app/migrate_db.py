"""Copy the local SQLite data into another database (e.g. Neon Postgres for Vercel).

    python -m app.migrate_db --to "postgresql://..."        # or set DATABASE_URL

Copies businesses, FAQs, calendar links, bookings, leads, requests and the
dashboard's calendar mirror. Conversation sessions are skipped (they're temporary).
Safe to re-run: target tables are emptied first.
"""
import argparse
import os
import sqlite3

from .store import Store

TABLES = ["businesses", "faqs", "booking_calendars", "bookings", "leads", "requests",
          "calendar_events", "calendar_sync"]
SERIAL_TABLES = {"faqs", "bookings", "leads", "requests"}  # have an auto-increment id


def main():
    parser = argparse.ArgumentParser(prog="python -m app.migrate_db")
    parser.add_argument("--from", dest="source", default="ajilt.db", help="SQLite file")
    parser.add_argument("--to", dest="target", default=os.getenv("DATABASE_URL", ""),
                        help="target database URL (default: $DATABASE_URL)")
    args = parser.parse_args()
    if not args.target:
        raise SystemExit("give --to or set DATABASE_URL")

    src = sqlite3.connect(args.source)
    src.row_factory = sqlite3.Row
    target = Store(args.target)  # creates the tables
    with target._conn() as c:
        for table in reversed(TABLES):  # faqs before businesses (foreign key)
            c.execute(f"DELETE FROM {table}")
        for table in TABLES:
            rows = src.execute(f"SELECT * FROM {table}").fetchall()
            if not rows:
                print(f"- {table}: 0 rows")
                continue
            cols = rows[0].keys()
            c.executemany(
                f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                [tuple(r) for r in rows],
            )
            if target.is_postgres and table in SERIAL_TABLES:
                # continue ids after the copied ones
                c.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                          f"(SELECT COALESCE(MAX(id), 1) FROM {table}))")
            print(f"- {table}: {len(rows)} rows")
    print(f"copied into {target.label}")


if __name__ == "__main__":
    main()
