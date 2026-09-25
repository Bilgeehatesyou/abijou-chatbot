"""Ajilt-AI's own sales conversation (the "🤖 Ajilt-AI" path, and where the demo
tour hands over at the end).

A deterministic, bilingual state machine: qualify the business (type, name, what
it does, size, branches) -> price estimate from config/pricing.yaml -> either
leave a number (name + phone saved as a lead) or book a meeting into Ajilt-AI's
real sales calendar through the same BookingFlow the demo businesses use.
The LLM is only used to map a free-text business description to a category.
"""
import re
from typing import List, Optional

from . import crm
from .booking import BUTTON_PAYLOAD_RE, ajilt_ai_business, normalize_phone
from .models import OutMsg, QuickReply, Session

# Internal ids must match the columns in pricing.yaml.
BUSINESS_TYPES = [
    ("Retail", {"mn": "🛍 Худалдаа", "en": "🛍 Retail"}),
    ("F&B", {"mn": "🍽 Хоол, кафе", "en": "🍽 Food & drink"}),
    ("Services", {"mn": "💼 Үйлчилгээ", "en": "💼 Services"}),
    ("Manufacturing", {"mn": "🏭 Үйлдвэрлэл", "en": "🏭 Manufacturing"}),
    ("Other", {"mn": "➕ Бусад", "en": "➕ Other"}),
]
BTYPE_IDS = [b for b, _ in BUSINESS_TYPES]

# Keyword fallback if the LLM is off/unsure.
KEYWORDS = {
    "F&B": ["restaurant", "cafe", "coffee", "food", "bar", "bakery", "canteen", "kitchen",
            "ресторан", "кафе", "кофе", "хоол", "зоог", "талх", "гуанз"],
    "Retail": ["shop", "store", "retail", "boutique", "mart", "market", "sell", "wholesale",
               "дэлгүүр", "худалдаа", "бараа", "бөөний", "маркет", "зардаг"],
    "Services": ["service", "agency", "consult", "salon", "clinic", "studio", "repair", "cleaning",
                 "school", "hotel", "dental", "үйлчилгээ", "салон", "эмнэлэг", "шүд", "сургууль",
                 "сургалт", "зочид буудал", "засвар", "цэвэрлэгээ"],
    "Manufacturing": ["factory", "manufactur", "produce", "production", "plant", "assembl", "workshop",
                      "үйлдвэр", "үйлдвэрлэл", "цех"],
}

YES = {"yes", "y", "yeah", "yep", "sure", "have", "we do", "true", "1",
       "тийм", "тиймээ", "бий", "байгаа", "tiim", "bii", "bgaa"}
NO = {"no", "n", "nope", "none", "nah", "0", "false", "үгүй", "байхгүй", "ugui", "baihgui"}

