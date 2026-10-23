"""Ajilt-AI's AI sales agent: the bot's front door.

It greets the visitor, then leads the conversation like a friendly salesperson:
what the business does, where the manual work and the pain is, what they'd like
to automate, then a package with its price and the saving, and a gentle close
(a meeting or a callback). Every reply is written by the LLM from
data/ajilt_ai_facts.md; nothing here is a fixed questionnaire.

The model ends each reply with a hidden <data>{...}</data> block: what it has
learned about the customer (saved on the lead), which buttons to offer, and
whether to start booking a meeting. The forms that must be exact (meeting
slots, name + phone after "📞 Утсаа үлдээх") are the deterministic sales
Engine's, so a phone number is never lost to a model hiccup.
"""
import json
import re
from typing import List, Optional

from pathlib import Path

from . import crm
from .conversation import S as ENGINE_TEXT, STATES as ENGINE_STATES, interest_note
from .models import OutMsg, QuickReply, Session

FACTS_PATH = Path(__file__).resolve().parent.parent / "data" / "ajilt_ai_facts.md"
FACTS = FACTS_PATH.read_text(encoding="utf-8") if FACTS_PATH.exists() else ""

HISTORY = 16  # messages kept for the model (8 back-and-forths)
DATA_RE = re.compile(r"<data>(.*?)(?:</data>|$)", re.S)
LOOSE_DATA_RE = re.compile(r"(?:```(?:json)?\s*)?(\{[^{}]*\"buttons\"[^{}]*\})\s*(?:```)?\s*$", re.S)
# An 8-digit Mongolian number, optionally +976 and a space or dash in the middle.
PHONE_RE = re.compile(r"(?<!\d)(?<!\d[.,])(?:\+?976[\s-]?)?([6-9]\d{3})[\s-]?(\d{4})"
                      r"(?!\d|[.,]\d|\s*(?:₮|төг|сая|mnt))", re.I)
PROFILE_KEYS = ("org_name", "business_type", "industry", "pains", "wants", "employees",
                "branches", "plan", "contact_name")
BUSINESS_TYPES = ("Retail", "F&B", "Services", "Manufacturing", "Other")
PLANS = ("STARTER", "PRO", "PREMIUM", "CUSTOM")

TEXT = {
    "mn": {
        "greeting": "Сайн байна уу! 👋 Би Ажилт-AI — бизнесийн давтагддаг ажлыг AI-д "
                    "шилжүүлэхэд тусалдаг зөвлөх. Яг одоо тантай чатлаж байгаа би өөрөө ч манай "
                    "бүтээгдэхүүний нэг шүү 😊\n\nТанай байгууллага ямар үйл ажиллагаа явуулдаг вэ?",
        "offline": "Уучлаарай, яг одоо надад жаахан саатал гарлаа 🙏 Утасны дугаараа үлдээвэл "
                   "манай баг өөрөө холбогдоно, эсвэл 8605 1688 руу залгаарай.",
        "MEET": "📅 Уулзалт товлох",
        "CALL": "📞 Утсаа үлдээх",
        "DEMO": "🎬 Демо үзэх",
        "lang": "🌐 English",
        "booked": "(Уулзалт товлогдлоо.)",
        "called": "(Утасны дугаараа үлдээлээ.)",
    },
    "en": {
        "greeting": "Hi! 👋 I'm Ajilt-AI — I help businesses hand their repetitive work over to AI. "
                    "Fun fact: this chat you're in right now is one of our products 😊\n\n"
                    "What does your business do?",
        "offline": "Sorry, I hit a small hiccup just now 🙏 Leave your phone number and our team "
                   "will get back to you, or call us on 8605 1688.",
        "MEET": "📅 Book a meeting",
        "CALL": "📞 Leave my number",
        "DEMO": "🎬 Try the demo",
        "lang": "🌐 Монгол",
        "booked": "(The meeting is booked.)",
        "called": "(They left their phone number.)",
    },
}
PAYLOADS = {"MEET": "ACTION_BOOK", "CALL": "ACTION_CALLBACK", "DEMO": "MODE_DEMO"}
CHANNELS = {"web": "the chat on the ajiltai.tech website", "messenger": "Facebook Messenger",
            "instagram": "Instagram direct messages"}

