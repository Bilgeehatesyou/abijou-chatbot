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


settings = Settings()
