"""FAQ demo engine: the visitor picks one of the fictional businesses, then the
bot answers as that business's receptionist using only its profile + FAQs.

Language: the user's Facebook locale sets the starting language, then each
message's own language takes over (Cyrillic -> Mongolian, Latin-script
Mongolian -> Mongolian, otherwise English). The LLM is told to answer in the
language of the last message, so the heuristic here only drives UI strings.
"""
import re
import time
from typing import Callable, List, Optional

from .booking import T as BOOK_TEXT, BookingFlow, wants_booking
from .demo_data import load_seeds
from .models import OutMsg, QuickReply, Session
from .request_flow import RequestFlow
from .tour import TourGuide

# "start"/"эхлэх" belong to the app router (back to the Ajilt-AI / demo choice).
MENU_WORDS = {"menu", "цэс", "tses", "demo", "демо"}
HISTORY_TURNS = 6
PAYLOAD_RE = re.compile(r"^(MENU|HOME|BOOK|BOK|BCANCEL|REQ|[A-Z]+_\w+)$")
CHAT_STATES = ("PICK_INDUSTRY", "PICK_KIND", "CHAT")
BOOK_TOKEN = "[BOOK]"
# Free text like a name ("Bat") must not flip the conversation language.
NO_LANG_DETECT_STATES = ("BOOK_NAME", "BOOK_PHONE", "REQ_NAME", "REQ_PHONE",
                         "ASK_ORG_NAME", "ASK_CONTACT_NAME", "ASK_PHONE", "ASK_EMPLOYEES",
                         "ASK_BRANCH_COUNT")

AMBIGUOUS_LATIN = {"hi", "hello", "hey", "ok", "okay", "k", "thanks", "thx", "bye",
                   "yes", "no", "yep", "lol", "pls", "please", "sorry", "wow"}

# Common words when Mongolian is typed in Latin letters.
LATIN_MN = {
    "sain", "sn", "bainuu", "bnuu", "bnu", "baina", "bna", "bn", "uu", "yu", "ve", "we",
    "hed", "hediin", "hediig", "haana", "hezee", "hen", "une", "vne", "unetei", "tulbur",
    "tolbor", "tsag", "tsagt", "tsagiin", "bolno", "bolomj", "bolohuu", "zahialga",
    "zahialah", "zahialj", "hayag", "bairshil", "utas", "dugaar", "medeelel", "avah",
    "awah", "avmaar", "heregtei", "baigaa", "bga", "bgaa", "bdag", "baidag", "yaj",
    "yaaj", "tanai", "tanaid", "manai", "ta", "bid", "shud", "shudnii", "emneleg",
    "surguuli", "surgalt", "zaal", "turees", "buudal", "amraltiin", "undsen",
    "hyamdral", "hymdral", "ajilladag", "ajillah", "odor", "udur", "margaash",
    "unuudur", "onoodor", "hurgelt", "hvrgelt", "bayarlalaa", "bayrlalaa", "zaa",
    "tegvel", "tegwel", "oor", "uur", "hudaldaj", "shaardlagatai", "yamar",
}

INDUSTRY_KEYWORDS = {
    "dental": ["шүд", "dental", "dentist", "tooth", "teeth", "shud"],
    "education": ["сургууль", "боловсрол", "коллеж", "сургалт", "курс", "school",
                  "college", "course", "education", "surguuli", "surgalt", "kurs"],
    "wholesale": ["бөөн", "wholesale", "buun", "distribut", "trade"],
    "salon": ["салон", "спа", "гоо", "үс", "массаж", "salon", "spa", "beauty",
              "hair", "nail", "massage"],
    "hospitality": ["буудал", "резорт", "түрээс", "заал", "hotel", "resort",
                    "rental", "apartment", "hall", "event", "buudal", "turees"],
}

