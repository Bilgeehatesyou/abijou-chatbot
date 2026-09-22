"""FastAPI webhook server for Meta (Instagram + Facebook Page), plus the
owner dashboard at /dashboard."""
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from .config import settings
from .llm import get_llm
from .meta import parse_events, send, send_typing, verify_signature
from .store import Store
from . import dashboard
from .gcal import get_calendar

store = Store(settings.DB_PATH)
calendar = get_calendar()
sync_worker = dashboard.SyncWorker(store, calendar)


@asynccontextmanager
async def lifespan(_app):
    # Serverless instances freeze between requests, so no background sync thread there;
    # the dashboard refreshes a business's calendar mirror on demand instead.
    if not settings.SERVERLESS:
        sync_worker.start()
    yield
    sync_worker.stop()


app = FastAPI(title="Ajilt-AI Chatbot", lifespan=lifespan)
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

from .conversation import Engine
from .pricing import Pricing

llm = get_llm()
if settings.BOT_MODE == "sales":
    engine = Engine(llm=llm, pricing=Pricing(settings.PRICING_PATH), store=store)
else:
    from .demo import DemoEngine
    from .router import AppRouter
    demo = DemoEngine(llm=llm, store=store, calendar=calendar)
    # Sales meetings book into Ajilt-AI's own calendar through the demo's BookingFlow.
    sales = Engine(llm=llm, pricing=Pricing(settings.PRICING_PATH), store=store, booking=demo.booking)
    engine = AppRouter(demo, sales, store)


def _process(channel: str, sender_id: str, user_input: str):
    send_typing(sender_id)
    session = store.get_session(sender_id, channel)
    session.channel = channel
    replies = engine.handle(session, user_input)
    send(sender_id, replies)


@app.get("/img/{business_id}/{sku}.png", include_in_schema=False)
def product_image(business_id: str, sku: str, lang: str = "mn"):
    """Generated product card (Messenger fetches these for catalog carousels)."""
    from .catalog import card_png
    png = card_png(business_id, sku, "en" if lang == "en" else "mn")
    if not png:
        raise HTTPException(404, "unknown product")
    return Response(png, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=86400, s-maxage=31536000, immutable"})


@app.get("/health")
def health():
    return {"ok": True, "bot": settings.BOT_NAME, "mode": settings.BOT_MODE}


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


# ---------- owner dashboard ----------
basic_auth = HTTPBasic(auto_error=False)


def dashboard_login(creds: HTTPBasicCredentials = Depends(basic_auth)):
    if not settings.DASHBOARD_PASSWORD:
        return
    ok = creds and secrets.compare_digest(creds.username, settings.DASHBOARD_USER)         and secrets.compare_digest(creds.password, settings.DASHBOARD_PASSWORD)
    if not ok:
        raise HTTPException(401, "login required", headers={"WWW-Authenticate": "Basic"})


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/dashboard")


@app.get("/dashboard", dependencies=[Depends(dashboard_login)])
@app.get("/dashboard/{business_id}", dependencies=[Depends(dashboard_login)])
def dashboard_page(business_id: str = ""):
    # version the asset URLs by file time so browsers never run a stale dashboard.js
    html = (STATIC_DIR / "dashboard.html").read_text(encoding="utf-8")
    for name in ("dashboard.js", "dashboard.css"):
        version = int((STATIC_DIR / name).stat().st_mtime)
        html = html.replace(f"/static/{name}", f"/static/{name}?v={version}")
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


@app.get("/api/dashboard", dependencies=[Depends(dashboard_login)])
def dashboard_businesses():
    return dashboard.business_list(store)


SERVERLESS_SYNC_SECONDS = 120


@app.get("/api/dashboard/{business_id}", dependencies=[Depends(dashboard_login)])
def dashboard_data(business_id: str):
    cfg = dashboard.booking_configs().get(business_id)
    if settings.SERVERLESS and calendar and cfg:
        synced_at = store.get_sync_state(business_id).get("synced_at") or 0
        if time.time() - synced_at > SERVERLESS_SYNC_SECONDS:
            try:
                dashboard.sync_business(store, calendar, business_id, cfg)
            except Exception as e:  # show the last mirror; the error is stored for the UI
                print(f"[dashboard] on-demand sync failed for {business_id}: {e}")
    data = dashboard.dashboard_payload(store, business_id)
    if not data:
        raise HTTPException(404, "unknown business")
    return data


# ---------- orders (order/stay requests collected by the chatbot) ----------
def _static_page(name: str) -> HTMLResponse:
    # version the asset URLs by file time so browsers never run a stale script
    html = (STATIC_DIR / name).read_text(encoding="utf-8")
    for asset in ("dashboard.css", "orders.css", "orders.js"):
        if (STATIC_DIR / asset).exists():
            version = int((STATIC_DIR / asset).stat().st_mtime)
            html = html.replace(f"/static/{asset}", f"/static/{asset}?v={version}")
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


@app.get("/orders", include_in_schema=False, dependencies=[Depends(dashboard_login)])
def orders_home():
    return RedirectResponse("/orders/wholesale")


@app.get("/orders/{business_id}", dependencies=[Depends(dashboard_login)])
def orders_page(business_id: str):
    return _static_page("orders.html")


@app.get("/api/orders/{business_id}", dependencies=[Depends(dashboard_login)])
def orders_data(business_id: str):
    biz = store.get_business(business_id)
    if not biz:
        raise HTTPException(404, "unknown business")
    return {
        "business": {"id": business_id, "name": {"mn": biz["name_mn"], "en": biz["name_en"]},
                     "emoji": biz["emoji"]},
        "orders": store.list_requests(business_id),
        "now": time.time(),
    }


class OrderStatus(BaseModel):
    status: str


@app.patch("/api/orders/{business_id}/{order_id}", dependencies=[Depends(dashboard_login)])
def orders_set_status(business_id: str, order_id: int, body: OrderStatus):
    try:
        found = store.set_request_status(business_id, order_id, body.status)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not found:
        raise HTTPException(404, "unknown order")
    return {"ok": True}


@app.post("/api/dashboard/{business_id}/sync", dependencies=[Depends(dashboard_login)])
def dashboard_sync(business_id: str):
    cfg = dashboard.booking_configs().get(business_id)
    if not cfg:
        raise HTTPException(404, "unknown business")
    if not calendar:
        raise HTTPException(503, "Google Calendar key not configured")
    try:
        count = dashboard.sync_business(store, calendar, business_id, cfg)
    except Exception as e:
        raise HTTPException(502, f"calendar sync failed: {e}")
    return {"events": count}
