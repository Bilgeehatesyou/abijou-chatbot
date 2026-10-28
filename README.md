# Abijou Clinic — chatbot (demo)

The virtual assistant of **Abijou Clinic** (dermatology and aesthetics) for
**Instagram DM, Facebook Messenger and the website**, in **Mongolian, Korean and
English**. It explains treatments and prices, lists the branches (4 in Mongolia,
8 in Korea), answers free questions, and **books appointments** at any branch.
Online payment comes later; the hook is ready (`app/payment.py`).

Built from the ajilt-ai chatbot: same Meta webhook, LLM layer, Google Calendar
and booking engine, without the demo picker, sales agent, tours or CRM.

> **Demo data.** The acne/redness treatments (NeoBeam, Gold PTT, Select Acne,
> Excel-V, Rejuran) come from the clinic's own description; every price, branch
> address, phone number and policy in `data/clinic.yaml` is made up. Replace them
> before going live.

## Try it

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows (source .venv/bin/activate elsewhere)
pip install -r requirements.txt
copy .env.example .env            # then put your Gemini/OpenAI key in LLM_API_KEY
uvicorn app.main:app --port 8010
```

- **http://localhost:8010/chat** — the chat, as a patient sees it (same engine as Instagram).
- **http://localhost:8010/bookings** — staff view of every booking: filter by country or
  branch, set confirmed / done / cancelled / no-show. Set `ADMIN_PASSWORD` before exposing it.
- `python -m app.cli` — the same conversation in the terminal.
- `python -m pytest tests` — no network needed.

Without an LLM key (`LLM_ENABLED=false`) everything still works except free-form
answers, which fall back to keyword matching against the FAQ and treatment names.

## What the bot does

| | |
|---|---|
| Greeting | Menu: 📅 Book · 💆 Treatments & prices · 📍 Branches · 🎁 Offers · ☎ Contact · 👩‍⚕️ Staff · 🌐 language |
| Treatments | 8 categories → each treatment with MNT and KRW prices, packages, options, and a 📅 button |
| Branches | Mongolia / Korea → addresses, hours, which branches have a Mongolian-speaking coordinator |
| Free questions | The LLM answers only from `data/clinic.yaml`, in the patient's language, never diagnoses, and can start a booking itself (`[BOOK:service:branch]`) |
| Booking | treatment → country → branch → day → time → name → phone → confirm |

**Languages.** Starts in Mongolian; each message's own language takes over (Hangul →
Korean, Cyrillic or Latin-typed Mongolian → Mongolian, otherwise English); the 🌐 buttons
pin one.

**Booking rules.** Each branch books in its own time zone (Ulaanbaatar or Seoul) and its
own hours, prices are in that country's currency, and `capacity` patients can be treated at
once. Slots already taken (in our database, and in Google Calendar when configured) aren't
offered; a cancelled booking frees its slot. Phones: Mongolian 8 digits or Korean 010.
A booking can send a Telegram alert to the coordinators (`TELEGRAM_*`).

## Editing the clinic's information

Everything is in **`data/clinic.yaml`**: services (with `short` button labels ≤ 20
characters, `price: {MNT, KRW}`, `packages`, `options`), categories, branches
(`country`, `hours`, `capacity`, `note`), promotions, policies and FAQs — each text in
`mn`, `en` and `ko`. Restart after editing. Keep at most 12 services (Messenger shows 13
quick replies, one is ✖ Cancel); `tests/test_bot.py` checks the file.

## Connect Instagram + Facebook

1. Meta app with **Messenger** and **Instagram** products; Page Access Token →
   `META_PAGE_ACCESS_TOKEN`, App Secret → `META_APP_SECRET`, any string → `META_VERIFY_TOKEN`.
2. Expose the server (`ngrok http 8010` locally) and set the webhook to
   `https://YOUR-URL/webhook` with that verify token; subscribe `messages` and
   `messaging_postbacks` (and the Instagram equivalents).
3. `python -m app.meta` sets the Get Started button and greeting (MN / EN / KO).

Or route Meta through n8n: the workflow posts `{channel, sender_id, message}` to
`/api/n8n` with `X-Bot-Token: $N8N_TOKEN` and sends back the `send` list.

## bas.mn (Perfex CRM) — patients, appointments, invoices