SYSTEM = """You are Ajilt-AI's sales consultant, chatting with a potential customer in {channel}.
You are an AI and say so if asked; never pretend to be a person. This very chat is one of the
products you sell, which you can mention once, with a wink, when it helps.

PERSONALITY: warm, upbeat and genuinely curious about the customer's business; confident but
humble, with a little light humour. You talk like an experienced, friendly Mongolian salesperson,
not like a form or an FAQ page. Polite "та". At most one emoji per message. Never pushy or
desperate: no fake urgency, no invented discounts.

HOW YOU SELL. You lead the conversation; the customer should never have to wonder what to ask
or which button to press.
1. Understand the business: what they do, who their customers are, how customers reach them
   (Facebook, Instagram, phone, walk-in).
2. Find the pain, ONE question per message. For example: "Хамгийн их цаг авдаг гар ажил юу вэ?",
   "Өдөрт хэр олон мессеж ирдэг вэ, оройн цагаар хэн хариулдаг вэ?", "Юуг нь автоматжуулмаар
   байна?". React to the answer with real interest and say it back in their words, e.g.
   "Аа, шөнө ирсэн захиалга өглөө болтол хүлээдэг юм байна. Тэр чинь алдагдаж буй орлого шүү дээ."
3. Ask the size (employees, branches) only when you need it to recommend a package.
4. Recommend ONE package (or a few modules) that fits what they told you: its monthly price, the
   one-time setup fee, and a concrete saving tied to their situation (which work and which
   salaries it takes over), from the facts.
5. Close gently: propose the next step, a 45-minute meeting (online or at their office) where the
   team shows it set up for their business, or their name and phone number so the team calls.
   If they hesitate, find out why (price? timing? need to ask the boss?) and answer that with the
   value arguments in the facts. Ask for the close at most once every two or three messages, and
   keep giving value in between.
- A direct question gets a short, direct answer first (prices included), then you carry on leading
  with one question.
- Don't ask again what WHAT WE KNOW already says.
- If they want to see the bot working for a business like theirs, offer the demo.

STYLE: 1-4 short sentences, under about 400 characters. Plain text: no Markdown, no ** or #.
Answer in the customer's language: Mongolian in any script (also Latin letters, like "sain bn uu",
"une hed ve") gets Mongolian in Cyrillic; English gets English. Use only the facts and prices
below; never invent prices, features, clients or promises. If you don't know, say the team will
clarify it at the meeting.

PRICES NOW (monthly; if the facts differ, these win): {prices}
Booking a meeting in this chat: {can_book}

WHAT WE KNOW ABOUT THIS CUSTOMER: {known}
{notes}
FACTS:
{facts}

After your message, on its own last line, write the data block, for example:
<data>{{"org_name": null, "business_type": "Services", "industry": "dental clinic, 2 dentists",
"pains": "answers Facebook messages by hand at night", "wants": "booking and reminders",
"employees": 6, "branches": 0, "plan": "STARTER", "contact_name": null, "buttons": [],
"action": ""}}</data>
- Fill only what the customer actually said (null otherwise); keep earlier values.
- business_type: one of Retail, F&B, Services, Manufacturing, Other.
- plan: the package you recommended (STARTER, PRO, PREMIUM, CUSTOM), else null.
- buttons: up to 2 of "MEET", "CALL", "DEMO", only when this message offers that next step;
  [] while you are still asking about their business.
- action: "book" only when the customer clearly asks or agrees to set a meeting time now.
"""


def find_phone(text: str) -> Optional[str]:
    m = PHONE_RE.search(text or "")
    return m.group(1) + m.group(2) if m else None


def _clean(value, key: str):
    """The model's value for one profile field, or None if it isn't usable."""
    if value in (None, "", "null", [], {}):
        return None
    if key in ("employees", "branches"):
        try:
            n = int(str(value).split()[0].replace(",", ""))
        except (ValueError, IndexError):
            return None
        return n if 0 <= n < 100000 else None
    if key == "business_type":
        return value if value in BUSINESS_TYPES else None
    if key == "plan":
        value = str(value).upper()
        return value if value in PLANS else None
    return str(value).strip()[:200] or None


