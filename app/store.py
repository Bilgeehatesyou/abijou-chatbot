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
    # Work for bas.mn, queued next to the row it describes and sent afterwards (app/crm.py),
    # so a slow or down CRM never costs a patient their booking; failures are retried.
    """CREATE TABLE IF NOT EXISTS crm_outbox (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        kind        TEXT,
        ref_id      TEXT,
        payload     TEXT,
        status      TEXT DEFAULT 'pending',
        attempts    INTEGER DEFAULT 0,
        next_try    REAL,
        locked_at   REAL,
        last_error  TEXT,
        created_at  REAL,
        done_at     REAL
    )""",
    "CREATE INDEX IF NOT EXISTS crm_outbox_due ON crm_outbox(status, next_try)",
    # Small key/value state: last pull, phone -> bas.mn customer, resolved custom field ids.
    """CREATE TABLE IF NOT EXISTS crm_state (
        key        TEXT PRIMARY KEY,
        value      TEXT,
        updated_at REAL
    )""",
    # Every message in and out of every channel, so staff can read and answer in the CRM inbox.
    # author: patient | bot | staff | system
    """CREATE TABLE IF NOT EXISTS messages (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id     TEXT,
        channel       TEXT,
        direction     TEXT,
        author        TEXT,
        staff_user_id INTEGER,
        text          TEXT,
        payload       TEXT,
        created_at    REAL
    )""",
    "CREATE INDEX IF NOT EXISTS messages_sender ON messages(sender_id, id)",
    # One row per conversation. needs_human is 0/1 (works on SQLite and Postgres alike).
    """CREATE TABLE IF NOT EXISTS conversations (
        sender_id          TEXT PRIMARY KEY,
        channel            TEXT,
        needs_human        INTEGER DEFAULT 0,
        bot_paused_until   REAL DEFAULT 0,
        assigned_branch_id TEXT,
        assigned_user_id   INTEGER,
        last_message_at    REAL,
        last_preview       TEXT
    )""",
]
# Columns added after the first release: added to older databases on start.
ADDED_COLUMNS = [("bookings", "crm_customer_id", "TEXT"), ("bookings", "crm_event_id", "TEXT"),
                 ("bookings", "crm_invoice_id", "TEXT"), ("bookings", "crm_invoice_number", "TEXT"),
                 ("bookings", "note", "TEXT")]   # what the patient wrote in the website's form
# new -> confirmed -> done, or cancelled / no_show. Cancelled ones free their slot.
BOOKING_STATUSES = ("new", "confirmed", "done", "cancelled", "no_show")
# at_clinic: nothing billed yet. unpaid / partial / paid: the bas.mn invoice's state.
PAYMENT_STATUSES = ("at_clinic", "pending", "unpaid", "partial", "paid", "refunded")
CRM_BOOKING_COLS = ("crm_customer_id", "crm_event_id", "crm_invoice_id", "crm_invoice_number",
                    "payment_status", "payment_link", "status", "start_at", "end_at")