With `BASMN_URL` + `BASMN_API_KEY` in `.env`, the clinic runs on bas.mn and the bot keeps it
up to date (`app/crm.py`, client with the API's quirks in `app/basmn.py`):

| When | In bas.mn |
|---|---|
| a patient books in the chat | **customer** (found by phone, else created with Салбар / Хэл / Суваг) + **calendar appointment** `Каннам · Excel-V лазер · Б. Хулан` |
| staff set the status on `/bookings` | the appointment's colour: blue booked, green came, grey cancelled / no-show |
| the visit is marked **came** (on `/bookings`, or `ИРСЭН` at the start of the appointment title in bas.mn) | an **invoice**: the treatment from the price list, ₮ or ₩ by branch, that country's payment modes, branch + booking number in its custom fields. `/bookings` links to it. |
| the patient pays (QPay closes it; staff record card / cash) | `/bookings` shows the invoice as paid |
| staff delete an appointment in bas.mn | the booking is cancelled, its slot free again |
| staff move an appointment in bas.mn | the booking moves |
| staff add an appointment by hand (phone, walk-in), with the branch name in it | that time is busy in the chat |

Writes are queued (`crm_outbox`) and retried, so a slow or full bas.mn never loses a booking;
staff edits are read every `BASMN_PULL_SECONDS` (bas.mn doesn't send webhooks for them).
On Vercel nothing runs between requests, so n8n calls `POST /api/basmn/sync` every 5 minutes
with `X-Sync-Token: $BASMN_SYNC_TOKEN`: it resends what is due and reads the staff edits.

The bot's invoices are numbered from `invoice_numbers_from` in `data/basmn.yaml` (900001):
bas.mn requires a number and ignores a prefix, so this keeps them apart from staff's own.
With `customer_limit` / `customer_warn_at` set there, the log warns as the plan's customer
cap nears (company1: 100).

```bash
python -m app.crm check     # read-only: key, custom fields, counts
python -m app.crm status    # queue, failures, last read
python -m app.crm flush | pull | retry
```

**What bas.mn's API can't do** (found by testing; worth raising with bas.mn): payments are
always dated *today*, whatever date is sent; recording a payment and updating an invoice
answer "failed" although both are saved; customer search errors; only the newest invoice can
be deleted; currencies can't be read. And company1's plan stops at **100 customers**.

### Using it for another clinic

1. `data/clinic.yaml`: that clinic's treatments, prices, branches, FAQs.
2. In its bas.mn: payment modes (Setup → Finance → Payment Modes), currencies, and the custom
   fields Салбар / Хэл / Суваг (customers) and Салбар / Захиалгын дугаар (invoices).
   The price list can be loaded from clinic.yaml (see `tools/`).
3. `data/basmn.yaml`: that tenant's currency and payment-mode ids (check a recorded payment's
   mode name: they aren't always in creation order) and the custom field labels.
4. `.env`: its `BASMN_URL` / `BASMN_API_KEY`, then `python -m app.crm check`.

### Demo month

`python -m tools.basmn_demo plan | generate | addresses | redo-invoices | delete` fills a
bas.mn with a month of made-up patients, appointments, invoices and payments from clinic.yaml,
all marked `DEMO DATA`, and removes them again (ids in `basmn_demo.json`).

## The clinic website's booking form

The website shows the bot's own data and books through it, so a form booking gets the same
free-slot check, bas.mn appointment and staff alert as a chat one:

| | |
|---|---|
| `GET /api/catalog` | branches, treatments, prices, categories from `clinic.yaml` (public, cached 5 min) |
| `GET /api/slots?branch=&service=&date=YYYY-MM-DD` | free start times (`HH:MM`, the branch's own time) |
| `POST /api/bookings` | `{name, phone, branch, service, date, time, lang, email?, note?}` with `X-Booking-Token: $WEB_BOOKING_TOKEN` → 201 `{id, start, price, currency}`; 409 when the time was just taken |

Bookings from the form have channel `website`; the email and the patient's note are kept in
`note` and shown in the bas.mn appointment and the Telegram alert.

## Google Calendar (optional)

Service-account key in `secrets/google-service-account.json`, your Google address in
`BOOKING_CALENDAR_SHARE_WITH`, then `python -m app.gcal setup`. All bookings go into one
calendar tagged with their branch; events staff add there block that branch (or every
branch, when untagged).

## Payment (later)

`app/payment.py` → `request_deposit(booking)` is called after every booking. Return a
payment link (QPay for Mongolia, a Korean PG for Korea) and set `PAYMENT_ENABLED=true`: the
link is shown in the confirmation and the booking is marked `pending`. A provider webhook
then calls `store.set_payment(id, "paid")`.

## Layout

```
app/
  main.py      FastAPI: /webhook (Meta), /api/chat + /chat, /api/n8n, /bookings
  bot.py       conversation: menus, language, LLM answers, hand-off to booking
  booking.py   booking flow, slots per branch / time zone / capacity
  clinic.py    loads data/clinic.yaml; prices, branch texts, the model's knowledge
  lang.py      Mongolian / Korean / English detection
  payment.py   payment hook (not built yet)
  crm.py       chatbot <-> bas.mn sync: queue, invoices, reading staff changes back
  basmn.py     bas.mn API client (and its quirks)
  store.py     SQLite or Postgres: sessions, bookings
  gcal.py      Google Calendar (optional)   notify.py  Telegram alerts
  llm.py       any OpenAI-compatible model  meta.py    Messenger / Instagram send API
  static/      chat and bookings pages
data/clinic.yaml   everything the bot knows
data/basmn.yaml    this clinic's bas.mn ids (currencies, payment modes, custom fields)
tools/basmn_demo.py  a month of demo data in bas.mn, and its removal
```