def parse_reply(raw: str):
    """(text the customer sees, data dict) from the model's raw reply."""
    data = {}
    m = DATA_RE.search(raw or "")
    if m:
        body = m.group(1).strip().strip("`")
        body = body[body.find("{"):body.rfind("}") + 1]
        try:
            data = json.loads(body) if body else {}
        except ValueError:
            data = {}
        raw = raw[:m.start()]
    else:                         # the block without its tags, e.g. in a ```json fence
        m = LOOSE_DATA_RE.search(raw or "")
        if m:
            try:
                data = json.loads(m.group(1))
            except ValueError:
                data = {}
            raw = raw[:m.start()]
    text = (raw or "").replace("**", "").replace("```", "").strip()
    return text, data if isinstance(data, dict) else {}


class SalesAgent:
    def __init__(self, llm, engine, store, pricing):
        self.llm = llm
        self.engine = engine      # conversation.Engine: meeting booking + callback form
        self.store = store
        self.pricing = pricing

    # ---- entry points ----
    def greet(self, session: Session, lang: str) -> List[OutMsg]:
        t = TEXT[lang]
        session.data = {"lang": lang, "chat": [{"role": "assistant", "content": t["greeting"]}]}
        session.state = "CHAT"
        buttons = [QuickReply(t["DEMO"], "MODE_DEMO"),
                   QuickReply(t["lang"], "LANG_EN" if lang == "mn" else "LANG_MN")]
        return [OutMsg(t["greeting"], buttons)]

    def start_closing(self, session: Session, lang: str, source: str, action: str) -> List[OutMsg]:
        """The demo tour's last buttons: straight to a callback or a meeting, keeping what
        the agent already knows."""
        keep = self._known(session.data)
        out = self.engine.start_closing(session, lang, source, action)
        session.data.update({k: v for k, v in keep.items() if k not in session.data})
        return out

    def handle(self, session: Session, text: str) -> List[OutMsg]:
        d = session.data
        lang = d.get("lang", "mn")
        if session.state in ("ASK_CONTACT_NAME", "ASK_PHONE") and not find_phone(text) \
                and ("?" in text or len(text) > 40):
            session.state = "CHAT"               # a question, not the name or number we asked for
        if session.state.startswith("BOOK_") or session.state in ENGINE_STATES:
            return self._form(session, lang, text)
        if text == "ACTION_BOOK" and self.engine._can_book():
            return self._form(session, lang, text, start="book")
        if text == "ACTION_CALLBACK":
            return self._form(session, lang, text, start="call")
        session.state = "CHAT"
        return self._chat(session, lang, text)

    # ---- the conversation ----
    def _chat(self, session: Session, lang: str, text: str) -> List[OutMsg]:
        d = session.data
        notes = []
        phone = find_phone(text)
        if phone and phone != d.get("phone"):
            d["phone"] = phone
            self._save_lead(session, lang, "callback", "Утсаа үлдээсэн")
            notes.append(f"NOTE: the customer just gave their phone number {phone}. It is saved and the "
                         "team will call during working hours (Mon-Fri 10:00-18:00). Thank them warmly"
                         + ("." if d.get("contact_name") else " and ask their name."))
        elif d.get("phone"):
            notes.append(f"NOTE: their phone number {d['phone']} is already saved; don't ask for it again.")
        if d.get("slot"):
            notes.append(f"NOTE: they already booked a meeting for {d['slot'][:16].replace('T', ' ')}.")

        history = d.get("chat", [])
        messages = ([{"role": "system", "content": self._system(session, lang, notes)}]
                    + history[-HISTORY:] + [{"role": "user", "content": text}])
        raw = self.llm.chat(messages, temperature=0.7)
        reply, data = parse_reply(raw or "")
        if not reply:
            t = TEXT[lang]
            return [OutMsg(t["offline"], self._buttons(lang, ["CALL", "MEET", "DEMO"]))]

        name_before = d.get("contact_name")
        for key in PROFILE_KEYS:
            value = _clean(data.get(key), key)
            if value is not None:
                d[key] = value
        self._apply_plan(d)
        d["chat"] = (history + [{"role": "user", "content": text},
                                {"role": "assistant", "content": reply}])[-HISTORY:]
        # A name that arrives after the number goes onto the same lead.
        if d.get("phone") and not phone and d.get("contact_name") and not name_before:
            self._save_lead(session, lang, "callback", "Нэрээ хэлсэн")

        out = [OutMsg(reply, self._buttons(lang, data.get("buttons") or []))]
        if data.get("action") == "book" and self.engine._can_book() and not d.get("slot"):
            out[-1].quick_replies = None
            out += self._form(session, lang, "ACTION_BOOK", start="book")
        return out

    def _system(self, session: Session, lang: str, notes: List[str]) -> str:
        known = {k: session.data[k] for k in PROFILE_KEYS + ("phone",) if session.data.get(k) is not None}
        return SYSTEM.format(
            channel=CHANNELS.get(session.channel, "a chat"),
            prices=self._prices(),
            can_book="yes (button MEET opens the calendar)" if self.engine._can_book()
            else "no; take their name and phone and the team arranges the time",
            known=json.dumps(known, ensure_ascii=False) if known else "nothing yet",
            notes="\n".join(notes) + ("\n" if notes else ""),
            facts=FACTS,
        ) + f"\nThe chat's language setting is {'Mongolian' if lang == 'mn' else 'English'}."

    def _prices(self) -> str:
        parts = []
        for tier in ("STARTER", "PRO", "PREMIUM"):
            _, price, _ = self.pricing.quote(*self._size_for(tier), "Other")
            if price:
                parts.append(f"{tier} {price:,}₮")
        return ", ".join(parts) + ", 200+ employees: individual quote"

    def _size_for(self, tier: str):
        """An (employees, branches) pair that lands on the tier, to read its price."""
        for t in self.pricing.tiers:
            if t["name"] == tier:
                return t.get("max_employees") or 1, 0
        return 1, 0

    def _apply_plan(self, d: dict):
        plan = d.get("plan")
        if not plan:
            return
        d["tier"] = plan
        if plan == "CUSTOM":
            d["quote"] = "custom"
        else:
            _, price, _ = self.pricing.quote(*self._size_for(plan), d.get("business_type") or "Other")
            d["quote"] = price if price else "custom"

    def _buttons(self, lang: str, names) -> Optional[List[QuickReply]]:
        t = TEXT[lang]
        out = []
        for name in names:
            name = str(name).upper()
            if name == "MEET" and not self.engine._can_book():
                name = "CALL"
            if name in PAYLOADS and name in t and all(b.payload != PAYLOADS[name] for b in out):
                out.append(QuickReply(t[name], PAYLOADS[name]))
        return out[:3] or None

    # ---- exact forms (meeting slots, callback) run by the sales Engine ----
    def _form(self, session: Session, lang: str, text: str, start: str = "") -> List[OutMsg]:
        keep = self._known(session.data)
        before = (session.data.get("slot"), session.data.get("phone"))
        if start == "book":
            out = self.engine._start_meeting(session, lang)
        elif start == "call" and session.data.get("phone") and session.data.get("contact_name"):
            session.state = "CHAT"               # we already have both: nothing to fill in
            d = session.data
            return [OutMsg(ENGINE_TEXT[lang]["callback_done"].format(name=d["contact_name"],
                                                                     phone=d["phone"]))]
        elif start == "call":
            session.state = "ASK_CONTACT_NAME"
            out = [OutMsg(ENGINE_TEXT[lang]["ask_name"])]
        else:
            out = self.engine._route(session, text)
        session.data.update({k: v for k, v in keep.items() if k not in session.data})
        if session.state == "DONE":              # the form finished: back to the conversation
            session.state = "CHAT"
            t = TEXT[lang]
            after = (session.data.get("slot"), session.data.get("phone"))
            note = t["booked"] if after[0] != before[0] else t["called"] if after[1] != before[1] else ""
            if note:
                session.data["chat"] = (session.data.get("chat", [])
                                        + [{"role": "assistant", "content": note}])[-HISTORY:]
            if out and out[-1].quick_replies:
                out[-1].quick_replies = self._buttons(lang, ["DEMO"])
        return out

    @staticmethod
    def _known(d: dict) -> dict:
        return {k: d[k] for k in PROFILE_KEYS + ("chat", "tier", "quote", "phone") if k in d}

    def _save_lead(self, session: Session, lang: str, path: str, interest: str):
        d = session.data
        lead_id = self.store.save_lead(session, path=path)
        crm.enqueue(self.store, "lead", lead_id,
                    {"interest": interest_note(d, f"AI борлуулагч: {interest}"), "lang": lang})
