"""FastAPI server: the Meta webhook (Instagram + Facebook Page), the web chat
(/api/chat and the /chat demo page), n8n, and the staff bookings page."""
import hashlib
import re
import secrets
import time
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from .bot import ClinicBot
from .clinic import get_clinic, tr
from .config import settings
from .gcal import get_calendar
from .llm import get_llm
from .meta import _to_meta_messages, parse_events, send, send_typing, verify_signature
from .store import BOOKING_STATUSES, Store

store = Store(settings.DB_PATH)
clinic = get_clinic()
engine = ClinicBot(llm=get_llm(), store=store, clinic=clinic, calendar=get_calendar())

app = FastAPI(title=f"{settings.BOT_NAME} chatbot")
if settings.WEB_CHAT_ORIGINS:
    # Only the clinic's own website may call the chat endpoint from a browser.
    app.add_middleware(CORSMiddleware, allow_origins=settings.WEB_CHAT_ORIGINS,
                       allow_methods=["POST", "OPTIONS"], allow_headers=["Content-Type"])
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _process(channel: str, sender_id: str, user_input: str):
    send_typing(sender_id)
    session = store.get_session(sender_id, channel)
    session.channel = channel
    replies = engine.handle(session, user_input)
    send(sender_id, replies)


def _static_page(name: str) -> HTMLResponse:
    # version the asset URLs by file time so browsers never run a stale script
    html = (STATIC_DIR / name).read_text(encoding="utf-8")
    for asset in STATIC_DIR.iterdir():
        if asset.suffix in (".css", ".js"):
            html = html.replace(f"/static/{asset.name}", f"/static/{asset.name}?v={int(asset.stat().st_mtime)}")
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/chat")


@app.get("/health")
def health():
    return {"ok": True, "bot": settings.BOT_NAME, "llm": settings.LLM_ENABLED,
            "branches": len(clinic.branches), "services": len(clinic.services)}


# ---------- Meta webhook (Instagram + Facebook Page) ----------
@app.get("/webhook")
def verify(request: Request):
    """Meta webhook verification handshake."""
    params = request.query_params
    if (params.get("hub.mode") == "subscribe"
            and params.get("hub.verify_token") == settings.VERIFY_TOKEN):
        return Response(content=params.get("hub.challenge", ""), media_type="text/plain")
    return Response(content="verification failed", status_code=403)


@app.post("/webhook")
async def incoming(request: Request, background: BackgroundTasks):
    raw = await request.body()
    if not verify_signature(settings.APP_SECRET, raw,
                            request.headers.get("X-Hub-Signature-256")):
        return Response(content="bad signature", status_code=403)

    body = await request.json()
    for channel, sender_id, user_input in parse_events(body):
        if settings.SERVERLESS:
            # Work after the response may never run on serverless; replying first takes a few
            # seconds, well within Meta's webhook timeout.
            await run_in_threadpool(_process, channel, sender_id, user_input)
        else:
            # LLM replies take seconds; Meta retries if we don't answer fast, so reply after the 200.
            background.add_task(_process, channel, sender_id, user_input)

    return Response(content="EVENT_RECEIVED", media_type="text/plain")


# ---------- web chat (the /chat demo page, or a widget on the clinic's website) ----------
class ChatIn(BaseModel):
    session: str = ""
    message: str = ""


def _client_key(request: Request) -> str:
    """Hashed client IP — enough to rate-limit, not enough to identify anyone."""
    fwd = request.headers.get("x-forwarded-for", "")
    ip = fwd.split(",")[0].strip() or (request.client.host if request.client else "")
    # a website relaying its visitors through its own server names each visitor's IP
    relayed = request.headers.get("X-Client-IP", "").strip()
    if relayed and settings.WEB_CHAT_PROXY_TOKEN and secrets.compare_digest(
            request.headers.get("X-Proxy-Token", ""), settings.WEB_CHAT_PROXY_TOKEN):
        ip = relayed[:64]
    return "chat:" + hashlib.sha256(f"{settings.VERIFY_TOKEN}{ip}".encode()).hexdigest()[:24]