S = {
    "mn": {
        "greeting": "Сайн байна уу! Би Ажилт-AI 👋 Хэдхэн асуултаар танай бизнест тохирох "
                    "үнийн санал гаргаж өгье.",
        "ask_type": "Ямар төрлийн бизнес эрхэлдэг вэ?",
        "ask_org": "Ойлголоо. Байгууллагынхаа нэрийг бичнэ үү.",
        "ask_industry": "Яг ямар үйл ажиллагаа явуулдаг вэ? Товчхон бичээрэй.",
        "ask_employees": "Хэдэн ажилтантай вэ?",
        "need_number": "Тоогоор бичнэ үү — хэдэн ажилтантай вэ?",
        "ask_has_branches": "Салбартай юу?",
        "ask_branch_count": "Хэдэн салбартай вэ?",
        "need_branch_number": "Тоогоор бичнэ үү — хэдэн салбартай вэ?",
        "yes": "Тийм", "no": "Үгүй",
        "quote_custom": "Баярлалаа! Танай хэмжээнд «{tier}» багц тохирох бөгөөд үнийг тусгайлан "
                        "тооцдог. Манай баг танд тохирсон санал бэлдье.",
        "quote": "«{btype}» чиглэлийн «{tier}» багцын урьдчилсан үнэ:\n\n➡️ сард {price}\n\n"
                 "Дараа нь юу хийх вэ?",
        "choose": "Сонгоно уу:",
        "call_button": "📞 Утсаа үлдээх",
        "meet_button": "📅 Уулзалт товлох",
        "ask_name": "Таны нэрийг бичнэ үү.",
        "ask_phone": "Холбогдох утасны дугаараа бичнэ үү.",
        "bad_phone": "Утасны дугаар буруу байна. 8 оронтой дугаараа бичнэ үү, жишээ нь 99112233.",
        "callback_done": "Баярлалаа, {name}! ✅ Манай баг {phone} дугаарт удахгүй залгана.",
        "closing_call": "Гоё! Манай баг танд залгаж, танай бизнест яг ийм чатбот хэрхэн "
                        "тохирохыг танилцуулна.",
        "closing_meet": "Гоё! Манай багтай 45 минутын уулзалт товлоё — танай бизнест тохируулсан "
                        "демо үзүүлнэ.",
        "meeting_done": "Уулзалтад баярлалаа! Манай менежер урьдчилан холбогдож, хаана уулзахаа тохирно.",
        "demo_button": "🎬 Демо үзэх",
        "home_button": "🏠 Эхлэл",
        "price_label": "{price:,} ₮",
    },
    "en": {
        "greeting": "Hi! I'm Ajilt-AI 👋 A few quick questions and I'll put together a price for your "
                    "business.",
        "ask_type": "What type of business do you run?",
        "ask_org": "Got it. What's your company's name?",
        "ask_industry": "What exactly does your business do? A few words is fine.",
        "ask_employees": "How many employees do you have?",
        "need_number": "Please send a number — how many employees?",
        "ask_has_branches": "Do you have branches?",
        "ask_branch_count": "How many branches?",
        "need_branch_number": "Please send a number — how many branches?",
        "yes": "Yes", "no": "No",
        "quote_custom": "Thanks! Based on your size you'd be on our “{tier}” plan, which is priced "
                        "individually. Our team will prepare an offer for you.",
        "quote": "Here's your estimate for a “{btype}” business on the “{tier}” plan:\n\n"
                 "➡️ {price} / month\n\nWhat would you like to do next?",
        "choose": "Choose one:",
        "call_button": "📞 Leave my number",
        "meet_button": "📅 Book a meeting",
        "ask_name": "What's your name?",
        "ask_phone": "What's the best number to reach you on?",
        "bad_phone": "That doesn't look like a phone number. Please send 8 digits, e.g. 99112233.",
        "callback_done": "Thanks, {name}! ✅ Our team will call you on {phone} shortly.",
        "closing_call": "Great! Our team will call you and show how a chatbot like this fits your business.",
        "closing_meet": "Great! Let's book a 45-minute meeting with our team — we'll show a demo "
                        "set up for your business.",
        "meeting_done": "Thanks for booking! Our manager will contact you beforehand to confirm where we meet.",
        "demo_button": "🎬 Try the demo",
        "home_button": "🏠 Home",
        "price_label": "{price:,} MNT",
    },
}


def _qr(pairs) -> List[QuickReply]:
    return [QuickReply(title=t, payload=p) for t, p in pairs]


def _parse_int(text: str) -> Optional[int]:
    m = re.search(r"\d+", text.replace(",", ""))
    return int(m.group()) if m else None


def _classify_business(text: str, llm) -> str:
    """Map free text to a BTYPE id. LLM first, keywords fallback, else Other."""
    guess = llm.classify(text, BTYPE_IDS)
    if guess in BTYPE_IDS:
        return guess
    low = text.lower()
    for label, words in KEYWORDS.items():
        if any(w in low for w in words):
            return label
    return "Other"


