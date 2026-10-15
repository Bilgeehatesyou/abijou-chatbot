"""FAQ demo engine: the visitor picks one of the fictional businesses, then the
bot answers as that business's receptionist using only its profile + FAQs.

Language: conversations start in Mongolian (many Mongolians use English Facebook, so
the Facebook locale is not a good signal); after that each
message's own language takes over (Cyrillic -> Mongolian, Latin-script
Mongolian -> Mongolian, otherwise English). The LLM is told to answer in the
language of the last message, so the heuristic here only drives UI strings.
"""
import json
import re
import time
from typing import List, Optional

from .booking import T as BOOK_TEXT, BookingFlow, wants_booking
from .demo_data import load_seeds, sync_businesses
from .catalog import image_url, load_catalog
from .config import settings
from .models import Card, OutMsg, QuickReply, Session
from .request_flow import RequestFlow
from .tour import TourGuide

# "start"/"эхлэх" belong to the app router (back to the Ajilt-AI / demo choice).
MENU_WORDS = {"menu", "цэс", "tses", "demo", "демо"}
HISTORY_TURNS = 6
DEFAULT_LANG = "mn"
PAYLOAD_RE = re.compile(r"^(MENU|HOME|BOOK|BOK|BCANCEL|REQ|CAT|[A-Z]+_\w+)$")
CHAT_STATES = ("PICK_INDUSTRY", "PICK_KIND", "CHAT")
BOOK_TOKEN = "[BOOK]"
# "this one": the listing the customer last opened (Cyrillic, Latin-typed, English)
THIS_RE = re.compile(r"(?<!\w)(энэ|ene|this|it)(?!\w)")
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
    # real estate, as people type it: "40r bair 2 dawhar 4 uruu"
    "bair", "bairnii", "uruu", "oroo", "davhar", "dawhar", "davhart", "dawhart", "hothon",
    "hotholt", "turees", "tureesiin", "zarna", "zarah", "mkv", "say", "saya", "terbum", "gazar",
    "zogsool", "baishin", "haus", "ipotek",
}

