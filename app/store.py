"""Persistence: conversation sessions, appointments and the clinic's Google
Calendar id.

Two backends behind the same methods:
  - SQLite file (local PC):   Store("abijou.db")
  - Postgres (Vercel / Neon): Store("postgresql://...")
SQL is written once with "?" placeholders and ON CONFLICT upserts (both dialects);
the Postgres wrapper swaps placeholders and a few DDL types.
"""
import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Optional

from .models import Session

TABLES = [
    """CREATE TABLE IF NOT EXISTS sessions (
        sender_id  TEXT PRIMARY KEY,
        channel    TEXT,
        state      TEXT,
        data       TEXT,
        updated_at REAL
    )""",
    """CREATE TABLE IF NOT EXISTS booking_calendars (
        business_id TEXT PRIMARY KEY,
        calendar_id TEXT,
        created_at  REAL
    )""",
    """CREATE TABLE IF NOT EXISTS bookings (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id       TEXT,
        channel         TEXT,
        lang            TEXT,
        service_id      TEXT,
        branch_id       TEXT,
        country         TEXT,
        start_at        TEXT,
        end_at          TEXT,
        name            TEXT,
        phone           TEXT,
        price           INTEGER,
        currency        TEXT,
        event_id        TEXT,
        calendar_status TEXT,
        status          TEXT DEFAULT 'new',
        payment_status  TEXT DEFAULT 'at_clinic',
        payment_link    TEXT,
        created_at      REAL,
        updated_at      REAL
    )""",
    "CREATE INDEX IF NOT EXISTS bookings_branch ON bookings(branch_id, start_at)",
    # Sliding-window counters for the public web chat (key = hashed IP).
    """CREATE TABLE IF NOT EXISTS rate_limits (
        key        TEXT PRIMARY KEY,
        hits       TEXT,
        updated_at REAL
    )""",
]
# new -> confirmed -> done, or cancelled / no_show. Cancelled ones free their slot.
BOOKING_STATUSES = ("new", "confirmed", "done", "cancelled", "no_show")
PAYMENT_STATUSES = ("at_clinic", "pending", "paid", "refunded")
BOOKING_COLS = ("sender_id", "channel", "lang", "service_id", "branch_id", "country", "start_at",
                "end_at", "name", "phone", "price", "currency", "event_id", "calendar_status")


class _PgCursor:
    """Makes a psycopg connection accept the SQLite-style SQL used in this module."""

    def __init__(self, conn):
        self.conn = conn

    @staticmethod
    def _sql(sql: str) -> str:
        return sql.replace("?", "%s")

    def execute(self, sql: str, params=()):
        return self.conn.execute(self._sql(sql), params)

    def executemany(self, sql: str, rows):
        with self.conn.cursor() as cur:
            cur.executemany(self._sql(sql), rows)


class _Postgres:
    """One reused connection per process (serverless instances are reused between
    requests), guarded by a lock and reopened if Neon closed it while idle."""

    def __init__(self, url: str):
        self.url = url
        self._conn = None
        self._lock = threading.Lock()

    def _connect(self):
        import psycopg
        from psycopg.rows import dict_row
        # prepare_threshold=None: no server-side prepared statements, which break
        # behind connection poolers such as Neon's default (pgbouncer) URL.
        return psycopg.connect(self.url, row_factory=dict_row, autocommit=True,
                               connect_timeout=10, prepare_threshold=None)

    def _live(self):
        """A connection that is actually usable.

        A serverless instance freezes between requests and Neon drops the idle
        connection, so the cached one can look open while its socket is dead.
        Checking costs one round trip inside the same region; not checking cost
        us whole messages, which just vanished with "SSL connection has been
        closed unexpectedly".
        """
        if self._conn is None or self._conn.closed:
            self._conn = self._connect()
            return self._conn
        try:
            self._conn.execute("SELECT 1")
        except Exception:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = self._connect()
        return self._conn

    @contextmanager
    def session(self):
        import psycopg
        with self._lock:
            conn = self._live()
            try:
                with conn.transaction():
                    yield _PgCursor(conn)
            except psycopg.OperationalError:
                self._conn = None  # died mid-statement: reconnect on the next call
                raise


def _pg_ddl(sql: str) -> str:
    return (sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
               .replace(" REAL", " DOUBLE PRECISION"))


