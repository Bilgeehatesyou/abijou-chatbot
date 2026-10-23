# Ajilt-AI — Sales Qualification Chatbot

A conversational sales assistant for **Instagram DM + Facebook Page**. It
qualifies a lead (business type, company, size, branches), gives an instant
price quote, then either takes a callback number or books a meeting — saving a
full lead record either way. a

Built as a **deterministic flow + quick-reply buttons**, with a **pluggable
LLM** used only to understand free-text answers. That keeps it reliable on a
small local model now, and gets smarter the moment you swap in a stronger one.
         
--- 

## Demo mode (current default).     

`BOT_MODE=demo` turns the Page into a client demo: the visitor picks one of 11
businesses (dental, school, college, learning center, course center,
wholesale, salon & spa, resort, apartment rental, event hall, real estate agency) and chats with it
as a customer. Answers come only from that business's generated profile + FAQs,
in Mongolian or English (always starts in Mongolian, then follows whatever language
they type — including Mongolian in Latin letters — or the 🌐 button)

```bash
# 1. put your Gemini key + model in .env (see .env.example)
python -m app.demo_data generate   # writes data/demo/businesses/*.json (review them!)
python -m app.demo_data load       # loads them into the SQLite DB
python -m app.cli                  # try it in the terminal
```

**First contact:** an AI sales agent (`app/agent.py`) greets the visitor and leads the
talk like a friendly salesperson: what the business does, where the manual work is, what
they'd like to automate, then a package with its price and saving, and a gentle close: a
meeting booked into Ajilt-AI's own Google Calendar, or a callback. It answers from
`data/ajilt_ai_facts.md` and the prices in `config/pricing.yaml`; what it learns (business,
pains, wants, size, package) goes onto the lead in bas.mn, and a phone number typed in chat
is saved straight away. **🎬 Demo** is a chip on the greeting and something the agent
offers when it fits (`app/router.py`). In the demo,
**🎬 Тур эхлүүлэх** starts a guided tour (`app/tour.py`, texts in `data/demo/tours.yaml`):
a "💡 Ajilt-AI" guide comments on each step — FAQ, language, unknown question,
booking/request, owner's view, extras — and ends by handing over to the sales flow.
Businesses without time slots (wholesale, resort, rental) take order/stay requests
(`app/request_flow.py`, `request:` in seeds.yaml). Set the Page's Get Started
button once with `python -m app.meta`.

Three demo businesses are **real** (`fictional: false` in seeds.yaml, built from their
public websites; prices are estimates): Mayflower dental, Global Leadership University
(replaces the college) and MCC Foods (wholesale). MCC Foods has a picture catalog
(`app/catalog.py`, `data/demo/catalogs/wholesale.json`: 80 real MCC items + 300 demo
items) — product questions show Messenger carousels of generated product cards
(`/img/<business>/<sku>.png`, drawn with Noto Sans in `app/fonts/`, SIL OFL), and each
card's 📝 button starts an order. Rebuild the catalog with `python -m app.catalog build`.

The real estate agency (Өргөө Хаус, fictional) sells and rents in two real Khan-Uul
complexes, **Gerlug Vista** and **Hunnu 2222** (104 made-up units: 2- to 6-room flats, heated
parking and garages), plus 169 example flats in 23 other areas — Zaisan, Khurd, Yarmag, Nisekh,
the centre, Sansar, the numbered microdistricts (1, 3, 4, 10–16-р хороолол), Amgalan, Sharkhad,
Tolgoit, Nalaikh and more — in `data/demo/catalogs/real_estate.json` (`app/listings.py`). Each
is ✅ available, 🔴 sold, ⏳ reserved or 🔴 rented. Units carry the
block ("40-р байр"), Hunnu's phase ("2-р ээлж", "Плас"), floor as storeys/unit ("16/9
давхарт"), condition, certificate, and how a buyer can pay (cash, bank loan, the 8% mortgage,
trade-in).

