"""Central configuration, loaded from environment / .env."""
import os
from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


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

    # Booking calendar (Google Calendar via a service account). Optional: without a key,
    # bookings are kept in our own database and shown on /bookings. On hosts without a
    # secrets folder (Vercel), put the whole key JSON in GOOGLE_SERVICE_ACCOUNT_JSON.
    GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE",
                                            "secrets/google-service-account.json")
    GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    BOOKING_CALENDAR_SHARE_WITH = os.getenv("BOOKING_CALENDAR_SHARE_WITH", "")
    # The calendar's own zone; each branch books in its own zone (data/clinic.yaml).
    BOOKING_TIMEZONE = os.getenv("BOOKING_TIMEZONE", "Asia/Ulaanbaatar")

    # Online payment (app/payment.py). Off until a provider is wired in.
    PAYMENT_ENABLED = _bool("PAYMENT_ENABLED", False)

    # Staff pages (/bookings). Empty password = no login, for local use only.
    ADMIN_USER = os.getenv("ADMIN_USER", "admin")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
    # The n8n workflow that receives Meta's webhook sends this as X-Bot-Token
    # to /api/n8n. Empty = the endpoint is turned off.
    N8N_TOKEN = os.getenv("N8N_TOKEN", "")

    # Telegram alert to the clinic for every new booking. Empty = no alerts.
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

    # Web chat (/api/chat, and the /chat demo page). Pages on these origins may call it
    # from a browser; this server's own /chat page always can. The LLM key never leaves
    # the server.
    WEB_CHAT_ORIGINS = [o.strip().rstrip("/") for o in os.getenv("WEB_CHAT_ORIGINS", "").split(",")
                        if o.strip()]
    WEB_CHAT_PER_10MIN = int(os.getenv("WEB_CHAT_PER_10MIN", "25"))
    WEB_CHAT_PER_DAY = int(os.getenv("WEB_CHAT_PER_DAY", "300"))

    # A visitor who comes back after this many quiet hours starts a fresh conversation
    # (greeting, no half-finished booking from last week). 0 = never.
    SESSION_FRESH_HOURS = float(os.getenv("SESSION_FRESH_HOURS", "6"))

    # App
    BOT_NAME = os.getenv("BOT_NAME", "Abijou Clinic")
    # A Postgres URL (Vercel/Neon set DATABASE_URL) wins over the local SQLite file.
    DB_PATH = (os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL")
               or os.getenv("DB_PATH", "abijou.db"))
    # Serverless (Vercel): work must finish before the response.
    SERVERLESS = bool(os.getenv("VERCEL"))


settings = Settings()