class Store:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.is_postgres = db_path.startswith(("postgres://", "postgresql://"))
        self._pg = _Postgres(db_path) if self.is_postgres else None
        self._init()

    @property
    def label(self) -> str:
        """Where the data lives, without credentials."""
        return "Postgres" if self.is_postgres else self.db_path

    @contextmanager
    def _conn(self):
        if self._pg:
            with self._pg.session() as c:
                yield c
            return
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            with conn:  # commits (or rolls back) the transaction
                yield conn
        finally:
            conn.close()

    def _insert_id(self, c, sql: str, params) -> int:
        if self._pg:
            return c.execute(sql + " RETURNING id", params).fetchone()["id"]
        return c.execute(sql, params).lastrowid

    def _init(self):
        with self._conn() as c:
            for ddl in TABLES:
                c.execute(_pg_ddl(ddl) if self._pg else ddl)

    # ---- sessions ----
    def get_session(self, sender_id: str, channel: str) -> Session:
        with self._conn() as c:
            row = c.execute("SELECT * FROM sessions WHERE sender_id = ?", (sender_id,)).fetchone()
        if row:
            return Session(
                sender_id=row["sender_id"],
                channel=row["channel"] or channel,
                state=row["state"] or "START",
                data=json.loads(row["data"] or "{}"),
                updated_at=float(row["updated_at"] or 0),
            )
        return Session(sender_id=sender_id, channel=channel)

    def save_session(self, s: Session):
        with self._conn() as c:
            c.execute(
                """INSERT INTO sessions (sender_id, channel, state, data, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(sender_id) DO UPDATE SET
                     channel=excluded.channel,
                     state=excluded.state,
                     data=excluded.data,
                     updated_at=excluded.updated_at""",
                (s.sender_id, s.channel, s.state, json.dumps(s.data), time.time()),
            )

    def reset_session(self, sender_id: str):
        with self._conn() as c:
            c.execute("DELETE FROM sessions WHERE sender_id = ?", (sender_id,))

    # ---- Google Calendar link ----
    def get_calendar_id(self, business_id: str) -> Optional[str]:
        with self._conn() as c:
            row = c.execute("SELECT calendar_id FROM booking_calendars WHERE business_id = ?",
                            (business_id,)).fetchone()
        return row["calendar_id"] if row else None

    def set_calendar_id(self, business_id: str, calendar_id: str):
        with self._conn() as c:
            c.execute("""INSERT INTO booking_calendars (business_id, calendar_id, created_at)
                         VALUES (?,?,?) ON CONFLICT(business_id) DO UPDATE SET
                           calendar_id=excluded.calendar_id, created_at=excluded.created_at""",
                      (business_id, calendar_id, time.time()))

    # ---- bookings ----
    def save_booking(self, b: dict) -> int:
        cols = ", ".join(BOOKING_COLS)
        marks = ", ".join("?" for _ in BOOKING_COLS)
        now = time.time()
        with self._conn() as c:
            return self._insert_id(
                c, f"INSERT INTO bookings ({cols}, created_at, updated_at) VALUES ({marks}, ?, ?)",
                (*[b.get(k) for k in BOOKING_COLS], now, now))

    def branch_bookings(self, branch_id: str, since: str, until: str) -> list:
        """Live bookings at one branch overlapping [since, until) (ISO times, same zone)."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT start_at, end_at, event_id FROM bookings WHERE branch_id = ? "
                "AND status NOT IN ('cancelled', 'no_show') AND end_at > ? AND start_at < ?",
                (branch_id, since, until)).fetchall()
        return [dict(r) for r in rows]

    def list_bookings(self, limit: int = 1000) -> list:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM bookings ORDER BY start_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def set_booking_status(self, booking_id: int, status: str) -> bool:
        if status not in BOOKING_STATUSES:
            raise ValueError(f"unknown status {status!r}")
        with self._conn() as c:
            cur = c.execute("UPDATE bookings SET status = ?, updated_at = ? WHERE id = ?",
                            (status, time.time(), booking_id))
            return cur.rowcount > 0

    def set_payment(self, booking_id: int, status: str, link: str = "") -> bool:
        if status not in PAYMENT_STATUSES:
            raise ValueError(f"unknown payment status {status!r}")
        with self._conn() as c:
            cur = c.execute("UPDATE bookings SET payment_status = ?, "
                            "payment_link = COALESCE(NULLIF(?, ''), payment_link), updated_at = ? "
                            "WHERE id = ?", (status, link, time.time(), booking_id))
            return cur.rowcount > 0

    # ---- rate limiting ----
    def rate_hit(self, key: str, keep_seconds: int = 86400) -> list:
        """Record one hit for `key` and return the hit times still inside the window."""
        now = time.time()
        with self._conn() as c:
            row = c.execute("SELECT hits FROM rate_limits WHERE key = ?", (key,)).fetchone()
            old = json.loads(row["hits"]) if row and row["hits"] else []
            hits = [t for t in old if t > now - keep_seconds][-500:] + [now]
            c.execute("""INSERT INTO rate_limits (key, hits, updated_at) VALUES (?,?,?)
                         ON CONFLICT(key) DO UPDATE SET
                           hits=excluded.hits, updated_at=excluded.updated_at""",
                      (key, json.dumps(hits), now))
        return hits
