"""The clinic's chatbot: greets, shows treatments and prices, branches, contacts,
answers free questions from data/clinic.yaml with the LLM, and books appointments.

Language: conversations start in Mongolian; after that each message's own
language takes over (Hangul -> Korean, Cyrillic or Latin-typed Mongolian ->
Mongolian, otherwise English), or the 🌐 buttons pin one. The LLM is told to
answer in the language of the last message; the detection here drives the
buttons and fixed texts.
"""
import re
import time
from typing import List, Optional

from .booking import PICK_STATES, T as BOOK_TEXT, BookingFlow, wants_booking
from .clinic import Clinic, tr
from .config import settings
from .lang import DEFAULT_LANG, detect_lang
from .models import OutMsg, QuickReply, Session

HISTORY_TURNS = 6
PAYLOAD_RE = re.compile(r"^(MENU|HOME|BOOK|BOK|BBACK|BCANCEL|GET_STARTED|[A-Z]+_\w+)$")
# The booking form's own buttons; any other button leaves the booking.
BOOKING_PAYLOAD_RE = re.compile(r"^(BOK|BBACK|BCANCEL|(BSVC|BCTRY|BBR|BDAY|BTIME)_\w+)$")
BOOK_TOKEN_RE = re.compile(r"\[BOOK(?::([a-z0-9_]+))?(?::([a-z0-9_]+))?\]")
HOME_PAYLOADS = {"GET_STARTED", "HOME"}
HOME_WORDS = {"start", "restart", "home", "get started", "эхлэх", "эхлэл", "ehleh", "처음", "처음으로", "시작"}
MENU_WORDS = {"menu", "цэс", "tses", "메뉴"}
GREETINGS = {"hi", "hello", "hey", "сайн уу", "сайн байна уу", "сайн", "сайнуу", "sain uu", "sainuu",
             "sain baina uu", "sain bn uu", "sn uu", "안녕하세요", "안녕", "안녕하세용", "하이"}
# Free text like a name ("Bat") must not flip the conversation language.
NO_LANG_DETECT_STATES = ("BOOK_NAME", "BOOK_PHONE")
LANG_PAYLOADS = {"LANG_MN": "mn", "LANG_EN": "en", "LANG_KO": "ko"}
LANG_BUTTONS = {"mn": ("🌐 Монгол", "LANG_MN"), "en": ("🌐 English", "LANG_EN"), "ko": ("🌐 한국어", "LANG_KO")}