class Engine:
    def __init__(self, llm, pricing, store, booking=None):
        self.llm = llm
        self.pricing = pricing
        self.store = store
        self.booking = booking  # BookingFlow with the "ajilt_ai" meeting config

    # ---- public entrypoints ----
    def handle(self, session: Session, user_input: str) -> List[OutMsg]:
        out = self._route(session, (user_input or "").strip())
        self.store.save_session(session)
        return out

    def start_closing(self, session: Session, lang: str, source: str, action: str) -> List[OutMsg]:
        """Entry from the demo tour's last step: skip qualifying, go straight to
        a callback (LEAD_CALL) or a meeting booking (LEAD_MEET)."""
        session.data = {"lang": lang, "industry": f"demo: {source}" if source else "demo"}
        s = S[lang]
        if action == "LEAD_MEET" and self._can_book():
            out = self._start_meeting(session, lang, intro=s["closing_meet"])
        else:
            session.state = "ASK_CONTACT_NAME"
            out = [OutMsg(s["closing_call"]), OutMsg(s["ask_name"])]
        self.store.save_session(session)
        return out

    # ---- helpers ----
    def _can_book(self) -> bool:
        return bool(self.booking and self.booking.is_bookable("ajilt_ai"))

    def _action_buttons(self, lang: str) -> List[QuickReply]:
        s = S[lang]
        pairs = [(s["call_button"], "ACTION_CALLBACK")]
        if self._can_book():
            pairs.append((s["meet_button"], "ACTION_BOOK"))
        return _qr(pairs)

    def _done_buttons(self, lang: str) -> List[QuickReply]:
        s = S[lang]
        return _qr([(s["demo_button"], "MODE_DEMO"), (s["home_button"], "HOME")])

    def _type_buttons(self, lang: str) -> List[QuickReply]:
        return _qr([(labels[lang], f"BTYPE_{bid}") for bid, labels in BUSINESS_TYPES])

    @staticmethod
    def _match_type(text: str) -> Optional[str]:
        if text.startswith("BTYPE_") and text[6:] in BTYPE_IDS:
            return text[6:]
        low = text.lower()
        for bid, labels in BUSINESS_TYPES:
            if any(low == label.lower() or low == label.split(" ", 1)[-1].lower()
                   for label in labels.values()):
                return bid
        return None

    def _show_quote(self, session: Session, lang: str) -> List[OutMsg]:
        d, s = session.data, S[lang]
        tier, price, _currency = self.pricing.quote(
            int(d["employees"]), int(d.get("branches", 0)), d["business_type"])
        d["tier"] = tier
        d["quote"] = "custom" if price is None else price
        btype = dict(BUSINESS_TYPES)[d["business_type"]][lang].split(" ", 1)[-1]
        if price is None:
            body = s["quote_custom"].format(tier=tier)
        else:
            body = s["quote"].format(btype=btype, tier=tier, price=s["price_label"].format(price=price))
        session.state = "CHOOSE_ACTION"
        return [OutMsg(body), OutMsg(s["choose"], self._action_buttons(lang))]

    def _start_meeting(self, session: Session, lang: str, intro: str = "") -> List[OutMsg]:
        msgs, done = self.booking.start(session, lang, ajilt_ai_business())
        out = ([OutMsg(intro)] if intro else []) + msgs
        return self._after_meeting_step(session, lang, out, done)

    def _after_meeting_step(self, session, lang, msgs: List[OutMsg], done: bool) -> List[OutMsg]:
        if not done:
            return msgs
        booked = session.data.pop("last_booking", None)
        session.state = "DONE"
        if booked and booked["status"] in ("booked", "no_calendar"):
            d = session.data
            d.update(contact_name=booked["name"], phone=booked["phone"], slot=booked["start"])
            self.store.save_lead(session, path="booking")
            self._push_to_crm(session, "Уулзалт товлосон")
            msgs.append(OutMsg(S[lang]["meeting_done"]))
        if msgs:
            msgs[-1].quick_replies = self._done_buttons(lang)
        return msgs

    def _push_to_crm(self, session: Session, interest: str):
        """Our own sales leads belong in our own CRM too."""
        d = session.data
        crm.push_lead(
            name=d.get("contact_name", ""), phone=d.get("phone", ""),
            business=d.get("org_name", ""), channel=session.channel, interest=interest,
            note=" · ".join(filter(None, [
                d.get("industry", ""),
                f"{d['employees']} ажилтан" if d.get("employees") else "",
                f"{d['branches']} салбар" if d.get("branches") else "",
            ])),
        )

    # ---- the state machine ----
    def _route(self, session: Session, text: str) -> List[OutMsg]:
        d = session.data
        lang = d.get("lang", "mn")
        s = S[lang]
        state = session.state

        if state.startswith("BOOK_") and self._can_book():
            msgs, done = self.booking.handle(session, lang, ajilt_ai_business(), text)
            return self._after_meeting_step(session, lang, msgs, done)

        if state in (None, "", "START", "DONE") or state not in STATES:
            session.data = {"lang": lang}
            session.state = "ASK_BUSINESS_TYPE"
            return [OutMsg(s["greeting"]), OutMsg(s["ask_type"], self._type_buttons(lang))]

        if state == "ASK_BUSINESS_TYPE":
            choice = self._match_type(text)
            if choice in (None, "Other"):
                choice = _classify_business(text, self.llm) if text and not text.startswith("BTYPE_") else "Other"
            d["business_type"] = choice
            session.state = "ASK_ORG_NAME"
            return [OutMsg(s["ask_org"])]

        if state == "ASK_ORG_NAME":
            if not text:
                return [OutMsg(s["ask_org"])]
            d["org_name"] = text
            session.state = "ASK_INDUSTRY"
            return [OutMsg(s["ask_industry"])]

        if state == "ASK_INDUSTRY":
            if not text:
                return [OutMsg(s["ask_industry"])]
            d["industry"] = text
            session.state = "ASK_EMPLOYEES"
            return [OutMsg(s["ask_employees"])]

        if state == "ASK_EMPLOYEES":
            n = _parse_int(text)
            if n is None:
                return [OutMsg(s["need_number"])]
            d["employees"] = n
            session.state = "ASK_HAS_BRANCHES"
            return [OutMsg(s["ask_has_branches"], _qr([(s["yes"], "BR_YES"), (s["no"], "BR_NO")]))]

        if state == "ASK_HAS_BRANCHES":
            low = text.lower()
            if text == "BR_YES" or low in YES:
                session.state = "ASK_BRANCH_COUNT"
                return [OutMsg(s["ask_branch_count"])]
            if text == "BR_NO" or low in NO:
                d["branches"] = 0
                return self._show_quote(session, lang)
            return [OutMsg(s["ask_has_branches"], _qr([(s["yes"], "BR_YES"), (s["no"], "BR_NO")]))]

        if state == "ASK_BRANCH_COUNT":
            n = _parse_int(text)
            if n is None:
                return [OutMsg(s["need_branch_number"])]
            d["branches"] = n
            return self._show_quote(session, lang)

        if state == "CHOOSE_ACTION":
            low = text.lower()
            if text == "ACTION_BOOK" and self._can_book():
                return self._start_meeting(session, lang)
            if text == "ACTION_CALLBACK" or any(k in low for k in ("call", "number", "phone", "утас", "залга")):
                session.state = "ASK_CONTACT_NAME"
                return [OutMsg(s["ask_name"])]
            return [OutMsg(s["choose"], self._action_buttons(lang))]

        if state == "ASK_CONTACT_NAME":
            if not text or BUTTON_PAYLOAD_RE.match(text):
                return [OutMsg(s["ask_name"])]
            d["contact_name"] = text
            session.state = "ASK_PHONE"
            return [OutMsg(s["ask_phone"])]

        if state == "ASK_PHONE":
            phone = normalize_phone(text)
            if not phone:
                return [OutMsg(s["bad_phone"])]
            d["phone"] = phone
            self.store.save_lead(session, path="callback")
            self._push_to_crm(session, "Залгахыг хүссэн")
            session.state = "DONE"
            return [OutMsg(s["callback_done"].format(name=d.get("contact_name", ""), phone=phone),
                           self._done_buttons(lang))]

        session.state = "START"
        return self._route(session, "")


STATES = {"ASK_BUSINESS_TYPE", "ASK_ORG_NAME", "ASK_INDUSTRY", "ASK_EMPLOYEES", "ASK_HAS_BRANCHES",
          "ASK_BRANCH_COUNT", "CHOOSE_ACTION", "ASK_CONTACT_NAME", "ASK_PHONE"}