UI = {
    "mn": {
        "welcome": "Сайн байна уу! 👋 Энэ бол Ажилт-AI чатботын демо.\n\n"
                   "Доорх салбаруудаас сонгоод, тухайн бизнесийн харилцагч шиг "
                   "асуулт асууж үзээрэй. Ихэнх бизнес нь зохиомол.",
        "pick_industry": "Салбараа сонгоно уу:",
        "pick_kind": "Аль бизнесийг туршиж үзэх вэ?",
        "switch_lang": "🌐 English",
        "other_business": "🔄 Өөр бизнес",
        "intro": "Та одоо «{name}»-ийн чатботтой ярьж байна ({label}).\n\n"
                 "Юу ч асууж болно, жишээ нь:\n{examples}\n\n"
                 "Өөр бизнес сонгох бол «цэс» гэж бичнэ үү.",
        "label_fictional": "демо, зохиомол бизнес",
        "label_real": "демо, нээлттэй мэдээлэлд суурилсан; үнэ ойролцоо",
        "no_data": "Демо өгөгдөл хараахан ачаалагдаагүй байна. Түр хүлээгээд дахин оролдоно уу.",
        "fallback_miss": "Уучлаарай, энэ талаар мэдээлэл олдсонгүй. "
                         "Дэлгэрэнгүйг {phone} утсаар лавлана уу.",
        "language": "Mongolian",
    },
    "en": {
        "welcome": "Hi! 👋 This is the Ajilt-AI chatbot demo.\n\n"
                   "Pick an industry below and ask questions like a customer of "
                   "that business would. Most businesses here are fictional.",
        "pick_industry": "Choose an industry:",
        "pick_kind": "Which business would you like to try?",
        "switch_lang": "🌐 Монгол",
        "other_business": "🔄 Other business",
        "intro": "You're now chatting with {name}'s assistant ({label}).\n\n"
                 "Ask anything, for example:\n{examples}\n\n"
                 "Type “menu” to pick another business.",
        "label_fictional": "demo — a fictional business",
        "label_real": "demo built from public info; prices are estimates",
        "no_data": "The demo data isn't loaded yet. Please try again shortly.",
        "fallback_miss": "Sorry, I couldn't find information about that. "
                         "Please call {phone} for details.",
        "language": "English",
    },
}

DEMO_NOTE_FICTIONAL = ("This is a product demo and the business is fictional, but act exactly "
                       "like its real, friendly receptionist.")
DEMO_NOTE_REAL = ("This is a product demo built from this real business's public information. "
                  "Act like its friendly receptionist. Its prices are estimates: whenever you "
                  "quote a price, say it is approximate and can be confirmed by phone.")

ANSWER_SYSTEM = """You are the Facebook Messenger assistant of "{name}", a {kind}.
{demo_note}

Language: reply in the language of the customer's LAST message. If they wrote
Mongolian (in Cyrillic or in Latin letters), answer in Mongolian Cyrillic. If they
wrote English, answer in English. If unclear, answer in {default_language}.
The business information below is in {data_language}; translate facts faithfully.

Rules:
- Use ONLY the business information and FAQs below. Never invent prices, times,
  services, staff names, discounts or policies.
- If the answer isn't covered, say you don't have that information and suggest
  calling {phone}.
- If the question has nothing to do with this business, politely say you can
  only help with questions about {name}.
- Keep it short: 1-4 sentences, plain text, no markdown, at most one emoji.
- If asked whether you are a bot, say you are {name}'s virtual assistant.
{booking}
BUSINESS INFORMATION
{profile}

FAQ
{faqs}"""


def detect_lang(text: str) -> Optional[str]:
    """'mn', 'en', or None when the text doesn't tell us."""
    if re.search(r"[Ѐ-ӿ]", text):
        return "mn"
    words = re.findall(r"[a-zA-Z]+", text.lower())
    if not words:
        return None
    if any(w in LATIN_MN for w in words):
        return "mn"
    if all(w in AMBIGUOUS_LATIN for w in words):
        return None
    return "en"


def locale_to_lang(locale: Optional[str]) -> Optional[str]:
    if not locale:
        return None
    return "mn" if locale.lower().startswith("mn") else "en"


def _qr(pairs) -> List[QuickReply]:
    return [QuickReply(title=t, payload=p) for t, p in pairs]


def _profile_text(p: dict, lang: str) -> str:
    lines = [
        p["summary"][lang],
        f"Address: {p['address'][lang]}",
        f"Hours: {p['hours'][lang]}",
        f"Phone: {p['phone']}  Email: {p['email']}  Website: {p['website']}",
        f"Payment: {p['payment_methods'][lang]}",
        "Offerings:",
    ]
    for o in p.get("offerings", []):
        price = f"{o['price_mnt']:,}₮" if isinstance(o.get("price_mnt"), (int, float)) else ""
        note = (o.get("price_note") or {}).get(lang, "")
        details = (o.get("details") or {}).get(lang, "")
        lines.append(f"- {o['name'][lang]}: {' '.join(x for x in (price, note) if x)}. {details}")
    lines.append("Policies:")
    for pol in p.get("policies", []):
        lines.append(f"- {pol['title'][lang]}: {pol['text'][lang]}")
    return "\n".join(lines)


