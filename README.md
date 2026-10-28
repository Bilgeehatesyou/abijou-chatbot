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
  store.py     SQLite or Postgres: sessions, bookings
  gcal.py      Google Calendar (optional)   notify.py  Telegram alerts
  llm.py       any OpenAI-compatible model  meta.py    Messenger / Instagram send API
  static/      chat and bookings pages
data/clinic.yaml   everything the bot knows
```