BOOKING_COLS = ("sender_id", "channel", "lang", "service_id", "branch_id", "country", "start_at",
                "end_at", "name", "phone", "price", "currency", "event_id", "calendar_status", "note")


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
            for table, column, ddl in ADDED_COLUMNS:
                if self._pg:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {ddl}")
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

    def get_booking(self, booking_id) -> Optional[dict]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM bookings WHERE id = ?", (int(booking_id),)).fetchone()
        return dict(row) if row else None

    def update_booking(self, booking_id, **cols) -> bool:
        """bas.mn ids and what the sync learns back (status, payment, a moved time)."""
        if not cols or set(cols) - set(CRM_BOOKING_COLS):
            raise ValueError(f"bad booking columns: {sorted(cols)}")
        if "status" in cols and cols["status"] not in BOOKING_STATUSES:
            raise ValueError(f"unknown status {cols['status']!r}")
        if "payment_status" in cols and cols["payment_status"] not in PAYMENT_STATUSES:
            raise ValueError(f"unknown payment status {cols['payment_status']!r}")
        sets = ", ".join(f"{k} = ?" for k in cols)
        with self._conn() as c:
            cur = c.execute(f"UPDATE bookings SET {sets}, updated_at = ? WHERE id = ?",
                            (*cols.values(), time.time(), int(booking_id)))
            return cur.rowcount > 0

    def crm_bookings(self) -> list:
        """Bookings that have an appointment or invoice in bas.mn."""
        with self._conn() as c:
            rows = c.execute("SELECT * FROM bookings WHERE crm_event_id IS NOT NULL "
                             "OR crm_invoice_id IS NOT NULL ORDER BY start_at").fetchall()
        return [dict(r) for r in rows]

    # ---- bas.mn outbox (app/crm.py) ----
    def crm_enqueue(self, kind: str, ref_id, payload: Optional[dict] = None) -> int:
        now = time.time()
        with self._conn() as c:
            return self._insert_id(
                c, "INSERT INTO crm_outbox (kind, ref_id, payload, status, attempts, next_try, created_at) "
                   "VALUES (?, ?, ?, 'pending', 0, ?, ?)",
                (kind, str(ref_id), json.dumps(payload or {}, ensure_ascii=False), now, now))

    def crm_claim(self, limit: int = 20, lock_seconds: int = 120) -> list:
        """Due jobs, oldest first, locked so a second instance doesn't send them too."""
        now = time.time()
        with self._conn() as c:
            ids = [r["id"] for r in c.execute(
                "SELECT id FROM crm_outbox WHERE status = 'pending' AND next_try <= ? "
                "AND (locked_at IS NULL OR locked_at < ?) ORDER BY id LIMIT ?",
                (now, now - lock_seconds, limit)).fetchall()]
            claimed = [i for i in ids if c.execute(
                "UPDATE crm_outbox SET locked_at = ? WHERE id = ? AND (locked_at IS NULL OR locked_at < ?)",
                (now, i, now - lock_seconds)).rowcount]
            if not claimed:
                return []
            rows = c.execute(f"SELECT * FROM crm_outbox WHERE id IN ({', '.join('?' * len(claimed))}) "
                             "ORDER BY id", claimed).fetchall()
        jobs = []
        for r in rows:
            job = dict(r)
            job["payload"] = json.loads(job["payload"] or "{}")
            jobs.append(job)
        return jobs

    def crm_finish(self, job_id: int):
        with self._conn() as c:
            c.execute("UPDATE crm_outbox SET status = 'done', locked_at = NULL, last_error = NULL, "
                      "done_at = ? WHERE id = ?", (time.time(), job_id))

    def crm_retry(self, job_id: int, error: str, delay: float, give_up: bool = False):
        with self._conn() as c:
            c.execute("UPDATE crm_outbox SET status = ?, attempts = attempts + 1, next_try = ?, "
                      "locked_at = NULL, last_error = ? WHERE id = ?",
                      ("failed" if give_up else "pending", time.time() + delay, error[:500], job_id))

    def crm_requeue_failed(self) -> int:
        with self._conn() as c:
            return c.execute("UPDATE crm_outbox SET status = 'pending', attempts = 0, next_try = ? "
                             "WHERE status = 'failed'", (time.time(),)).rowcount

    def crm_has_pending(self, kind: str, ref_id) -> bool:
        with self._conn() as c:
            return c.execute("SELECT 1 FROM crm_outbox WHERE kind = ? AND ref_id = ? AND status = 'pending'",
                             (kind, str(ref_id))).fetchone() is not None

    def crm_jobs(self, status: str = "", limit: int = 50) -> list:
        with self._conn() as c:
            if status:
                rows = c.execute("SELECT * FROM crm_outbox WHERE status = ? ORDER BY id DESC LIMIT ?",
                                 (status, limit)).fetchall()
            else:
                rows = c.execute("SELECT * FROM crm_outbox ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def crm_counts(self) -> dict:
        with self._conn() as c:
            rows = c.execute("SELECT status, COUNT(*) AS n FROM crm_outbox GROUP BY status").fetchall()
        return {r["status"]: r["n"] for r in rows}

    def crm_state_get(self, key: str, default=None):
        with self._conn() as c:
            row = c.execute("SELECT value FROM crm_state WHERE key = ?", (key,)).fetchone()
        return json.loads(row["value"]) if row and row["value"] is not None else default

    def crm_state_set(self, key: str, value):
        with self._conn() as c:
            c.execute("""INSERT INTO crm_state (key, value, updated_at) VALUES (?,?,?)
                         ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
                      (key, json.dumps(value, ensure_ascii=False), time.time()))

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

    # ---- inbox: messages and conversations ----
    def log_message(self, sender_id: str, channel: str, direction: str, author: str, text: str,
                    payload: Optional[dict] = None, staff_user_id: Optional[int] = None) -> int:
        now = time.time()
        with self._conn() as c:
            mid = self._insert_id(c, """INSERT INTO messages (sender_id, channel, direction, author,
                                        staff_user_id, text, payload, created_at) VALUES (?,?,?,?,?,?,?,?)""",
                                  (sender_id, channel, direction, author, staff_user_id, text,
                                   json.dumps(payload, ensure_ascii=False) if payload else None, now))
            c.execute("""INSERT INTO conversations (sender_id, channel, last_message_at, last_preview)
                         VALUES (?,?,?,?) ON CONFLICT(sender_id) DO UPDATE SET
                           last_message_at=excluded.last_message_at, last_preview=excluded.last_preview""",
                      (sender_id, channel, now, (text or "")[:120]))
        return mid

    def get_conversation(self, sender_id: str) -> Optional[dict]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM conversations WHERE sender_id = ?", (sender_id,)).fetchone()
        return dict(row) if row else None

    def set_conversation(self, sender_id: str, channel: str, **cols):
        allowed = {k: v for k, v in cols.items() if k in ("needs_human", "bot_paused_until",
                                                         "assigned_branch_id", "assigned_user_id")}
        if not allowed:
            return
        with self._conn() as c:
            c.execute("INSERT INTO conversations (sender_id, channel, last_message_at) VALUES (?,?,?) "
                      "ON CONFLICT(sender_id) DO NOTHING", (sender_id, channel, time.time()))
            sets = ", ".join(f"{k} = ?" for k in allowed)
            c.execute(f"UPDATE conversations SET {sets} WHERE sender_id = ?", (*allowed.values(), sender_id))

    def messages_after(self, sender_id: str, after_id: int, authors=("staff", "system")) -> list:
        marks = ",".join("?" * len(authors))
        with self._conn() as c:
            rows = c.execute(f"SELECT id, author, text, created_at FROM messages WHERE sender_id = ? "
                             f"AND id > ? AND author IN ({marks}) ORDER BY id LIMIT 50",
                             (sender_id, after_id, *authors)).fetchall()
        return [dict(r) for r in rows]

    def button_title(self, sender_id: str, payload: str) -> Optional[str]:
        """The title of a button the bot offered recently, given what came back (its payload)."""
        with self._conn() as c:
            rows = c.execute("SELECT payload FROM messages WHERE sender_id = ? AND author = 'bot' "
                             "AND payload IS NOT NULL ORDER BY id DESC LIMIT 5", (sender_id,)).fetchall()
        for r in rows:
            for q in (json.loads(r["payload"]) or {}).get("quick_replies", []):
                if isinstance(q, dict) and q.get("payload") == payload:
                    return q.get("title")
        return None
