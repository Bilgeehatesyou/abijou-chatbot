"""Persistence for conversation sessions, captured leads, demo bookings/requests,
the demo FAQ knowledge base (businesses + faqs) and the dashboard's calendar mirror.

Two backends behind the same methods:
  - SQLite file (local PC):   Store("ajilt.db")
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
    """CREATE TABLE IF NOT EXISTS leads (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id     TEXT,
        channel       TEXT,
        org_name      TEXT,
        business_type TEXT,
        industry      TEXT,
        employees     INTEGER,
        branches      INTEGER,
        tier          TEXT,
        quote         TEXT,
        path          TEXT,
        phone         TEXT,
        contact_name  TEXT,
        slot          TEXT,
        created_at    REAL
    )""",
    """CREATE TABLE IF NOT EXISTS businesses (
        id         TEXT PRIMARY KEY,
        industry   TEXT,
        kind_mn    TEXT,
        kind_en    TEXT,
        emoji      TEXT,
        name_mn    TEXT,
        name_en    TEXT,
        profile    TEXT,
        updated_at REAL
    )""",
    """CREATE TABLE IF NOT EXISTS faqs (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        business_id TEXT REFERENCES businesses(id),
        faq_key     TEXT,
        category    TEXT,
        question_mn TEXT,
        question_en TEXT,
        answer_mn   TEXT,
        answer_en   TEXT,
        variants    TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS faqs_business ON faqs(business_id)",
    """CREATE TABLE IF NOT EXISTS booking_calendars (
        business_id TEXT PRIMARY KEY,
        calendar_id TEXT,
        created_at  REAL
    )""",
    """CREATE TABLE IF NOT EXISTS bookings (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        business_id TEXT,
        sender_id   TEXT,
        channel     TEXT,
        service_id  TEXT,
        branch_id   TEXT,
        start_at    TEXT,
        end_at      TEXT,
        name        TEXT,
        phone       TEXT,
        event_id    TEXT,
        status      TEXT,
        created_at  REAL,
        staff_id    TEXT
    )""",
    # Mirror of each business calendar, refreshed by app.dashboard's sync.
    """CREATE TABLE IF NOT EXISTS calendar_events (
        business_id TEXT,
        event_id    TEXT,
        status      TEXT,
        start_at    TEXT,
        end_at      TEXT,
        summary     TEXT,
        service_id  TEXT,
        staff_id    TEXT,
        branch_id   TEXT,
        name        TEXT,
        phone       TEXT,
        sender_id   TEXT,
        source      TEXT,
        created_at  TEXT,
        updated_at  TEXT,
        PRIMARY KEY (business_id, event_id)
    )""",
    """CREATE TABLE IF NOT EXISTS calendar_sync (
        business_id TEXT PRIMARY KEY, synced_at REAL, error TEXT)""",
    # Order / stay requests from businesses without time-slot booking.
    """CREATE TABLE IF NOT EXISTS requests (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        business_id TEXT,
        sender_id   TEXT,
        channel     TEXT,
        title       TEXT,
        details     TEXT,
        name        TEXT,
        phone       TEXT,
        created_at  REAL,
        status      TEXT DEFAULT 'new',
        updated_at  REAL
    )""",
]
ORDER_STATUSES = ("new", "confirmed", "delivered", "cancelled")


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

    @contextmanager
    def session(self):
        import psycopg
        with self._lock:
            if self._conn is None or self._conn.closed:
                self._conn = self._connect()
            try:
                with self._conn.transaction():
                    yield _PgCursor(self._conn)
            except psycopg.OperationalError:
                self._conn = None  # stale connection: reconnect on the next call
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
            # Columns added after a table was first created: add them to older databases.
            for table, column, ddl in [("bookings", "staff_id", "TEXT"),
                                       ("requests", "status", "TEXT DEFAULT 'new'"),
                                       ("requests", "updated_at", "REAL")]:
                if self._pg:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} "
                              + ddl.replace("REAL", "DOUBLE PRECISION"))
                elif column not in {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

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

    # ---- leads ----
    def save_lead(self, s: Session, path: str) -> int:
        d = s.data
        with self._conn() as c:
            return self._insert_id(
                c,
                """INSERT INTO leads
                   (sender_id, channel, org_name, business_type, industry,
                    employees, branches, tier, quote, path, phone,
                    contact_name, slot, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    s.sender_id, s.channel, d.get("org_name"), d.get("business_type"),
                    d.get("industry"), d.get("employees"), d.get("branches"),
                    d.get("tier"), str(d.get("quote")), path, d.get("phone"),
                    d.get("contact_name"), d.get("slot"), time.time(),
                ),
            )

    # ---- demo knowledge base ----
    def replace_business(self, biz: dict):
        """Insert or fully replace one business and its FAQs."""
        with self._conn() as c:
            c.execute("DELETE FROM faqs WHERE business_id = ?", (biz["id"],))
            c.execute(
                """INSERT INTO businesses
                   (id, industry, kind_mn, kind_en, emoji, name_mn, name_en, profile, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                     industry=excluded.industry, kind_mn=excluded.kind_mn,
                     kind_en=excluded.kind_en, emoji=excluded.emoji, name_mn=excluded.name_mn,
                     name_en=excluded.name_en, profile=excluded.profile,
                     updated_at=excluded.updated_at""",
                (biz["id"], biz["industry"], biz["kind"]["mn"], biz["kind"]["en"], biz["emoji"],
                 biz["name"]["mn"], biz["name"]["en"],
                 json.dumps(biz["profile"], ensure_ascii=False), time.time()),
            )
            c.executemany(
                """INSERT INTO faqs
                   (business_id, faq_key, category, question_mn, question_en,
                    answer_mn, answer_en, variants)
                   VALUES (?,?,?,?,?,?,?,?)""",
                [(biz["id"], f["id"], f["category"],
                  f["question"]["mn"], f["question"]["en"],
                  f["answer"]["mn"], f["answer"]["en"],
                  json.dumps(f.get("variants", {}), ensure_ascii=False))
                 for f in biz["faqs"]],
            )

    def list_businesses(self) -> list:
        # updated_at follows load order (the loader goes through seeds.yaml in order)
        with self._conn() as c:
            rows = c.execute(
                "SELECT id, industry, kind_mn, kind_en, emoji, name_mn, name_en "
                "FROM businesses ORDER BY updated_at, id"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_business(self, business_id: str) -> Optional[dict]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM businesses WHERE id = ?", (business_id,)).fetchone()
        if not row:
            return None
        biz = dict(row)
        biz["profile"] = json.loads(biz["profile"])
        return biz

    # ---- demo bookings ----
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

    def save_request(self, r: dict) -> int:
        with self._conn() as c:
            return self._insert_id(
                c,
                """INSERT INTO requests (business_id, sender_id, channel, title, details, name,
                   phone, created_at) VALUES (?,?,?,?,?,?,?,?)""",
                (r["business_id"], r["sender_id"], r["channel"], r["title"],
                 json.dumps(r["details"], ensure_ascii=False), r["name"], r["phone"], time.time()),
            )

    def list_requests(self, business_id: str, limit: int = 1000) -> list:
        with self._conn() as c:
            rows = c.execute(
                "SELECT id, sender_id, channel, title, details, name, phone, created_at, status, "
                "updated_at FROM requests WHERE business_id = ? ORDER BY created_at DESC LIMIT ?",
                (business_id, limit)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["details"] = json.loads(d["details"] or "[]")
            d["status"] = d["status"] or "new"
            out.append(d)
        return out

    def set_request_status(self, business_id: str, request_id: int, status: str) -> bool:
        if status not in ORDER_STATUSES:
            raise ValueError(f"unknown status {status!r}")
        with self._conn() as c:
            cur = c.execute("UPDATE requests SET status = ?, updated_at = ? WHERE id = ? AND business_id = ?",
                            (status, time.time(), request_id, business_id))
            return cur.rowcount > 0

    def save_booking(self, b: dict) -> int:
        with self._conn() as c:
            return self._insert_id(
                c,
                """INSERT INTO bookings
                   (business_id, sender_id, channel, service_id, branch_id, start_at, end_at,
                    name, phone, event_id, status, created_at, staff_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (b["business_id"], b["sender_id"], b["channel"], b["service_id"], b.get("branch_id"),
                 b["start_at"], b["end_at"], b["name"], b["phone"], b.get("event_id"),
                 b["status"], time.time(), b.get("staff_id")),
            )

    # ---- dashboard calendar mirror ----
    EVENT_COLS = ("event_id", "status", "start_at", "end_at", "summary", "service_id", "staff_id",
                  "branch_id", "name", "phone", "sender_id", "source", "created_at", "updated_at")

    def replace_calendar_events(self, business_id: str, events: list, since: str, until: str):
        """Replace the mirrored events whose start falls in [since, until)."""
        cols = ", ".join(self.EVENT_COLS)
        updates = ", ".join(f"{k}=excluded.{k}" for k in self.EVENT_COLS if k != "event_id")
        with self._conn() as c:
            c.execute("DELETE FROM calendar_events WHERE business_id = ? AND start_at >= ? "
                      "AND start_at < ?", (business_id, since, until))
            c.executemany(
                f"INSERT INTO calendar_events (business_id, {cols}) "
                f"VALUES (?{', ?' * len(self.EVENT_COLS)}) "
                f"ON CONFLICT(business_id, event_id) DO UPDATE SET {updates}",
                [(business_id, *[e.get(k) for k in self.EVENT_COLS]) for e in events],
            )
            c.execute("""INSERT INTO calendar_sync (business_id, synced_at, error) VALUES (?,?,NULL)
                         ON CONFLICT(business_id) DO UPDATE SET synced_at=excluded.synced_at,
                           error=NULL""", (business_id, time.time()))

    def set_sync_error(self, business_id: str, error: str):
        with self._conn() as c:
            c.execute("""INSERT INTO calendar_sync (business_id, synced_at, error) VALUES (?, NULL, ?)
                         ON CONFLICT(business_id) DO UPDATE SET error = excluded.error""",
                      (business_id, error))

    def get_sync_state(self, business_id: str) -> dict:
        with self._conn() as c:
            row = c.execute("SELECT synced_at, error FROM calendar_sync WHERE business_id = ?",
                            (business_id,)).fetchone()
        return dict(row) if row else {"synced_at": None, "error": None}

    def calendar_events(self, business_id: str) -> list:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM calendar_events WHERE business_id = ? ORDER BY start_at",
                             (business_id,)).fetchall()
        return [dict(r) for r in rows]

    def get_faqs(self, business_id: str) -> list:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM faqs WHERE business_id = ? ORDER BY id", (business_id,)
            ).fetchall()
        out = []
        for r in rows:
            f = dict(r)
            f["variants"] = json.loads(f["variants"] or "{}")
            out.append(f)
        return out
