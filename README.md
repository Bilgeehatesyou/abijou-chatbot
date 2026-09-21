# Ajilt-AI — Sales Qualification Chatbot

A conversational sales assistant for **Instagram DM + Facebook Page**. It
qualifies a lead (business type, company, size, branches), gives an instant
price quote, then either takes a callback number or books a meeting — saving a
full lead record either way.

Built as a **deterministic flow + quick-reply buttons**, with a **pluggable
LLM** used only to understand free-text answers. That keeps it reliable on a
small local model now, and gets smarter the moment you swap in a stronger one.

---

## Demo mode (current default)

`BOT_MODE=demo` turns the Page into a client demo: the visitor picks one of 10
fictional businesses (dental, school, college, learning center, course center,
wholesale, salon & spa, resort, apartment rental, event hall) and chats with it
as a customer. Answers come only from that business's generated profile + FAQs,
in Mongolian or English (starting language from the user's Facebook locale, then
whatever language they type — including Mongolian in Latin letters).

```bash
# 1. put your Gemini key + model in .env (see .env.example)
python -m app.demo_data generate   # writes data/demo/businesses/*.json (review them!)
python -m app.demo_data load       # loads them into the SQLite DB
python -m app.cli                  # try it in the terminal
```

**First contact:** visitors choose **🤖 Ajilt-AI** (price estimate, callback, meeting
booked into Ajilt-AI's own Google Calendar) or **🎬 Demo** (`app/router.py`). In the demo,
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
│   ├── conversation.py  # sales mode — state machine + quote + booking
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