- Questions like «Гэрлүг Вистад 3 өрөө», «Хүннү 2222 2-р ээлж», «Зайсанд 2 өрөө», «13-р
  хороолол», «700 сая хүртэл», «бартер 3 өрөө» show listing cards with size in m², price, price per m² and monthly rent.
  **ℹ Дэлгэрэнгүй** lists every offer and its terms, then asks whether to view it or what would
  suit better; **📅 Үзэх цаг авах** books a viewing at the property's address.
- A unit that doesn't exist («40-р байр 20 давхар», «Хүннү 6 өрөө») gets "not found" and the
  closest available units (same complex, nearest rooms, block and floor).
- A sold or rented listing says so and offers the same type **on another floor of the same
  building**, then **another block of the same complex**, then **nearby** (within 4 km). With
  none, the bot asks which complex, then which type (`PREFA_<area>` → `PREF_<area>_<type>`).
- **🔎 Байр сонгох** asks rooms → complex → how you pay (`WANTR_` → `WANTC_` → `WANTP_`) and
  shows what fits, cheapest first.
- The LLM gets a summary of every complex and neighbourhood, a one-line index of the units in
  the places that come up, and full details of the ones on screen.

Unit numbers, prices and statuses are made up (prices follow 2024–2026 public ads); the profile
and FAQs were written by hand from the listings, so the numbers agree.

New or edited files in `data/demo/businesses/` load into the database by themselves when
the app starts (`sync_businesses`), and a bookable business without a Google Calendar gets
one on first use, shared with everyone in `BOOKING_CALENDAR_SHARE_WITH` (comma-separated).
So adding a demo business needs only a deploy.

### Our own meetings — `/meetings`

Everything booked **with Ajilt-AI itself**, from both directions, in one list:
the chatbot's sales flow (`bookings`, `business_id = 'ajilt_ai'`) and the
ajiltai.tech booking form (`site_bookings`). Each row keeps its source label,
moves through new → confirmed → done / cancelled, and overlapping meetings are
flagged so a website booking landing on a chatbot one is visible.