UI = {
    "mn": {
        "welcome": "Сайн байна уу! 🌸 Abijou клиникийн виртуал туслах байна.\n\n"
                   "Батга, улайлт, сэвх толбо, арьс чангалах, skin booster эмчилгээний талаар асууж, "
                   "үнэ мэдэж, Монгол (4) болон Солонгос (8) салбартаа цаг захиалах боломжтой.\n\n"
                   "Асуултаа бичих эсвэл доороос сонгоно уу 👇",
        "menu": "Юугаар туслах вэ? 👇",
        "services_button": "💆 Эмчилгээ, үнэ",
        "branches_button": "📍 Салбарууд",
        "promo_button": "🎁 Хөнгөлөлт",
        "contact_button": "☎ Холбоо барих",
        "human_button": "👩‍⚕️ Ажилтантай",
        "home_button": "🏠 Цэс",
        "categories_button": "⬅ Ангилал",
        "pick_category": "Ямар асуудлаар эмчилгээ хайж байна вэ?",
        "category_footer": "Эмчилгээний тоо нь хувь хүний арьсны байдлаас шалтгаална. Цаг авах бол доорх "
                           "товчийг дарна уу.",
        "pick_country": "Аль улсын салбарыг харах вэ?",
        "branches_header": "{flag} {country} дахь салбарууд:",
        "branches_footer": "Цаг авах салбараа сонгоно уу.",
        "promo": "🎁 Одоогийн урамшуулал:\n{lines}",
        "contact": "Холбоо барих:\n{lines}",
        "human": "Манай зохицуулагч энэ чатаар удахгүй хариулна. Яаралтай бол утсаар холбогдоорой:\n{lines}",
        "fallback_miss": "Уучлаарай, энэ талаар надад мэдээлэл алга. Дэлгэрэнгүйг утсаар лавлана уу:\n{lines}",
        "language": "Mongolian",
    },
    "en": {
        "welcome": "Hello! 🌸 I'm the virtual assistant of Abijou Clinic.\n\n"
                   "Ask me about acne, redness, pigmentation, lifting and skin booster treatments, "
                   "check prices, and book at our branches in Mongolia (4) and Korea (8).\n\n"
                   "Type your question or pick below 👇",
        "menu": "How can I help? 👇",
        "services_button": "💆 Treatments",
        "branches_button": "📍 Branches",
        "promo_button": "🎁 Offers",
        "contact_button": "☎ Contact",
        "human_button": "👩‍⚕️ Talk to staff",
        "home_button": "🏠 Menu",
        "categories_button": "⬅ Categories",
        "pick_category": "What would you like to treat?",
        "category_footer": "The number of sessions depends on your skin. Tap a button below to book.",
        "pick_country": "Which country's branches would you like to see?",
        "branches_header": "{flag} Our branches in {country}:",
        "branches_footer": "Pick a branch to book there.",
        "promo": "🎁 Current offers:\n{lines}",
        "contact": "Contact us:\n{lines}",
        "human": "Our coordinator will reply in this chat shortly. If it's urgent, please call:\n{lines}",
        "fallback_miss": "Sorry, I don't have information about that. Please call us for details:\n{lines}",
        "language": "English",
    },
    "ko": {
        "welcome": "안녕하세요! 🌸 아비쥬의원 가상 상담원입니다.\n\n"
                   "여드름, 홍조, 기미·잡티, 리프팅, 스킨부스터 시술 문의와 가격 안내, "
                   "몽골(4개)·한국(8개) 지점 예약을 도와드립니다.\n\n"
                   "궁금한 점을 입력하시거나 아래에서 선택해 주세요 👇",
        "menu": "무엇을 도와드릴까요? 👇",
        "services_button": "💆 시술·가격",
        "branches_button": "📍 지점 안내",
        "promo_button": "🎁 이벤트",
        "contact_button": "☎ 연락처",
        "human_button": "👩‍⚕️ 상담원 연결",
        "home_button": "🏠 메뉴",
        "categories_button": "⬅ 카테고리",
        "pick_category": "어떤 고민을 해결하고 싶으세요?",
        "category_footer": "시술 횟수는 피부 상태에 따라 다릅니다. 예약은 아래 버튼을 눌러 주세요.",
        "pick_country": "어느 나라 지점을 보시겠어요?",
        "branches_header": "{flag} {country} 지점 안내:",
        "branches_footer": "예약할 지점을 선택해 주세요.",
        "promo": "🎁 진행 중인 이벤트:\n{lines}",
        "contact": "연락처:\n{lines}",
        "human": "코디네이터가 곧 이 채팅으로 답변드립니다. 급하신 경우 전화 주세요:\n{lines}",
        "fallback_miss": "죄송합니다. 해당 내용은 안내해 드리기 어렵습니다. 자세한 사항은 전화로 문의해 주세요:\n{lines}",
        "language": "Korean",
    },
}

