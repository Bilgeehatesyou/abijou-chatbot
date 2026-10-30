"""FastAPI server: the Meta webhook (Instagram + Facebook Page), the web chat
(/api/chat and the /chat demo page), n8n, and the staff bookings page."""
import hashlib
import re
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from . import crm
from .booking import SlotTaken, normalize_phone
from .bot import ClinicBot
from .clinic import clinic, tr
from .config import settings
from .gcal import get_calendar
from .llm import get_llm
from .models import OutMsg
from .meta import _to_meta_messages, parse_events, send, send_typing, verify_signature
from .store import BOOKING_STATUSES, Store

store = Store(settings.DB_PATH)
engine = ClinicBot(llm=get_llm(), store=store, clinic=clinic, calendar=get_calendar())
crm_worker = crm.CrmWorker(store)


@asynccontextmanager
async def lifespan(_app):
    # Serverless instances freeze between requests: there the queue is flushed inline.
    if not settings.SERVERLESS:
        crm_worker.start()
    yield
    crm_worker.stop()


app = FastAPI(title=f"{settings.BOT_NAME} chatbot", lifespan=lifespan)
if settings.WEB_CHAT_ORIGINS:
    # Only the clinic's own website may call the chat endpoint from a browser.
    app.add_middleware(CORSMiddleware, allow_origins=settings.WEB_CHAT_ORIGINS,
                       allow_methods=["POST", "OPTIONS"], allow_headers=["Content-Type"])
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# Words that hand a conversation to a person (besides the "Talk to staff" button).
HUMAN_WORDS = ("гомдол", "буруу", "хүнтэй ярих", "complaint", "human", "불만", "상담원")


def converse(session, channel: str, user_input: str) -> list:
    """One turn, logged for the CRM inbox. While a person has the conversation the bot stays quiet."""
    sender_id = session.sender_id
    if user_input:
        store.log_message(sender_id, channel, "in", "patient", user_input)
    conv = store.get_conversation(sender_id) or {}
    if float(conv.get("bot_paused_until") or 0) > time.time():
        return []
    replies = engine.handle(session, user_input)
    low = user_input.lower()
    if user_input == "MENU_HUMAN" or any(w in low for w in HUMAN_WORDS):
        store.set_conversation(sender_id, channel, needs_human=1,
                               bot_paused_until=time.time() + settings.HUMAN_PAUSE_HOURS * 3600)
    for m in replies:
        store.log_message(sender_id, channel, "out", "bot", m.text,
                          {"quick_replies": [q.title for q in (m.quick_replies or [])]} if m.quick_replies else None)
    return replies


def _process(channel: str, sender_id: str, user_input: str):
    send_typing(sender_id)
    session = store.get_session(sender_id, channel)
    session.channel = channel
    replies = converse(session, channel, user_input)
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


# ---------- the clinic website's booking form ----------
# The form shows /api/catalog and /api/slots and its server books through /api/bookings, so a
# form booking is checked, saved, sent to bas.mn and alerted exactly like a chat one.
SLOTS_AHEAD_DAYS = 60


@app.get("/api/catalog")
def catalog(response: Response):
    """Branches and treatments with their prices, as clinic.yaml has them (no private data)."""
    response.headers["Cache-Control"] = "public, max-age=300"
    pick = lambda d, keys: {k: d[k] for k in keys if k in d}
    return {
        "countries": [pick(c, ("id", "flag", "name", "tz", "currency", "time_note")) for c in clinic.countries.values()],
        "categories": [pick(c, ("id", "emoji", "name")) for c in clinic.data.get("categories", [])],
        "branches": [pick(b, ("id", "country", "name", "address", "hours_text", "note")) for b in clinic.branches],
        "services": [{**pick(s, ("id", "category", "minutes", "name", "short", "price", "price_note")),
                      "price_from": bool(s.get("options"))} for s in clinic.services],
        "contacts": {k: v["phone"] for k, v in clinic.data.get("contacts", {}).items()},
    }


def _branch_service(branch_id: str, service_id: str):
    branch, service = clinic.branch(branch_id), clinic.service(service_id)
    if not branch or not service:
        raise HTTPException(400, "unknown branch or service")
    return branch, service, ZoneInfo(clinic.country_of(branch)["tz"])


@app.get("/api/slots")
def slots(branch: str, service: str, date: str):
    """Free start times (HH:MM, the branch's own time) for one treatment on one day."""
    b, s, tz = _branch_service(branch, service)
    try:
        day = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD")
    today = datetime.now(tz).date()
    if not today <= day <= today + timedelta(days=SLOTS_AHEAD_DAYS):
        return {"date": date, "tz": str(tz), "slots": []}
    starts = engine.booking.free_starts(b, s, day)
    return {"date": date, "tz": str(tz), "slots": [f"{t:%H:%M}" for t in starts]}


class WebBookingIn(BaseModel):
    name: str
    phone: str
    branch: str
    service: str
    date: str               # YYYY-MM-DD in the branch's own time
    time: str               # HH:MM, one of /api/slots
    lang: str = "mn"
    email: str = ""
    note: str = ""