The website posts to `POST /api/site-booking` with an `X-Ajilt-Token` header
(`SITE_BOOKING_TOKEN`, same value as `AJILT_TOKEN` in the site's `config.php`).
The payload is validated again here, then written into Ajilt-AI's Google Calendar
in tangerine, so website and chatbot meetings never double-book silently.

### The chat bubble on ajiltai.tech — `/api/chat`
-
The website's widget (`assets/chat.js` + `chat.css` there) posts
`{session, message}` here and gets back the same `OutMsg` list Messenger would:
text, quick replies and product cards. It runs the **same AppRouter**, so the
site and Messenger behave identically — and the model key never leaves this
server. The endpoint is public, so it is fenced in: CORS limited to
`WEB_CHAT_ORIGINS`, a hashed-IP sliding window (`WEB_CHAT_PER_10MIN`,
`WEB_CHAT_PER_DAY`) in the `rate_limits` table, sanitised session ids and a
500-character cap per message.

### ZevChat — `/api/zev`

ZevChat (our partner's Messenger/Instagram tool) can't host a conversation by
itself, but its **HTTP API** block can call one. A flow sends
`{subscriber_id, message}` here, we answer one turn, and its response mapping
drops our `reply` into a subscriber field the flow then sends.

Two things learned by testing against the real thing, both handled in
`app/zev.py`:

* a mapped field is dropped entirely when the value contains a **line break**
  (emoji are fine), so the reply goes out on one line separated by `·`;
* an unfilled template variable arrives as the literal `#LEAD_USER_LAST_CHAT#`
  and would otherwise be read as English text.

Quick replies become a numbered list and `"2"` is resolved back to that
button's payload, so a text-only channel still drives the whole engine.

### n8n — `/api/n8n`

The Page and Instagram can also be served through n8n: Meta's webhook points at the
n8n workflow *ajiltAI – FB + Instagram Chatbot*, which skips chats a staff member
took over from the inbox, posts `{channel, sender_id, message}` here with an
`X-Ajilt-Token` header (`N8N_TOKEN`), and sends back the `send` list — ready-made
Send API messages with quick replies and cards — in order. The session key is the
same as `/webhook`'s, so a conversation carries on whichever door Meta uses.

### bas.mn (Perfex CRM) — `app/crm.py`

With `BASMN_URL` + `BASMN_API_KEY` set, everything the bot collects goes into bas.mn,
and bas.mn is read back. Our database stays the source of truth; nothing the CRM
does can cost a visitor their answer.

**Bot → bas.mn.** Each save also queues a job in `crm_outbox`; a background worker
sends it at once (inline on Vercel) and retries failures with backoff for about a day.

| In the bot | In bas.mn |
|---|---|
| sales lead (callback / meeting) | **Lead**: name, phone, company, quote as *lead value*, tags, language |
| any chatbot booking | Lead + **calendar event** whose description links to the lead |
| ajiltai.tech booking form | Lead (with e-mail) + orange calendar event |
| order / stay request | Lead with the items (+ a row in `BASMN_ORDERS_TABLE` once it exists) |
| /meetings: confirmed / done | ✅ / ☑ in front of the event title |
| /meetings: cancelled | event deleted, note on the lead (optional status) |
| /orders: status change | note on the lead |

A person is one lead: leads are found by phone before one is created. Source,
status and owner come from `BASMN_SOURCE_*`, `BASMN_STATUS_*`, `BASMN_ASSIGNED`.
Demo businesses go in too, so the tour can show a booking landing in a real CRM,
but marked: `[DEMO]` titles, grey events, a `demo`  tag.

**bas.mn → bot.** Every `BASMN_PULL_SECONDS` the bot reads the calendar and Items:
meetings staff add in bas.mn block those times in Ajilt-AI's booking flow; our
meetings deleted there become *cancelled* here, moved ones move (in Google Calendar
too); Items named `STARTER…`, `PRO…`, `PREMIUM…` override the prices in
`config/pricing.yaml`. It is polling because bas.mn's "Event Webhooks" fire only on
API traffic, never when staff edit a lead or event.

On Vercel there is no background worker: queued jobs go out inline, the /meetings
page catches up when opened, and a scheduler should call `GET /api/basmn/sync`
with `Authorization: Bearer $CRON_SECRET` (Vercel Cron sends that header itself).

```bash
python -m app.crm check                # read-only: key works? staff / calendar / items
python -m app.crm status               # queue, failures, last pull   (also GET /api/basmn/status)
python -m app.crm flush | pull | retry
python -m app.crm fix-old-leads        # leads the first sync sent as "Google"/"Customer"; --apply to fix
python -m pytest tests                 # fake bas.mn, no network (pip install pytest)
```

What the live API taught us (all handled in `app/basmn.py`): auth is the
`authtoken` header; an empty list answers **404** `"No data were found"`;
`POST /api/calendar` also requires `reminder_before`, `reminder_before_type`,
`isstartnotified` and `public`; a created event returns no id, so it is matched
back by title and start; `GET /api/calendar` takes no parameters.

Businesses are defined in `data/demo/seeds.yaml`. Regenerate one with
`python -m app.demo_data generate --only salon --force`, then `load` again.
Set `BOT_MODE=sales` to get the original sales flow back.

---

## What's in the box

```
ajilt-ai/
├── app/
│   ├── main.py          # FastAPI webhook (Meta: Messenger + Instagram)
│   ├── demo.py          # demo mode — business picker + FAQ answers
│   ├── demo_data.py     # generate (LLM) + load the demo FAQ data
│   ├── router.py        # front door: the sales agent, the demo, home/language
│   ├── agent.py         # AI sales agent — leads the conversation, saves the lead
│   ├── conversation.py  # sales forms (meeting slots, callback) + the old BOT_MODE=sales flow
│   ├── meta.py          # Meta send/receive + signature check
│   ├── llm.py           # pluggable LLM (local OpenAI-compatible endpoint)
│   ├── pricing.py       # config-driven pricing engine
│   ├── store.py         # SQLite: sessions + leads (swap for a CRM later)
│   ├── models.py        # Session, OutMsg, QuickReply
│   ├── config.py        # env settings
│   └── cli.py           # terminal simulator — test without Meta
├── config/pricing.yaml  # tiers + price matrix (edit these numbers)
├── data/demo/           # seeds.yaml + generated businesses/*.json
├── .env.example
└── requirements.txt
```

---

## 1. Install

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## 2. Run a local model (Ollama example)

```bash
# https://ollama.com — then:
ollama pull llama3.1:8b
ollama serve      # exposes an OpenAI-compatible API on http://localhost:11434/v1
```

The defaults in `.env` already point at this. Any OpenAI-compatible server
works (LM Studio, llama.cpp `server`, vLLM). You can also set
`LLM_ENABLED=false` to run with **zero** model calls — the flow still works,
it just uses keyword matching instead of the model to categorize free text.

## 3. Test the whole conversation in your terminal

```bash
python -m app.cli
```

No Meta setup, no tunnels. Type answers; when buttons show, type the number,
the button text, or free text. Try both the "leave my number" and "book a
meeting" paths. This drives the **exact same engine** the live bot uses.

---

## 4. Connect to Instagram + Facebook

You need a Facebook Page, an Instagram **professional/business** account linked
to that Page, and a Meta developer app.

1. **Create a Meta app** at developers.facebook.com → add the **Messenger** and
   **Instagram** products.
2. **Get a Page Access Token** (Messenger settings → your Page) and put it in
   `.env` as `META_PAGE_ACCESS_TOKEN`. Copy the **App Secret** (Settings →
   Basic) into `META_APP_SECRET`.
3. **Pick a verify token** — any string — and set the same value in `.env`
   (`META_VERIFY_TOKEN`) and in the webhook screen.
4. **Expose your server** so Meta can reach it. Locally:
   ```bash
   uvicorn app.main:app --port 8000
   # in another terminal:
   ngrok http 8000
   ```
   Use the `https://…ngrok…` URL.
5. **Add the webhook** in the Messenger and Instagram product settings:
   - Callback URL: `https://YOUR-URL/webhook`
   - Verify token: the value from step 3
   - Subscribe the Page to the `messages` and `messaging_postbacks` fields
     (and the equivalent Instagram messaging fields).
6. **Link the Instagram account** to the Page in the Instagram product settings
   and subscribe it.

> **Note on API version:** `GRAPH_API_VERSION` in `.env` defaults to `v21.0`.
> Check the current version in your Meta dashboard and set it to match, since
> Meta rotates versions and deprecates old ones.

Instagram and Messenger arrive on the **same** `/webhook`; the code tells them
apart by the payload's `object` field and replies through the same Send API.

---

## 5. Edit the pricing

Everything lives in `config/pricing.yaml` — tier thresholds, the branch-bump
rule, and the price for each (tier × business type) cell. No code changes. The
placeholder numbers are there to be replaced with your real ones.

---

## 6. Swapping the LLM later

When you're ready for a stronger model, either:
- point `LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY` at any OpenAI-compatible
  hosted model, **or**
- add a new class in `app/llm.py` implementing `classify(text, labels)` and
  return it from `get_llm()`.

Nothing in the flow changes.

---

## Still TODO (the open items from the requirements)

- **Real pricing numbers**, business-type list, and tier cutoffs.
- **Calendar integration** — `_create_calendar_event()` in `conversation.py`
  and `_slot_options()` are stubs returning mock times. Wire these to Google
  Calendar / Outlook (read availability, create the event, invite the rep).
- **CRM handoff** — `store.save_lead()` writes to SQLite. Swap or add a push to
  Bitrix24 / a sheet / your DB, plus a real-time notification to the sales team.
- **What Ajilt-AI sells** — the offering text in the quote message is generic;
  drop in the real product framing.