INDUSTRY_KEYWORDS = {
    "dental": ["шүд", "dental", "dentist", "tooth", "teeth", "shud"],
    "education": ["сургууль", "боловсрол", "коллеж", "сургалт", "курс", "school",
                  "college", "course", "education", "surguuli", "surgalt", "kurs"],
    "wholesale": ["бөөн", "wholesale", "buun", "distribut", "trade"],
    "salon": ["салон", "спа", "гоо", "үс", "массаж", "salon", "spa", "beauty",
              "hair", "nail", "massage"],
    "hospitality": ["буудал", "резорт", "түрээс", "заал", "hotel", "resort",
                    "rental", "hall", "event", "buudal", "turees"],
    "real_estate": ["үл хөдлөх", "орон сууц", "байр зар", "хаус", "агент", "real estate",
                    "property", "realty", "apartment", "ul hudluh", "oron suuts"],
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
        "category_page": "{label}: {start}–{end} / нийт {count}",
        "more_button": "➡ Дараах 10",
        "pick_listing": "Аль байрыг очиж үзэх вэ? Доороос сонгоно уу, эсвэл ерөнхий зөвлөгөө "
                        "авах цаг товлож болно.",
        "consult_button": "💬 Зөвлөгөө авах",
        "found_listings": "Таны хайлтад тохирох {count} зар олдлоо. Картан дээрх товчоор "
                          "дэлгэрэнгүйг үзэх эсвэл үзэх цаг авна уу.",
        "gone_alternatives": "«{title}» {status}. Оронд нь эдгээрийг санал болгож байна:\n{lines}",
        "alt_same_building": "• {title} — яг тэр байранд, {floor}",
        "alt_same_complex": "• {title} — мөн хотхоны {building}, {floor}",
        "alt_nearby": "• {title} — {km} км зайтай",
        "gone_ask_area": "«{title}» {status}, ойролцоо ижил төрлийн зар одоогоор алга. Та хаана, "
                         "ямар байр авахыг хүсэж байна вэ? Байршлаа сонгоод өгвөл төрлийг нь асууж, "
                         "хамгийн ойрхныг олж өгье.",
        "ask_type": "{area} орчимд ямар төрлийн үл хөдлөх хайж байна вэ?",
        "any_type": "Аль нь ч болно",
        "recommend": "{area} орчмын хамгийн ойр зарууд:\n{lines}",
        "rec_line": "• {title} — {km} км",
        "rec_here": "• {title} — яг энэ хавьд",
        "nothing_there": "Уучлаарай, тэр төрлийн боломжтой зар одоогоор алга. Өөр төрөл сонгоно уу.",
        "not_viewable": "«{title}» {status} тул үзэх цаг авах боломжгүй.",
        "not_found": "Уучлаарай, «{what}» манай мэдээлэлд олдсонгүй.",
        "similar_instead": "Оронд нь хамгийн төстэй {count} зарыг санал болгож байна.",
        "after_details": "Энэ байрыг очиж үзэх үү? Таалагдаагүй бол хэдэн өрөө, аль хотхонд, ямар "
                         "нөхцөлөөр (бэлэн, банкны зээл, бартер) авахыг хүсэж байгаагаа хэлээрэй.",
        "want_button": "🔎 Байр сонгох",
        "want_rooms": "Хэдэн өрөө байр сонирхож байна вэ?",
        "want_rooms_n": "{n} өрөө",
        "want_rooms_5": "5+ өрөө",
        "want_parking": "🅿️ Зогсоол, гараж",
        "want_complex": "Аль хотхонд вэ?",
        "any_complex": "Аль нь ч болно",
        "want_pay": "Төлбөрөө ямар хэлбэрээр хийх вэ?",
        "pay_cash": "💵 Бэлнээр",
        "pay_loan": "🏦 Банкны зээл",
        "pay_barter": "🔄 Бартер",
        "any_pay": "Аль нь ч болно",
        "want_found": "Таны сонголт: {summary}. Тохирох {count} зар байна (хямдаас нь эхлэв):",
        "want_relaxed": "Яг таны сонголтоор ({summary}) боломжтой зар одоогоор алга. Хамгийн ойрыг "
                        "санал болгож байна:",
        "want_none": "Уучлаарай, ийм зар одоогоор алга. Өөр сонголт хийж үзээрэй.",
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
        "category_page": "{label}: {start}–{end} of {count}",
        "more_button": "➡ Next 10",
        "pick_listing": "Which property would you like to see? Pick one below, or book a "
                        "general consultation.",
        "consult_button": "💬 Consultation",
        "found_listings": "I found {count} listings that match. Use the buttons on a card to "
                          "see details or book a viewing.",
        "gone_alternatives": "“{title}” is {status}. Here's what I can offer instead:\n{lines}",
        "alt_same_building": "• {title} — same building, {floor}",
        "alt_same_complex": "• {title} — same complex, {building}, {floor}",
        "alt_nearby": "• {title} — {km} km away",
        "gone_ask_area": "“{title}” is {status}, and there's nothing of the same type nearby right "
                         "now. Where would you like to buy, and what type? Pick an area, then a type, "
                         "and I'll find the closest options.",
        "ask_type": "What kind of property are you looking for around {area}?",
        "any_type": "Any",
        "recommend": "The closest listings to {area}:\n{lines}",
        "rec_line": "• {title} — {km} km",
        "rec_here": "• {title} — right here",
        "nothing_there": "Sorry, nothing of that type is available right now. Please pick another type.",
        "not_viewable": "“{title}” is {status}, so it can't be viewed.",
        "not_found": "Sorry, I couldn't find {what} in our listings.",
        "similar_instead": "Here are the {count} closest options instead.",
        "after_details": "Would you like to view this one? If it's not quite right, tell me how many "
                         "rooms, which complex, and how you'd pay (cash, bank loan or trade-in).",
        "want_button": "🔎 Find a flat",
        "want_rooms": "How many rooms are you looking for?",
        "want_rooms_n": "{n} rooms",
        "want_rooms_5": "5+ rooms",
        "want_parking": "🅿️ Parking, garage",
        "want_complex": "Which complex?",
        "any_complex": "Either",
        "want_pay": "How would you pay?",
        "pay_cash": "💵 Cash",
        "pay_loan": "🏦 Bank loan",
        "pay_barter": "🔄 Trade-in",
        "any_pay": "Any",
        "want_found": "You chose: {summary}. {count} listings fit (cheapest first):",
        "want_relaxed": "Nothing available fits exactly ({summary}) right now. The closest ones:",
        "want_none": "Sorry, nothing like that is available right now. Try another choice.",
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
    def __init__(self, llm, store, calendar=None):
        self.llm = llm
        self.store = store
        try:
            loaded = sync_businesses(store)
            if loaded:
                print(f"[demo] loaded demo data: {', '.join(loaded)}")
        except Exception as e:   # the demo still works with whatever the database has
            print(f"[demo] demo data sync failed: {type(e).__name__}: {e}")
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
            d["lang"] = DEFAULT_LANG
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
        catalog = load_catalog(business_id)
        if catalog:
            buttons.append((catalog.browse_button(lang), "CAT"))
            if catalog.kind == "listings":
                buttons.append((UI[lang]["want_button"], "WANT_START"))
        if self.booking.is_bookable(business_id):
            buttons.append((BOOK_TEXT[lang]["book_button"], "BOOK"))
        elif self.requests.has_request(business_id):
            buttons.append(self.requests.button(lang, business_id))
        return _qr(buttons + [(UI[lang]["other_business"], "MENU")])

    # Payloads from the chat (cards, menus, tour) that mean "not the booking any more".
    CHAT_PAYLOADS = ("CAT", "BOOK", "BOOK_CONSULT", "REQ")
    CHAT_PREFIXES = ("CAT_", "CATP_", "INFO_", "VIEW_", "SIMILAR_", "PREFA_", "PREF_", "ORDER_", "TOUR_",
                     "WANT")
    PICK_STATES = ("BOOK_SERVICE", "BOOK_BRANCH", "BOOK_STAFF", "BOOK_DAY", "BOOK_TIME")

    def _leaves_booking(self, session, lang, biz, text: str) -> bool:
        """While picking a service/day/time, a question or another chat button leaves the
        booking instead of getting "pick a button" forever. Typed answers the booking
        understands (an option's number, "10:00") still count as answers."""
        if session.state not in self.PICK_STATES or text in ("BCANCEL", "BOK"):
            return False
        if text in self.CHAT_PAYLOADS or text.startswith(self.CHAT_PREFIXES):
            return True
        if PAYLOAD_RE.match(text):
            return False
        trial = Session(sender_id=session.sender_id, channel=session.channel, state=session.state,
                        data=json.loads(json.dumps(session.data)))
        msgs, _ = self.booking.handle(trial, lang, biz, text)
        return bool(msgs) and msgs[0].text.startswith(BOOK_TEXT[lang]["pick_button"])

    def _has_action(self, business_id: str) -> bool:
        return self.booking.is_bookable(business_id) or self.requests.has_request(business_id)

    def _start_action(self, session: Session, lang: str, biz: dict,
                      before: Optional[List[OutMsg]] = None, product: str = "",
                      item: Optional[dict] = None, service: str = "") -> List[OutMsg]:
        """Start booking (time slots) or a request (orders/stays), whichever the business has.
        Property listings book a viewing of one property, so that is asked first."""
        catalog = load_catalog(biz["id"])
        if (self.booking.is_bookable(biz["id"]) and not item and not service
                and catalog is not None and catalog.kind == "listings"):
            shown = [catalog.by_sku[s] for s in session.data.get("shown", []) if s in catalog.by_sku]
            if len(shown) == 1:
                item = catalog.booking_item(shown[0])
            else:
                return (before or []) + [self._listing_picker(lang, catalog, shown)]
        if self.booking.is_bookable(biz["id"]):
            msgs, done = self.booking.start(session, lang, biz, item=item, service=service)
        else:
            msgs, done = self.requests.start(session, lang, biz, product=product), False
        return self._finish_flow(session, lang, biz, (before or []) + msgs, done)

    def _listing_picker(self, lang: str, catalog, shown: list) -> OutMsg:
        options = shown or [p for t in catalog.categories() for p in catalog.in_category(t)]
        buttons = [(f"🏠 {p['short'][lang]}", f"VIEW_{p['sku']}") for p in options[:11]]
        buttons += [(UI[lang]["consult_button"], "BOOK_CONSULT"),
                    (BOOK_TEXT[lang]["cancel_button"], "CAT")]
        return OutMsg(UI[lang]["pick_listing"], _qr(buttons))

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
            if self._leaves_booking(session, lang, biz, text):
                d.pop("book", None)          # a new question or a button from the chat: answer it
                session.state = "CHAT"
                return self._chat(session, lang, biz, text)
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
        if text == "BOOK_CONSULT" and self.booking.is_bookable(biz["id"]):
            return self._start_action(session, lang, biz, service="consult")
        catalog = load_catalog(biz["id"])
        if catalog and (text == "CAT" or text.startswith(("CAT_", "CATP_", "ORDER_", "INFO_", "VIEW_",
                                                          "SIMILAR_", "PREFA_", "PREF_", "WANT"))):
            return self._catalog(session, lang, biz, catalog, text)
        return self._answer(session, lang, biz, text)

    # ---- product catalog ----
    def _cards(self, session: Session, lang: str, biz: dict, catalog, products: list) -> List[Card]:
        products = products[:10]
        # "book a viewing" picks from these (never from sold or rented listings)
        session.data["shown"] = [p["sku"] for p in products if p.get("status", "available") == "available"]
        return [catalog.card(p, lang, image_url(settings.PUBLIC_BASE_URL, biz["id"], p, lang))
                for p in products]

    def _catalog(self, session, lang, biz, catalog, text) -> List[OutMsg]:
        sku = text.split("_", 1)[1] if text.startswith(("INFO_", "VIEW_", "SIMILAR_")) else ""
        if sku in catalog.by_sku:
            session.data["focus"] = sku       # "энэ байр" in the next question means this one
        if text.startswith("ORDER_"):
            product = catalog.by_sku.get(text[6:])
            if product and self.requests.has_request(biz["id"]):
                return self._start_action(session, lang, biz, product=product["name"][lang])
        if text.startswith("VIEW_"):
            listing = catalog.by_sku.get(text[5:])
            if listing and not self._is_free(listing):
                note = UI[lang]["not_viewable"].format(title=listing["title"][lang],
                                                      status=self._status(listing, lang))
                return [OutMsg(note)] + self._gone_followup(session, lang, biz, catalog, listing)
            if listing and self.booking.is_bookable(biz["id"]):
                return self._start_action(session, lang, biz, item=catalog.booking_item(listing))
        if text.startswith("INFO_"):
            listing = catalog.by_sku.get(text[5:])
            if listing and not self._is_free(listing):
                return [OutMsg(catalog.details(listing, lang))] + \
                    self._gone_followup(session, lang, biz, catalog, listing)
            if listing:
                session.data["shown"] = [listing["sku"]]
                buttons = [(t, pl) for t, pl in [(q.title, q.payload) for q in
                           self._chat_buttons(lang, biz["id"], session)] if pl != "BOOK"]
                view = (catalog.card(listing, lang, "").buttons[-1].title, f"VIEW_{listing['sku']}")
                if catalog.kind == "listings":     # then: view it, or what would suit them better?
                    return [OutMsg(catalog.details(listing, lang)),
                            OutMsg(UI[lang]["after_details"], _qr([view] + buttons))]
                return [OutMsg(catalog.details(listing, lang), _qr([view] + buttons))]
        if text.startswith("SIMILAR_") and text[8:] in catalog.by_sku:
            return self._gone_followup(session, lang, biz, catalog, catalog.by_sku[text[8:]])
        if text.startswith("WANT") and catalog.kind == "listings":
            return self._want(session, lang, biz, catalog, text)
        if text.startswith("PREFA_") and text[6:] in catalog.areas:
            return [self._type_question(lang, catalog, text[6:])]
        if text.startswith("PREF_"):
            area, _, category = text[5:].rpartition("_")
            if area in catalog.areas:
                return self._recommend(session, lang, biz, catalog, area, category)
        if text.startswith(("CAT_", "CATP_")):
            if text.startswith("CATP_"):  # CATP_<category>_<page>
                category, _, page = text[5:].rpartition("_")
            else:
                category, page = text[4:], "0"
            items = catalog.in_category(category)
            if items:
                start = int(page or 0) * 10
                chunk = items[start:start + 10]
                buttons = [(UI[lang]["more_button"], f"CATP_{category}_{int(page or 0) + 1}")] \
                    if start + 10 < len(items) else []
                buttons.append((catalog.browse_button(lang), "CAT"))
                buttons += [(t, pl) for t, pl in [(q.title, q.payload) for q in
                            self._chat_buttons(lang, biz["id"], session)] if pl not in ("CAT",)]
                header = UI[lang]["category_page"].format(
                    label=catalog.category_label(category, lang), start=start + 1,
                    end=start + len(chunk), count=len(items))
                return [OutMsg(header, _qr(buttons[:13]),
                               cards=self._cards(session, lang, biz, catalog, chunk))]
        buttons = [(catalog.category_label(c, lang)[:20], f"CAT_{c}") for c in catalog.categories()]
        return [OutMsg(catalog.pick_text(lang), _qr(buttons[:13]))]

    # ---- listings that are gone: alternatives, or ask what they want ----
    @staticmethod
    def _is_free(listing: dict) -> bool:
        return listing.get("status", "available") == "available"

    @staticmethod
    def _status(listing: dict, lang: str) -> str:
        from .listings import STATUS
        return STATUS[listing["status"]][lang].split(" ", 1)[-1].lower()

    def _gone_followup(self, session, lang, biz, catalog, listing, shown=()) -> List[OutMsg]:
        """Same building first, then nearby; with neither, ask which area they want.
        shown: listings whose cards are already on screen, so they aren't repeated."""
        from .listings import floor_label
        u = UI[lang]
        title, status = listing["title"][lang], self._status(listing, lang)
        alts = catalog.alternatives(listing)
        if not alts:
            buttons = [(catalog.area_label(a, lang)[:20], f"PREFA_{a}") for a in catalog.area_choices()]
            return [OutMsg(u["gone_ask_area"].format(title=title, status=status), _qr(buttons[:13]))]
        complex_of = lambda x: ((x.get("building") or {}).get("complex") or {}).get("id")

        def line(q, why, d):
            if why == "same_building":
                return u["alt_same_building"].format(title=q["title"][lang], floor=floor_label(q, lang))
            if why == "same_complex" or (complex_of(q) and complex_of(q) == complex_of(listing)):
                block = q["building"]["name"][lang].split(", ")[-1]      # "5-р байр" / "bldg 5"
                return u["alt_same_complex"].format(title=q["title"][lang], building=block,
                                                    floor=floor_label(q, lang))
            return u["alt_nearby"].format(title=q["title"][lang], km=f"{d:.1f}")
        lines = "\n".join(line(q, why, d) for q, why, d in alts)
        new = [q for q, _, _ in alts if q["sku"] not in {p["sku"] for p in shown}]
        cards = self._cards(session, lang, biz, catalog, new) if new else None
        if not new:   # every alternative is already on screen: keep those bookable
            session.data["shown"] = [q["sku"] for q, _, _ in alts]
        return [OutMsg(u["gone_alternatives"].format(title=title, status=status, lines=lines),
                       self._chat_buttons(lang, biz["id"], session), cards=cards)]

    # ---- "what are you looking for?": rooms -> complex -> how you pay -> listings ----
    def _want(self, session, lang, biz, catalog, text) -> List[OutMsg]:
        u, want = UI[lang], session.data.setdefault("want", {})
        if text.startswith("WANTR_"):
            want["rooms"] = text[6:]
            buttons = [(name[lang][:20], f"WANTC_{cid}") for cid, name in catalog.complex_choices()]
            return [OutMsg(u["want_complex"], _qr(buttons + [(u["any_complex"], "WANTC_any")]))]
        if text.startswith("WANTC_") and want.get("rooms"):
            want["complex"] = text[6:]
            buttons = [(u["pay_cash"], "WANTP_cash"), (u["pay_loan"], "WANTP_loan"),
                       (u["pay_barter"], "WANTP_barter"), (u["any_pay"], "WANTP_any")]
            if want["rooms"] == "parking":                    # no bank loans for a parking space
                buttons.pop(1)
            return [OutMsg(u["want_pay"], _qr(buttons))]
        if text.startswith("WANTP_") and want.get("rooms"):
            want["pay"] = text[6:]
            found, exact = catalog.want(want["rooms"], want.get("complex", "any"), want["pay"])
            rooms = {"parking": u["want_parking"].split(" ", 1)[-1], "5": u["want_rooms_5"]}.get(
                want["rooms"]) or u["want_rooms_n"].format(n=want["rooms"])
            names = dict(catalog.complex_choices())
            summary = " · ".join(x for x in (
                rooms, names[want["complex"]][lang] if want.get("complex") in names else "",
                {"cash": u["pay_cash"], "loan": u["pay_loan"], "barter": u["pay_barter"]}.get(
                    want["pay"], "").split(" ", 1)[-1]) if x)
            if not found:
                return [OutMsg(u["want_none"], self._chat_buttons(lang, biz["id"], session))]
            text = (u["want_found"] if exact else u["want_relaxed"]).format(summary=summary, count=len(found))
            return [OutMsg(text, self._chat_buttons(lang, biz["id"], session),
                           cards=self._cards(session, lang, biz, catalog, found))]
        session.data["want"] = {}                              # WANT_START, or a stale button
        buttons = [(u["want_rooms_n"].format(n=n), f"WANTR_{n}") for n in (2, 3, 4)]
        buttons += [(u["want_rooms_5"], "WANTR_5"), (u["want_parking"], "WANTR_parking")]
        return [OutMsg(u["want_rooms"], _qr(buttons))]

    def _type_question(self, lang, catalog, area: str) -> OutMsg:
        buttons = [(catalog.category_label(c, lang)[:20], f"PREF_{area}_{c}") for c in catalog.categories()]
        buttons.append((UI[lang]["any_type"], f"PREF_{area}_any"))
        return OutMsg(UI[lang]["ask_type"].format(area=catalog.area_label(area, lang)), _qr(buttons))

    def _recommend(self, session, lang, biz, catalog, area: str, category: str) -> List[OutMsg]:
        found = catalog.recommend(area, "" if category == "any" else category)
        if not found:
            return [OutMsg(UI[lang]["nothing_there"])] + [self._type_question(lang, catalog, area)]
        def line(p):
            d = catalog.distance_from(area, p)
            if d < 0.5:
                return UI[lang]["rec_here"].format(title=p["title"][lang])
            return UI[lang]["rec_line"].format(title=p["title"][lang], km=f"{d:.1f}")
        lines = "\n".join(line(p) for p in found)
        text = UI[lang]["recommend"].format(area=catalog.area_label(area, lang), lines=lines)
        return [OutMsg(text, self._chat_buttons(lang, biz["id"], session),
                       cards=self._cards(session, lang, biz, catalog, found))]

    # ---- answering ----
    def _answer(self, session: Session, lang: str, biz: dict, text: str) -> List[OutMsg]:
        if not text:
            return []
        faqs = self.store.get_faqs(biz["id"])
        has_action = self._has_action(biz["id"])
        catalog = load_catalog(biz["id"])
        missing = None                    # a unit the customer named that isn't in the listings
        if catalog and catalog.kind == "listings":
            matches, missing = catalog.find(text)
        else:
            matches = catalog.search(text) if catalog else []
        focus = catalog.by_sku.get(session.data.get("focus", "")) if catalog else None
        if not matches and focus and THIS_RE.search(text.lower()):
            matches = [focus]                 # "энэ байр ипотекоор болох уу?" is about that one
        if len(matches) == 1:
            session.data["focus"] = matches[0]["sku"]

        started = time.monotonic()
        reply = self.llm.chat(self._build_messages(session, biz, faqs, lang, text, matches,
                                                   len(catalog.products) if catalog else 0, missing),
                              timeout=40)
        seconds = time.monotonic() - started
        if reply:
            wants_action = BOOK_TOKEN in reply
            reply = reply.replace(BOOK_TOKEN, "").replace("**", "").strip()
            if wants_action and reply.endswith("?"):
                # "...үзэх цаг товлох уу?" offers a booking; only the customer's yes starts one
                wants_action = False
        else:
            wants_action = wants_booking(text)
            reply = "" if wants_action and has_action else self._keyword_answer(biz, faqs, lang, text)
            if matches and catalog.kind == "listings" and not wants_action \
                    and reply == UI[lang]["fallback_miss"].format(phone=biz["profile"]["phone"]):
                reply = UI[lang]["found_listings"].format(count=len(matches[:10]))
            if missing:
                reply = UI[lang]["similar_instead"].format(count=len(matches)) if matches else ""
        if missing:   # say plainly that it isn't there, before the closest options
            reply = (UI[lang]["not_found"].format(what=missing[lang]) + "\n\n" + reply).strip()

        history = session.data.get("history", [])
        history += [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
        session.data["history"] = history[-HISTORY_TURNS * 2:]

        if wants_action and has_action:
            if matches:
                session.data["shown"] = [p["sku"] for p in matches[:10] if self._is_free(p)]
            return self._start_action(session, lang, biz, before=[OutMsg(reply)] if reply else None)
        cards = self._cards(session, lang, biz, catalog, matches) if matches else None
        gone = [m for m in matches if catalog.kind == "listings" and not self._is_free(m)]
        if gone:   # say what replaces it (or ask what they want) right under the answer
            return [OutMsg(reply, cards=cards)] + self._gone_followup(session, lang, biz, catalog,
                                                                      gone[0], shown=matches[:10])
        comment = self.tour.after_answer(session, lang, biz, seconds)
        if comment:
            return [OutMsg(reply, cards=cards), comment]
        return [OutMsg(reply, self._chat_buttons(lang, biz["id"], session), cards=cards)]

    def _build_messages(self, session, biz, faqs, lang, text, matches=(), catalog_size=0,
                        missing=None) -> List[dict]:
        p = biz["profile"]
        faq_text = "\n\n".join(f"Q: {f['question_' + lang]}\nA: {f['answer_' + lang]}" for f in faqs)
        catalog = load_catalog(biz["id"]) if catalog_size else None
        if catalog:
            focus = catalog.by_sku.get(session.data.get("focus", ""))
            if catalog.kind == "listings":
                faq_text += catalog.prompt_context(list(matches), lang, missing=missing, focus=focus)
            else:
                faq_text += catalog.prompt_context(list(matches), lang)
            if focus and catalog.kind == "listings":
                faq_text += (f"\nThe customer is now looking at {focus['sku']} ({focus['title'][lang]}); "
                             "“this one”, «энэ байр», «энэ» mean that listing unless they name another.")
        booking = ""
        if self.booking.is_bookable(biz["id"]):
            services = ", ".join(s["name"]["en"] for s in self.booking.configs[biz["id"]]["services"])
            booking = (
                f"- Customers can book right here in this chat ({services}). If the customer "
                "wants to book, schedule or reserve an appointment or visit (not just asking "
                f"about a policy), reply with one short sentence and end with the exact token {BOOK_TOKEN}. "
                f"Use {BOOK_TOKEN} only when they asked to book; when you merely suggest a booking, "
                "don't add it (the buttons let them book). "
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
