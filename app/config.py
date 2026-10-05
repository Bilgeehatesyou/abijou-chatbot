"""Central configuration, loaded from environment / .env."""
import os
from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    return int(value) if value.isdigit() else default


class Settings:
    # Meta
    VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN", "changeme")
    PAGE_ACCESS_TOKEN = os.getenv("META_PAGE_ACCESS_TOKEN", "")
    APP_SECRET = os.getenv("META_APP_SECRET", "")
    GRAPH_API_VERSION = os.getenv("GRAPH_API_VERSION", "v21.0")

    # LLM (OpenAI-compatible endpoint)
    LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
    LLM_MODEL = os.getenv("LLM_MODEL", "llama3.1:8b")
    LLM_API_KEY = os.getenv("LLM_API_KEY", "ollama")
    LLM_ENABLED = _bool("LLM_ENABLED", True)
    # Gemini 3 can't disable thinking; "low" keeps chat replies fast. Leave empty for Ollama.
    LLM_REASONING_EFFORT = os.getenv("LLM_REASONING_EFFORT", "")
    # Tried when the main model errors (e.g. Gemini 503 "high demand") or takes too long.
    LLM_FALLBACK_MODEL = os.getenv("LLM_FALLBACK_MODEL", "")
    LLM_PRIMARY_TIMEOUT = float(os.getenv("LLM_PRIMARY_TIMEOUT", "15"))

    # Booking (Google Calendar via a service account). On hosts without a secrets
    # folder (Vercel), put the whole key JSON in GOOGLE_SERVICE_ACCOUNT_JSON instead.
    GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE",
                                            "secrets/google-service-account.json")
    GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    BOOKING_CALENDAR_SHARE_WITH = os.getenv("BOOKING_CALENDAR_SHARE_WITH", "")
    BOOKING_TIMEZONE = os.getenv("BOOKING_TIMEZONE", "Asia/Ulaanbaatar")

    # Owner dashboard (/dashboard). Empty password = no login, for local use only.
    DASHBOARD_USER = os.getenv("DASHBOARD_USER", "admin")
    DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "")
    # Shared secret the ajiltai.tech booking form sends with each meeting
    # (X-Ajilt-Token). Empty = the /api/site-booking endpoint is turned off.
    SITE_BOOKING_TOKEN = os.getenv("SITE_BOOKING_TOKEN", "")
    # ZevChat's HTTP API step sends this as X-Ajilt-Token. Falls back to the
    # booking token, so there is one secret to manage while we are testing.
    ZEV_TOKEN = os.getenv("ZEV_TOKEN", "")

    # bas.mn (Perfex CRM): where a client's leads, bookings and orders belong.
    # Empty = the chatbot keeps everything in our own database only.
    BASMN_URL = os.getenv("BASMN_URL", "").rstrip("/")
    BASMN_API_KEY = os.getenv("BASMN_API_KEY", "")
    # Ids from bas.mn Setup > Leads > Sources / Statuses and Setup > Staff. The defaults
    # are aibiz.bas.mn's: status 1 is "Customer" there, so new leads must not use it.
    BASMN_STATUS_NEW = _int("BASMN_STATUS_NEW", 2)
    BASMN_STATUS_MEETING = _int("BASMN_STATUS_MEETING", 0)      # 0 = leave as new
    BASMN_STATUS_CANCELLED = _int("BASMN_STATUS_CANCELLED", 0)  # 0 = leave as is
    BASMN_SOURCE_FACEBOOK = _int("BASMN_SOURCE_FACEBOOK", 2)    # Messenger, ZevChat
    BASMN_SOURCE_INSTAGRAM = _int("BASMN_SOURCE_INSTAGRAM", 0)  # 0 = same as Facebook
    BASMN_SOURCE_WEBSITE = _int("BASMN_SOURCE_WEBSITE", 3)      # web chat, booking form
    BASMN_ASSIGNED = _int("BASMN_ASSIGNED", 1)                  # staff member who owns them
    # Perfex has no order object. When bas.mn adds a custom table for orders, put its
    # name here and orders are written there as well as a lead.
    BASMN_ORDERS_TABLE = os.getenv("BASMN_ORDERS_TABLE", "")
    # How often the server reads bas.mn back (calendar changes, price list).
    BASMN_PULL_SECONDS = _int("BASMN_PULL_SECONDS", 300)
    # Lets a scheduler (Vercel Cron, cron-job.org) call /api/basmn/sync. Vercel sends
    # CRON_SECRET by itself as "Authorization: Bearer ...". Empty = endpoint off.
    CRON_SECRET = os.getenv("CRON_SECRET", "")

    # Web chat widget (/api/chat). Only these origins may call it; the LLM key
    # never leaves the server. Empty list = the endpoint is turned off.
    WEB_CHAT_ORIGINS = [o.strip().rstrip("/") for o in
                        os.getenv("WEB_CHAT_ORIGINS",
                                  "https://ajiltai.tech,https://www.ajiltai.tech").split(",")
                        if o.strip()]
    WEB_CHAT_PER_10MIN = int(os.getenv("WEB_CHAT_PER_10MIN", "25"))
    WEB_CHAT_PER_DAY = int(os.getenv("WEB_CHAT_PER_DAY", "300"))

    # App
    # "demo" = FAQ demo for fictional businesses, "sales" = Ajilt-AI sales qualification flow
    BOT_MODE = os.getenv("BOT_MODE", "demo").strip().lower()
    BOT_NAME = os.getenv("BOT_NAME", "Ajilt-AI")
    # A Postgres URL (Vercel/Neon set DATABASE_URL) wins over the local SQLite file.
    DB_PATH = (os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL")
               or os.getenv("DB_PATH", "ajilt.db"))
    PRICING_PATH = os.getenv("PRICING_PATH", "config/pricing.yaml")
    # Serverless (Vercel): no background threads, and work must finish before the response.
    SERVERLESS = bool(os.getenv("VERCEL"))
    # Public https address of this app, used for image links Messenger must fetch.
    # Vercel provides VERCEL_PROJECT_PRODUCTION_URL; locally set PUBLIC_BASE_URL (e.g. ngrok).
    PUBLIC_BASE_URL = (os.getenv("PUBLIC_BASE_URL")
                       or (f"https://{os.getenv('VERCEL_PROJECT_PRODUCTION_URL')}"
                           if os.getenv("VERCEL_PROJECT_PRODUCTION_URL") else "")).rstrip("/")


settings = Settings()