ANSWER_SYSTEM = """You are the virtual assistant of "{name}", a {kind}, answering patients on
Instagram, Facebook Messenger and the website chat.

Language: reply in the language of the patient's LAST message: Mongolian (Cyrillic;
also when they typed Mongolian in Latin letters), Korean, or English. If unclear,
reply in {default_language}. The clinic information below is in {data_language};
translate facts faithfully and keep treatment brand names (NeoBeam, Gold PTT,
Rejuran, Excel-V...) as they are.

Rules:
- Use ONLY the clinic information below. Never invent prices, treatments, branches,
  doctors, discounts or policies.
- Mongolia branches charge in MNT (₮), Korea branches in KRW (₩). When you quote a
  price, say which country it is for; if you don't know where they will go, give both.
- You are not a doctor. Don't diagnose and never promise results. For questions about
  their own skin, explain which of our treatments are used for that concern, say the
  number of sessions depends on each person's skin, and suggest a dermatologist
  consultation.
- Anything urgent (allergic reaction, strong pain, swelling or infection after a
  procedure): tell them to call the branch right away ({phones}).
- If the answer isn't in the information, say you don't have it and give the phone numbers.
- If the question has nothing to do with the clinic, politely say you can only help
  with {name}.
- Keep it short: 1-5 sentences, plain text, no markdown, at most one emoji. A price
  list may use short lines starting with "• ".
- If asked whether you are a bot, say you are {name}'s virtual assistant.
- Patients can book right here in this chat. If the patient asks to book, make an
  appointment or reserve (not just asking about a policy), reply with one short
  sentence and end with the exact token [BOOK]. If they named a treatment, write
  [BOOK:<service id>] instead, and if they also named a branch,
  [BOOK:<service id>:<branch id>]. Service ids: {service_ids}.
  Branch ids: {branch_ids}.
  Use the token only when they asked to book; when you merely suggest booking, don't
  add it (the buttons let them book). Never ask for their name, phone or time
  yourself; the booking form does that.

CLINIC INFORMATION
{knowledge}"""


def _qr(pairs) -> List[QuickReply]:
    return [QuickReply(title=t, payload=p) for t, p in pairs]