@app.post("/api/bookings", status_code=201)
async def web_booking(body: WebBookingIn, request: Request):
    if not settings.WEB_BOOKING_TOKEN:
        raise HTTPException(503, "website booking is not configured")
    if not secrets.compare_digest(request.headers.get("X-Booking-Token", ""), settings.WEB_BOOKING_TOKEN):
        raise HTTPException(403, "bad token")
    b, s, tz = _branch_service(body.branch, body.service)
    name, phone = " ".join(body.name.split())[:80], normalize_phone(body.phone)
    if len(name) < 2:
        raise HTTPException(400, "name")
    if not phone:
        raise HTTPException(400, "phone")
    try:
        start = datetime.strptime(f"{body.date} {body.time}", "%Y-%m-%d %H:%M").replace(tzinfo=tz)
    except ValueError:
        raise HTTPException(400, "date/time")
    free = await run_in_threadpool(engine.booking.free_starts, b, s, start.date())
    if start not in free:
        raise HTTPException(409, "slot not free")
    note = " · ".join(x for x in (body.email.strip()[:120], body.note.strip()[:500]) if x)
    try:
        row, _ = await run_in_threadpool(
            lambda: engine.booking.save(b, s, start, name=name, phone=phone,
                                        lang=body.lang if body.lang in ("mn", "en", "ko") else "mn",
                                        channel="website", sender_id=f"website:{phone}", note=note))
    except SlotTaken:
        raise HTTPException(409, "slot not free")
    return {"id": row["id"], "branch": b["id"], "service": s["id"], "start": row["start_at"],
            "price": row["price"], "currency": row["currency"]}


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
    replies = await run_in_threadpool(converse, session, "web", (body.message or "").strip()[:500])
    return {"messages": _out(replies), "state": session.state, "lang": session.data.get("lang")}


@app.get("/api/chat/updates")
def web_chat_updates(session: str, since: int = 0):
    """Staff replies for a web visitor (the widget polls this). The session id is the secret."""
    session_id = re.sub(r"[^A-Za-z0-9_-]", "", session)[:64]
    if len(session_id) < 8:
        raise HTTPException(400, "bad session")
    return {"messages": store.messages_after(f"web-{session_id}", max(0, since))}


# ---------- staff (CRM inbox) ----------
def _staff_auth(request: Request):
    if not settings.STAFF_API_TOKEN:
        raise HTTPException(503, "staff api is not configured")
    if not secrets.compare_digest(request.headers.get("X-Staff-Token", ""), settings.STAFF_API_TOKEN):
        raise HTTPException(403, "bad token")


class StaffReplyIn(BaseModel):
    sender_id: str
    channel: str
    text: str
    staff_user_id: int | None = None


class StaffReleaseIn(BaseModel):
    sender_id: str
    channel: str = ""


@app.post("/api/staff/reply", dependencies=[Depends(_staff_auth)])
def staff_reply(body: StaffReplyIn):
    text = body.text.strip()[:2000]
    if not body.sender_id or not text:
        raise HTTPException(400, "sender_id and text are required")
    # A person answered: the bot keeps quiet; nobody is waiting any more.
    store.set_conversation(body.sender_id, body.channel, needs_human=0,
                           bot_paused_until=time.time() + settings.HUMAN_PAUSE_HOURS * 3600)
    mid = store.log_message(body.sender_id, body.channel, "out", "staff", text, staff_user_id=body.staff_user_id)
    if body.channel in ("messenger", "instagram"):
        # Web visitors read it from /api/chat/updates; Meta channels get it pushed.
        send(body.sender_id, [OutMsg(text=text)])
    return {"id": mid}


@app.post("/api/staff/release", dependencies=[Depends(_staff_auth)])
def staff_release(body: StaffReleaseIn):
    store.set_conversation(body.sender_id, body.channel, needs_human=0, bot_paused_until=0)
    return {"ok": True}


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
    replies = await run_in_threadpool(converse, session, channel, (body.message or "").strip()[:2000])
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
    # bas.mn: appointment title/colour; "done" also makes the invoice
    crm.enqueue(store, "status", booking_id, {"status": body.status})
    return {"ok": True}


@app.get("/api/crm/status", dependencies=[Depends(admin_login)])
def crm_status():
    return crm.status(store)


@app.post("/api/basmn/sync")
async def basmn_sync(request: Request):
    """What the background worker does on a server, for serverless hosting where nothing runs
    between requests: n8n calls this every ~5 minutes. Retries the queued sends that are due,
    then reads staff changes back from bas.mn (deleted, moved, ИРСЭН, paid)."""
    if not settings.BASMN_SYNC_TOKEN:
        raise HTTPException(503, "sync endpoint is not configured")
    if not secrets.compare_digest(request.headers.get("X-Sync-Token", ""), settings.BASMN_SYNC_TOKEN):
        raise HTTPException(403, "bad token")
    sent = await run_in_threadpool(crm.flush, store, 20)
    try:
        changes = await run_in_threadpool(crm.pull, store)
    except Exception as e:
        raise HTTPException(502, f"bas.mn read failed: {type(e).__name__}: {e}")
    return {"sent": sent, "changes": changes, "customers": store.crm_state_get("customer_count")}