def _out(messages) -> list:
    return [{
        "text": m.text,
        "quick_replies": [{"title": q.title, "payload": q.payload} for q in (m.quick_replies or [])],
    } for m in messages]


@app.get("/chat", include_in_schema=False)
def chat_page():
    return _static_page("chat.html")


@app.post("/api/chat")
async def web_chat(body: ChatIn, request: Request):
    """Same engine as Messenger; the LLM key stays here on the server."""
    session_id = re.sub(r"[^A-Za-z0-9_-]", "", body.session)[:64]
    if len(session_id) < 8:
        raise HTTPException(400, "bad session")

    now = time.time()
    hits = await run_in_threadpool(store.rate_hit, _client_key(request))
    if len([t for t in hits if t > now - 600]) > settings.WEB_CHAT_PER_10MIN \
            or len(hits) > settings.WEB_CHAT_PER_DAY:
        raise HTTPException(429, "too many messages")

    session = store.get_session(f"web-{session_id}", "web")
    session.channel = "web"
    replies = await run_in_threadpool(engine.handle, session, (body.message or "").strip()[:500])
    return {"messages": _out(replies), "state": session.state, "lang": session.data.get("lang")}


# ---------- n8n (receives Meta's webhook, asks us for the reply, sends it) ----------
class N8nIn(BaseModel):
    channel: str = "messenger"
    sender_id: str = ""
    message: str = ""


@app.post("/api/n8n")
async def n8n_chat(body: N8nIn, request: Request):
    """One turn for a Messenger / Instagram visitor whose webhook lands in n8n.

    In:  {"channel": "messenger"|"instagram", "sender_id": "<PSID/IGSID>",
          "message": "<text, or the quick-reply / postback payload>"}
    Out: {"send": [<Send API message objects, in order>], "state": ..., "lang": ...}
    """
    if not settings.N8N_TOKEN:
        raise HTTPException(503, "n8n endpoint is not configured")
    if not secrets.compare_digest(request.headers.get("X-Bot-Token", ""), settings.N8N_TOKEN):
        raise HTTPException(403, "bad token")

    channel = body.channel if body.channel in ("messenger", "instagram") else ""
    sender_id = re.sub(r"[^0-9]", "", body.sender_id)[:32]
    if not channel or not sender_id:
        raise HTTPException(400, "channel and sender_id are required")

    session = store.get_session(sender_id, channel)
    session.channel = channel
    replies = await run_in_threadpool(engine.handle, session, (body.message or "").strip()[:2000])
    return {"send": [msg for m in replies for msg in _to_meta_messages(m)],
            "state": session.state, "lang": session.data.get("lang", "mn")}


# ---------- staff: bookings ----------
basic_auth = HTTPBasic(auto_error=False)


def admin_login(creds: HTTPBasicCredentials = Depends(basic_auth)):
    if not settings.ADMIN_PASSWORD:
        return
    ok = creds and secrets.compare_digest(creds.username, settings.ADMIN_USER) \
        and secrets.compare_digest(creds.password, settings.ADMIN_PASSWORD)
    if not ok:
        raise HTTPException(401, "login required", headers={"WWW-Authenticate": "Basic"})


@app.get("/bookings", include_in_schema=False, dependencies=[Depends(admin_login)])
def bookings_page():
    return _static_page("bookings.html")


@app.get("/api/bookings", dependencies=[Depends(admin_login)])
def bookings_data():
    return {
        "bookings": store.list_bookings(),
        "branches": [{"id": b["id"], "country": b["country"], "name": tr(b["name"], "mn")}
                     for b in clinic.branches],
        "services": {s["id"]: tr(s["name"], "mn") for s in clinic.services},
        "countries": {c["id"]: f"{c['flag']} {tr(c['name'], 'mn')}" for c in clinic.countries.values()},
        "statuses": BOOKING_STATUSES,
        "now": time.time(),
    }


class BookingStatus(BaseModel):
    status: str


@app.patch("/api/bookings/{booking_id}", dependencies=[Depends(admin_login)])
def bookings_set_status(booking_id: int, body: BookingStatus):
    try:
        found = store.set_booking_status(booking_id, body.status)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not found:
        raise HTTPException(404, "unknown booking")
    return {"ok": True}