class ClinicBot:
    def __init__(self, llm, store, clinic: Clinic, calendar=None):
        self.llm = llm
        self.store = store
        self.clinic = clinic
        self.booking = BookingFlow(store, clinic, calendar)

    def handle(self, session: Session, user_input: str) -> List[OutMsg]:
        text = (user_input or "").strip()
        idle = time.time() - session.updated_at if session.updated_at else 0
        if settings.SESSION_FRESH_HOURS and idle > settings.SESSION_FRESH_HOURS * 3600:
            # Back after a long gap: a clean start, as if they'd never written (language kept).
            session.data = {k: session.data[k] for k in ("lang", "lang_locked") if k in session.data}
            session.state = "START"
        out = self._route(session, text)
        self.store.save_session(session)
        return out

    # ---- language ----
    def _update_lang(self, session: Session, text: str) -> str:
        d = session.data
        if (not d.get("lang_locked") and text and not PAYLOAD_RE.match(text)
                and session.state not in NO_LANG_DETECT_STATES and text.lower() not in HOME_WORDS):
            detected = detect_lang(text)
            if detected:
                d["lang"] = detected
        if not d.get("lang"):
            d["lang"] = DEFAULT_LANG
        return d["lang"]

    # ---- menus ----
    def _menu_buttons(self, lang: str, with_lang: bool = False) -> List[QuickReply]:
        u = UI[lang]
        buttons = [(BOOK_TEXT[lang]["book_button"], "BOOK"), (u["services_button"], "MENU_SERVICES"),
                   (u["branches_button"], "MENU_BRANCHES"), (u["promo_button"], "MENU_PROMO"),
                   (u["contact_button"], "MENU_CONTACT"), (u["human_button"], "MENU_HUMAN")]
        if with_lang:
            buttons += [LANG_BUTTONS[x] for x in ("mn", "en", "ko") if x != lang]
        return _qr(buttons)

    def _greet(self, session: Session, lang: str) -> List[OutMsg]:
        session.state = "CHAT"
        session.data.pop("book", None)
        session.data["history"] = []
        return [OutMsg(UI[lang]["welcome"], self._menu_buttons(lang, with_lang=True))]

    def _menu(self, session: Session, lang: str) -> List[OutMsg]:
        session.state = "CHAT"
        return [OutMsg(UI[lang]["menu"], self._menu_buttons(lang, with_lang=True))]

    def _categories(self, lang: str) -> List[OutMsg]:
        buttons = [(f"{c['emoji']} {tr(c['name'], lang)}", f"CAT_{c['id']}") for c in self.clinic.categories]
        buttons.append((UI[lang]["home_button"], "HOME"))
        return [OutMsg(UI[lang]["pick_category"], _qr(buttons))]

    def _category(self, lang: str, category_id: str) -> List[OutMsg]:
        cat = next((c for c in self.clinic.categories if c["id"] == category_id), None)
        services = self.clinic.services_in(category_id)
        if not cat or not services:
            return self._categories(lang)
        body = f"{cat['emoji']} {tr(cat['name'], lang)}\n\n" + "\n\n".join(
            self.clinic.service_text(s, lang) + f"\n{tr(s['details'], lang)}" for s in services)
        body += "\n\n" + UI[lang]["category_footer"]
        buttons = [(f"📅 {tr(s['short'], lang)}", f"BOOKS_{s['id']}") for s in services]
        buttons += [(UI[lang]["categories_button"], "MENU_SERVICES"), (UI[lang]["home_button"], "HOME")]
        return [OutMsg(body, _qr(buttons))]

    def _countries(self, lang: str) -> List[OutMsg]:
        buttons = [(f"{c['flag']} {tr(c['name'], lang)}", f"BRANCHES_{c['id']}")
                   for c in self.clinic.countries.values()]
        buttons.append((UI[lang]["home_button"], "HOME"))
        return [OutMsg(UI[lang]["pick_country"], _qr(buttons))]

    def _branches(self, lang: str, country_id: str) -> List[OutMsg]:
        country = self.clinic.countries.get(country_id)
        if not country:
            return self._countries(lang)
        u = UI[lang]
        branches = self.clinic.branches_in(country_id)
        body = (u["branches_header"].format(flag=country["flag"], country=tr(country["name"], lang)) + "\n\n"
                + "\n\n".join(self.clinic.branch_text(b, lang) for b in branches)
                + f"\n\n☎ {self.clinic.phone(country_id)}\n\n" + u["branches_footer"])
        buttons = [(f"📅 {tr(b['name'], lang)}", f"BOOKB_{b['id']}") for b in branches]
        others = [c for c in self.clinic.countries.values() if c["id"] != country_id]
        buttons += [(f"{c['flag']} {tr(c['name'], lang)}", f"BRANCHES_{c['id']}") for c in others]
        buttons.append((u["home_button"], "HOME"))
        return [OutMsg(body, _qr(buttons))]

    def _promo(self, lang: str) -> List[OutMsg]:
        lines = "\n".join(f"• {tr(p, lang)}" for p in self.clinic.data.get("promotions", []))
        return [OutMsg(UI[lang]["promo"].format(lines=lines), self._menu_buttons(lang))]

    def _contact(self, lang: str, key: str = "contact") -> List[OutMsg]:
        return [OutMsg(UI[lang][key].format(lines=self.clinic.contact_lines(lang)), self._menu_buttons(lang))]

    # ---- routing ----
    def _route(self, session: Session, text: str) -> List[OutMsg]:
        d = session.data
        if text in LANG_PAYLOADS:
            d.update(lang=LANG_PAYLOADS[text], lang_locked=True)
            return self._greet(session, d["lang"])

        lang = self._update_lang(session, text)
        low = text.lower().strip(" .!?,")

        if text in HOME_PAYLOADS or low in HOME_WORDS:
            return self._greet(session, lang)
        if session.state == "START" and (not text or low in GREETINGS):
            return self._greet(session, lang)
        if text == "MENU" or low in MENU_WORDS:
            d.pop("book", None)
            return self._menu(session, lang)

        if session.state.startswith("BOOK_"):
            other_button = bool(PAYLOAD_RE.match(text)) and not BOOKING_PAYLOAD_RE.match(text)
            question = (session.state in PICK_STATES and not PAYLOAD_RE.match(text)
                        and not self.booking.understands(session, lang, text))
            if other_button or question:
                # a menu button or a question in the middle of booking: answer that instead
                d.pop("book", None)
                session.state = "CHAT"
            else:
                msgs, done = self.booking.handle(session, lang, text)
                return self._finish_booking(session, lang, msgs, done)

        session.state = "CHAT"
        if text == "BOOK":
            return self._start_booking(session, lang)
        if text.startswith("BOOKS_"):
            return self._start_booking(session, lang, service=text[6:])
        if text.startswith("BOOKB_"):
            return self._start_booking(session, lang, branch=text[6:])
        if text == "MENU_SERVICES":
            return self._categories(lang)
        if text.startswith("CAT_"):
            return self._category(lang, text[4:])
        if text == "MENU_BRANCHES":
            return self._countries(lang)
        if text.startswith("BRANCHES_"):
            return self._branches(lang, text[9:])
        if text == "MENU_PROMO":
            return self._promo(lang)
        if text == "MENU_CONTACT":
            return self._contact(lang)
        if text == "MENU_HUMAN":
            return self._contact(lang, "human")
        if not text or PAYLOAD_RE.match(text):     # an old or unknown button
            return self._menu(session, lang)
        return self._answer(session, lang, text)

    def _start_booking(self, session, lang, before: Optional[List[OutMsg]] = None,
                       service: str = "", branch: str = "") -> List[OutMsg]:
        msgs, done = self.booking.start(session, lang, service=service, branch=branch)
        return self._finish_booking(session, lang, (before or []) + msgs, done)

    def _finish_booking(self, session, lang, msgs: List[OutMsg], done: bool) -> List[OutMsg]:
        if not done:
            return msgs
        session.state = "CHAT"
        if msgs:
            msgs[-1].quick_replies = self._menu_buttons(lang)
        return msgs

    # ---- answering ----
    def _answer(self, session: Session, lang: str, text: str) -> List[OutMsg]:
        reply = self.llm.chat(self._build_messages(session, lang, text), timeout=40)
        service, branch = "", ""
        if reply:
            token = BOOK_TOKEN_RE.search(reply)
            reply = BOOK_TOKEN_RE.sub("", reply).replace("**", "").strip()
            wants = bool(token) and not reply.endswith("?")   # an offer; only their yes books
            if token:
                service, branch = token.group(1) or "", token.group(2) or ""
        else:
            wants = wants_booking(text)
            matched = self.clinic.match_service(text)
            service = matched["id"] if matched else ""
            reply = "" if wants else self._keyword_answer(lang, text)

        history = session.data.get("history", [])
        history += [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
        session.data["history"] = history[-HISTORY_TURNS * 2:]

        if wants:
            return self._start_booking(session, lang, before=[OutMsg(reply)] if reply else None,
                                       service=service, branch=branch)
        return [OutMsg(reply, self._menu_buttons(lang))]

    def _build_messages(self, session: Session, lang: str, text: str) -> List[dict]:
        c = self.clinic
        system = ANSWER_SYSTEM.format(
            name=c.name(lang), kind=tr(c.data["kind"], "en"),
            phones=", ".join(f"{tr(x['label'], 'en')} {x['phone']}" for x in c.data["contacts"].values()),
            default_language=UI[lang]["language"], data_language=UI[lang]["language"],
            service_ids=", ".join(s["id"] for s in c.services),
            branch_ids=", ".join(b["id"] for b in c.branches),
            knowledge=c.knowledge(lang),
        )
        return ([{"role": "system", "content": system}]
                + session.data.get("history", [])
                + [{"role": "user", "content": text}])

    def _keyword_answer(self, lang: str, text: str) -> str:
        """Used only when the LLM is unavailable. A treatment named outright beats a
        loosely matching FAQ."""
        service = self.clinic.match_service(text)
        if service:
            return self.clinic.service_text(service, lang) + "\n" + tr(service["details"], lang)
        faq = self.clinic.match_faq(text, lang)
        if faq:
            return tr(faq["answer"], lang)
        return UI[lang]["fallback_miss"].format(lines=self.clinic.contact_lines(lang))