def _tokens(text: str) -> set:
    return {w for w in re.findall(r"\w+", text.lower()) if len(w) >= 3}


class DemoEngine:
    def __init__(self, llm, store, locale_lookup: Optional[Callable[[str], Optional[str]]] = None,
                 calendar=None):
        self.llm = llm
        self.store = store
        self.locale_lookup = locale_lookup
        seeds = load_seeds()
        self.industries = seeds["industries"]
        self.real = {s["id"] for s in seeds["businesses"] if s.get("fictional", True) is False}
        self.booking = BookingFlow(store, calendar)
        self.requests = RequestFlow(store)
        self.tour = TourGuide(store, self.booking, self.requests)

    def handle(self, session: Session, user_input: str) -> List[OutMsg]:
        out = self._route(session, (user_input or "").strip())
        self.store.save_session(session)
        return out

    # ---- language ----
    def _update_lang(self, session: Session, text: str) -> str:
        d = session.data
        if (not d.get("lang_locked") and not PAYLOAD_RE.match(text)
                and session.state not in NO_LANG_DETECT_STATES):
            detected = detect_lang(text)
            if detected:
                d["lang"] = detected
        if not d.get("lang"):
            locale = self.locale_lookup(session.sender_id) if self.locale_lookup else None
            d["lang"] = locale_to_lang(locale) or "mn"
        return d["lang"]

    # ---- pickers ----
    def _businesses_by_industry(self) -> dict:
        grouped = {}
        for b in self.store.list_businesses():
            grouped.setdefault(b["industry"], []).append(b)
        return grouped

    def _industry_picker(self, session: Session, lang: str, greet: bool) -> List[OutMsg]:
        grouped = self._businesses_by_industry()
        available = [i for i in self.industries if i["id"] in grouped]
        if not available:
            return [OutMsg(UI[lang]["no_data"])]
        session.state = "PICK_INDUSTRY"
        buttons = [(f"{i['emoji']} {i['label'][lang]}", f"IND_{i['id']}") for i in available]
        buttons.append((UI[lang]["switch_lang"], "LANG_EN" if lang == "mn" else "LANG_MN"))
        buttons.append(("🏠 Эхлэл" if lang == "mn" else "🏠 Home", "HOME"))
        out = [OutMsg(UI[lang]["welcome"])] if greet else []
        out.append(OutMsg(UI[lang]["pick_industry"], _qr(buttons)))
        return out

    def _kind_picker(self, session: Session, lang: str, industry_id: str) -> List[OutMsg]:
        options = self._businesses_by_industry().get(industry_id, [])
        if len(options) == 1:
            return self._select_business(session, lang, options[0]["id"])
        session.state = "PICK_KIND"
        session.data["industry"] = industry_id
        body = UI[lang]["pick_kind"] + "\n\n" + "\n".join(
            f"{b['emoji']} {b['name_' + lang]}" for b in options)
        buttons = [(f"{b['emoji']} {b['kind_' + lang]}", f"BIZ_{b['id']}") for b in options]
        return [OutMsg(body, _qr(buttons))]

    def _select_business(self, session: Session, lang: str, business_id: str) -> List[OutMsg]:
        biz = self.store.get_business(business_id)
        if not biz:
            return self._industry_picker(session, lang, greet=False)
        session.state = "CHAT"
        session.data.update(biz=business_id, history=[])
        session.data.pop("tour", None)
        faqs = self.store.get_faqs(business_id)
        examples, used = [], set()
        for category in ("pricing", "booking", "hours_location", "services"):
            f = next((f for f in faqs if f["category"] == category), None)
            if f and f["id"] not in used:
                used.add(f["id"])
                examples.append(f"• {f['question_' + lang]}")
        label = UI[lang]["label_real" if business_id in self.real else "label_fictional"]
        text = UI[lang]["intro"].format(name=biz["name_" + lang], label=label,
                                        examples="\n".join(examples[:3]))
        buttons = self._chat_buttons(lang, business_id, session)
        if self.tour.has_tour(business_id):
            buttons.insert(0, QuickReply(*self.tour.start_button(lang)))
        return [OutMsg(text, buttons)]

    def _chat_buttons(self, lang: str, business_id: str, session: Session) -> List[QuickReply]:
        buttons = []
        if self.tour.active(session):
            buttons.append(self.tour.continue_button(lang))
        if self.booking.is_bookable(business_id):
            buttons.append((BOOK_TEXT[lang]["book_button"], "BOOK"))
        elif self.requests.has_request(business_id):
            buttons.append(self.requests.button(lang, business_id))
        return _qr(buttons + [(UI[lang]["other_business"], "MENU")])

    def _has_action(self, business_id: str) -> bool:
        return self.booking.is_bookable(business_id) or self.requests.has_request(business_id)

    def _start_action(self, session: Session, lang: str, biz: dict,
                      before: Optional[List[OutMsg]] = None) -> List[OutMsg]:
        """Start booking (time slots) or a request (orders/stays), whichever the business has."""
        if self.booking.is_bookable(biz["id"]):
            msgs, done = self.booking.start(session, lang, biz)
        else:
            msgs, done = self.requests.start(session, lang, biz), False
        return self._finish_flow(session, lang, biz, (before or []) + msgs, done)

    def _finish_flow(self, session, lang, biz, msgs: List[OutMsg], done: bool) -> List[OutMsg]:
        if not done:
            return msgs
        session.state = "CHAT"
        comment = self.tour.after_action(session, lang, biz)
        if comment:
            for m in msgs:
                m.quick_replies = None
            return msgs + [comment]
        if msgs:
            msgs[-1].quick_replies = self._chat_buttons(lang, biz["id"], session)
        return msgs

    def _match_industry(self, text: str) -> Optional[str]:
        if text.startswith("IND_"):
            return text[4:]
        grouped = self._businesses_by_industry()
        available = [i["id"] for i in self.industries if i["id"] in grouped]
        if text.isdigit() and 1 <= int(text) <= len(available):
            return available[int(text) - 1]
        low = text.lower()
        for industry_id, words in INDUSTRY_KEYWORDS.items():
            if industry_id in available and any(w in low for w in words):
                return industry_id
        return None

    def _match_business(self, session: Session, text: str) -> Optional[str]:
        if text.startswith("BIZ_"):
            return text[4:]
        options = self._businesses_by_industry().get(session.data.get("industry"), [])
        if text.isdigit() and 1 <= int(text) <= len(options):
            return options[int(text) - 1]["id"]
        low = text.lower()
        for b in options:
            if b["id"] in low or any(w in low for w in _tokens(b["name_mn"] + " " + b["name_en"])):
                return b["id"]
        return None

    # ---- routing ----
    def _route(self, session: Session, text: str) -> List[OutMsg]:
        d = session.data
        if text in ("LANG_MN", "LANG_EN"):
            d.update(lang=text[-2:].lower(), lang_locked=True)
            return self._industry_picker(session, d["lang"], greet=False)

        lang = self._update_lang(session, text)

        if text == "MENU" or text.lower() in MENU_WORDS:
            for key in ("book", "req", "tour"):
                d.pop(key, None)
            in_demo = session.state in CHAT_STATES or session.state.startswith(("BOOK_", "REQ_"))
            return self._industry_picker(session, lang, greet=not in_demo)

        if session.state == "PICK_INDUSTRY":
            industry = self._match_industry(text)
            if industry:
                return self._kind_picker(session, lang, industry)
            return self._industry_picker(session, lang, greet=False)

        if session.state == "PICK_KIND":
            business_id = self._match_business(session, text)
            if business_id:
                return self._select_business(session, lang, business_id)
            return self._kind_picker(session, lang, d.get("industry", ""))

        biz = self.store.get_business(d["biz"]) if d.get("biz") else None

        if session.state.startswith("BOOK_") and biz and self.booking.is_bookable(biz["id"]):
            msgs, done = self.booking.handle(session, lang, biz, text)
            return self._finish_flow(session, lang, biz, msgs, done)

        if session.state.startswith("REQ_") and biz and self.requests.has_request(biz["id"]):
            msgs, done = self.requests.handle(session, lang, biz, text)
            return self._finish_flow(session, lang, biz, msgs, done)

        if biz and (session.state == "CHAT" or session.state.startswith(("BOOK_", "REQ_"))):
            session.state = "CHAT"
            return self._chat(session, lang, biz, text)

        # New or unknown state (including old sales-flow sessions).
        session.data = {"lang": lang, "lang_locked": d.get("lang_locked", False)}
        return self._industry_picker(session, lang, greet=True)

    def _chat(self, session: Session, lang: str, biz: dict, text: str) -> List[OutMsg]:
        """Chat state: tour buttons, booking/request buttons, or a free question."""
        if text == "TOUR_START" and self.tour.has_tour(biz["id"]):
            return self.tour.start(session, lang, biz)
        if text == "TOUR_NEXT":
            if self.tour.active(session):
                return self.tour.next(session, lang, biz)
            return self.tour.start(session, lang, biz) if self.tour.has_tour(biz["id"]) else []
        if text == "TOUR_END":
            return self.tour.end(session, lang)
        if text == "TOUR_SEND":
            question = self.tour.pending_question(session, lang, biz)
            if not question:
                return self.tour.next(session, lang, biz) if self.tour.active(session) else []
            return [OutMsg(f"👤 {question}")] + self._answer(session, lang, biz, question)
        if text in ("BOOK", "REQ") and self._has_action(biz["id"]):
            return self._start_action(session, lang, biz)
        return self._answer(session, lang, biz, text)

    # ---- answering ----
    def _answer(self, session: Session, lang: str, biz: dict, text: str) -> List[OutMsg]:
        if not text:
            return []
        faqs = self.store.get_faqs(biz["id"])
        has_action = self._has_action(biz["id"])

        started = time.monotonic()
        reply = self.llm.chat(self._build_messages(session, biz, faqs, lang, text), timeout=40)
        seconds = time.monotonic() - started
        if reply:
            wants_action = BOOK_TOKEN in reply
            reply = reply.replace(BOOK_TOKEN, "").replace("**", "").strip()
        else:
            wants_action = wants_booking(text)
            reply = "" if wants_action and has_action else self._keyword_answer(biz, faqs, lang, text)

        history = session.data.get("history", [])
        history += [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
        session.data["history"] = history[-HISTORY_TURNS * 2:]

        if wants_action and has_action:
            return self._start_action(session, lang, biz, before=[OutMsg(reply)] if reply else None)
        comment = self.tour.after_answer(session, lang, biz, seconds)
        if comment:
            return [OutMsg(reply), comment]
        return [OutMsg(reply, self._chat_buttons(lang, biz["id"], session))]

    def _build_messages(self, session, biz, faqs, lang, text) -> List[dict]:
        p = biz["profile"]
        faq_text = "\n\n".join(f"Q: {f['question_' + lang]}\nA: {f['answer_' + lang]}" for f in faqs)
        booking = ""
        if self.booking.is_bookable(biz["id"]):
            services = ", ".join(s["name"]["en"] for s in self.booking.configs[biz["id"]]["services"])
            booking = (
                f"- Customers can book right here in this chat ({services}). If the customer "
                "wants to book, schedule or reserve an appointment or visit (not just asking "
                f"about a policy), reply with one short sentence and end with the exact token {BOOK_TOKEN}. "
                "Never ask for their name, phone or time yourself; the booking form does that.\n"
            )
        elif self.requests.has_request(biz["id"]):
            title = self.requests.configs[biz["id"]]["title"]["en"]
            booking = (
                f"- Customers can send a {title.lower()} right here in this chat. If the customer "
                "wants to order or reserve (not just asking about prices or a policy), reply with "
                f"one short sentence and end with the exact token {BOOK_TOKEN}. Never collect the "
                "details, name or phone yourself; the request form does that.\n"
            )
        system = ANSWER_SYSTEM.format(
            demo_note=DEMO_NOTE_REAL if biz["id"] in self.real else DEMO_NOTE_FICTIONAL,
            name=biz["name_" + lang], kind=biz["kind_en"], phone=p["phone"],
            default_language=UI[lang]["language"], data_language=UI[lang]["language"],
            profile=_profile_text(p, lang), faqs=faq_text, booking=booking,
        )
        return ([{"role": "system", "content": system}]
                + session.data.get("history", [])
                + [{"role": "user", "content": text}])

    def _keyword_answer(self, biz, faqs, lang, text) -> str:
        """Used only when the LLM is unavailable."""
        asked = _tokens(text)
        best, best_score = None, 0.0
        for f in faqs:
            phrasings = [f["question_mn"], f["question_en"]] + [
                v for vs in f["variants"].values() for v in vs]
            score = max((len(asked & _tokens(ph)) / len(asked) for ph in phrasings), default=0) if asked else 0
            if score > best_score:
                best, best_score = f, score
        if best and best_score >= 0.5:
            return best["answer_" + lang]
        return UI[lang]["fallback_miss"].format(phone=biz["profile"]["phone"])
