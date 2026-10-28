"""Appointment booking: treatment -> country -> branch -> day -> time -> name
-> phone -> confirm -> saved (and put in Google Calendar when one is set up).

Button-driven so it works even when the LLM is down. Free slots come from each
branch's opening hours in data/clinic.yaml, in that branch's own time zone
(Ulaanbaatar or Seoul), minus bookings already made: our own database always,
plus the clinic's Google Calendar when a key is configured. A branch can treat
`capacity` patients at the same time.
"""
import re
from datetime import date, datetime, time, timedelta
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

from . import crm, notify, payment
from .clinic import Clinic, money, tr
from .models import OutMsg, QuickReply, Session

WEEKDAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAY_NAMES = {
    "mn": ["Даваа", "Мягмар", "Лхагва", "Пүрэв", "Баасан", "Бямба", "Ням"],
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    "ko": ["월", "화", "수", "목", "금", "토", "일"],
}
MONTHS_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

SLOT_STEP_MINUTES = 30
LEAD_MINUTES = 60
SEARCH_DAYS = 14
MAX_DAY_BUTTONS = 7
MAX_TIME_BUTTONS = 12

BUTTON_PAYLOAD_RE = re.compile(r"^(BOOK|BOK|BCANCEL|MENU|HOME|[A-Z]+_\w+)$")
CANCEL_WORDS = {"болих", "болъё", "цуцлах", "cancel", "stop", "bolih", "tsutslah", "취소", "그만"}
PICK_STATES = ("BOOK_SERVICE", "BOOK_COUNTRY", "BOOK_BRANCH", "BOOK_DAY", "BOOK_TIME")

# Only used when the LLM is unavailable; otherwise the LLM flags booking intent.
BOOK_INTENT = ["цаг захиал", "захиалмаар", "захиалга хий", "цаг авмаар", "цаг авах",
               "tsag zahial", "zahialmaar", "tsag avmaar", "tsag awmaar", "tsag avah",
               "book an appointment", "make an appointment", "i want to book", "i'd like to book",
               "schedule an appointment", "book a visit", "book a consultation",
               "예약하고", "예약할", "예약 하고", "예약 할", "예약해", "예약 원"]

T = {
    "mn": {
        "book_button": "📅 Цаг захиалах",
        "cancel_button": "✖ Болих",
        "back_button": "⬅ Буцах",
        "confirm_button": "✅ Баталгаажуулах",
        "ask_service": "Ямар эмчилгээнд цаг авах вэ? Мэдэхгүй бол «Эмчийн зөвлөгөө»-г сонгоорой.",
        "ask_country": "Аль улсын салбарт очих вэ?",
        "ask_branch": "Аль салбарт очих вэ?",
        "ask_day": "Аль өдөр тохиромжтой вэ? ({tz})",
        "ask_time": "{day} — сул цагуудаас сонгоно уу ({tz}):",
        "ask_name": "Захиалгыг хэний нэр дээр бүртгэх вэ? Нэрээ бичнэ үү.",
        "ask_phone": "Холбогдох утасны дугаараа бичнэ үү (Монгол 8 оронтой эсвэл Солонгос 010-оор эхэлсэн).",
        "bad_phone": "Утасны дугаар буруу байна. Жишээ нь 99112233 эсвэл 010-1234-5678 гэж бичнэ үү.",
        "bad_name": "Нэрээ бичнэ үү.",
        "no_days": "Уучлаарай, энэ салбарт ойрын 2 долоо хоногт сул цаг алга. {phone} утсаар холбогдоно уу.",
        "day_full": "Уучлаарай, тэр өдрийн цаг дүүрчихлээ. Өөр өдөр сонгоно уу.",
        "slot_taken": "Уучлаарай, тэр цагийг саяхан өөр хүн авчихлаа. Өөр цаг сонгоно уу.",
        "pick_button": "Доорх товчнуудаас сонгоно уу.",
        "summary": "Захиалгаа шалгана уу:\n\n💆 {service}\n📍 {branch}\n📅 {when} ({tz})\n"
                   "💰 {price}\n👤 {name}\n📞 {phone}",
        "done": "✅ Цаг захиалга бүртгэгдлээ!\n\n💆 {service}\n📍 {branch}, {address}\n📅 {when} ({tz})\n"
                "💰 {price}\n\n{payment}\nЦагаа өөрчлөх, цуцлах бол 24 цагийн өмнө энд бичих эсвэл "
                "{phone} утсаар холбогдоно уу.",
        "pay_at_clinic": "Төлбөрийг эмнэлэг дээр төлнө.",
        "pay_link": "Урьдчилгаа төлбөр: {link}",
        "price_from": "{price}-өөс",
        "cancelled": "Захиалгыг цуцаллаа. Өөр асуух зүйл байвал бичээрэй.",
        "today": "Өнөөдөр",
        "tomorrow": "Маргааш",
    },
    "en": {
        "book_button": "📅 Book",
        "cancel_button": "✖ Cancel",
        "back_button": "⬅ Back",
        "confirm_button": "✅ Confirm",
        "ask_service": "Which treatment would you like to book? Not sure? Pick “Consultation”.",
        "ask_country": "Which country's branch would you like to visit?",
        "ask_branch": "Which branch would you like to visit?",
        "ask_day": "Which day works for you? ({tz})",
        "ask_time": "{day} — pick a free time ({tz}):",
        "ask_name": "What name should the booking be under?",
        "ask_phone": "What's your phone number? (Mongolian 8 digits or Korean starting with 010)",
        "bad_phone": "That doesn't look like a phone number. Please send e.g. 99112233 or 010-1234-5678.",
        "bad_name": "Please type your name.",
        "no_days": "Sorry, this branch has no free slots in the next 2 weeks. Please call {phone}.",
        "day_full": "Sorry, that day just filled up. Please pick another day.",
        "slot_taken": "Sorry, someone just took that time. Please pick another one.",
        "pick_button": "Please choose one of the buttons below.",
        "summary": "Please check your booking:\n\n💆 {service}\n📍 {branch}\n📅 {when} ({tz})\n"
                   "💰 {price}\n👤 {name}\n📞 {phone}",
        "done": "✅ Your appointment is booked!\n\n💆 {service}\n📍 {branch}, {address}\n📅 {when} ({tz})\n"
                "💰 {price}\n\n{payment}\nTo change or cancel, message us here or call {phone} at least "
                "24 hours before.",
        "pay_at_clinic": "You pay at the clinic.",
        "pay_link": "Deposit: {link}",
        "price_from": "from {price}",
        "cancelled": "Booking cancelled. Let me know if you have any other questions.",
        "today": "Today",
        "tomorrow": "Tomorrow",
    },
    "ko": {
        "book_button": "📅 예약하기",
        "cancel_button": "✖ 취소",
        "back_button": "⬅ 뒤로",
        "confirm_button": "✅ 예약 확정",
        "ask_service": "어떤 시술을 예약하시겠어요? 잘 모르시면 “전문의 상담”을 선택해 주세요.",
        "ask_country": "어느 나라 지점을 방문하시겠어요?",
        "ask_branch": "어느 지점을 방문하시겠어요?",
        "ask_day": "어느 날이 편하세요? ({tz})",
        "ask_time": "{day} — 예약 가능한 시간을 선택해 주세요 ({tz}):",
        "ask_name": "예약자 성함을 입력해 주세요.",
        "ask_phone": "연락처를 입력해 주세요 (몽골 8자리 또는 010으로 시작하는 한국 번호).",
        "bad_phone": "전화번호 형식이 올바르지 않습니다. 예: 010-1234-5678 또는 99112233",
        "bad_name": "성함을 입력해 주세요.",
        "no_days": "죄송합니다. 이 지점은 2주 내 예약 가능한 시간이 없습니다. {phone}로 연락해 주세요.",
        "day_full": "죄송합니다. 그날은 예약이 마감되었습니다. 다른 날을 선택해 주세요.",
        "slot_taken": "죄송합니다. 방금 다른 분이 그 시간을 예약했습니다. 다른 시간을 선택해 주세요.",
        "pick_button": "아래 버튼 중에서 선택해 주세요.",
        "summary": "예약 내용을 확인해 주세요:\n\n💆 {service}\n📍 {branch}\n📅 {when} ({tz})\n"
                   "💰 {price}\n👤 {name}\n📞 {phone}",
        "done": "✅ 예약이 완료되었습니다!\n\n💆 {service}\n📍 {branch}, {address}\n📅 {when} ({tz})\n"
                "💰 {price}\n\n{payment}\n예약 변경·취소는 24시간 전까지 이 채팅이나 {phone}로 연락해 주세요.",
        "pay_at_clinic": "결제는 내원 시 진행됩니다.",
        "pay_link": "예약금 결제: {link}",
        "price_from": "{price}부터",
        "cancelled": "예약을 취소했습니다. 다른 궁금한 점이 있으면 말씀해 주세요.",
        "today": "오늘",
        "tomorrow": "내일",
    },
}


def opening_hours(hours: dict, day: date, tz: ZoneInfo) -> Optional[Tuple[datetime, datetime]]:
    spec = hours.get(WEEKDAY_KEYS[day.weekday()])
    if not spec:
        return None
    start_s, end_s = spec.split("-")
    return (datetime.combine(day, time.fromisoformat(start_s.strip()), tz),
            datetime.combine(day, time.fromisoformat(end_s.strip()), tz))


def free_slots(hours: dict, day: date, minutes: int, busy, now: datetime, tz: ZoneInfo,
               capacity: int = 1) -> List[datetime]:
    """Start times on `day` with fewer than `capacity` bookings overlapping."""
    window = opening_hours(hours, day, tz)
    if not window:
        return []
    open_at, close_at = window
    earliest = now + timedelta(minutes=LEAD_MINUTES)
    slots, t = [], open_at
    length = timedelta(minutes=minutes)
    while t + length <= close_at:
        if t >= earliest and sum(t < b[1] and t + length > b[0] for b in busy) < capacity:
            slots.append(t)
        t += timedelta(minutes=SLOT_STEP_MINUTES)
    return slots


def pick_evenly(items: list, n: int) -> list:
    if len(items) <= n:
        return items
    step = (len(items) - 1) / (n - 1)
    return [items[round(i * step)] for i in range(n)]


def normalize_phone(text: str) -> Optional[str]:
    """Mongolian 8 digits (+976 optional) or a Korean mobile (010..., +82 10...)."""
    digits = re.sub(r"\D", "", text)
    if len(digits) == 11 and digits.startswith("976"):
        digits = digits[3:]
    if len(digits) == 8:
        return digits
    if digits.startswith("82") and len(digits) in (11, 12):
        digits = "0" + digits[2:]
    if len(digits) == 11 and digits.startswith("01"):
        return f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"
    return None


def wants_booking(text: str) -> bool:
    low = text.lower()
    return any(k in low for k in BOOK_INTENT)


def day_label(day: date, lang: str, today: date) -> str:
    if day == today:
        return T[lang]["today"]
    if day == today + timedelta(days=1):
        return T[lang]["tomorrow"]
    name = WEEKDAY_NAMES[lang][day.weekday()]
    if lang == "en":
        return f"{name} {day.month}/{day.day}"
    if lang == "ko":
        return f"{day.month}/{day.day} ({name})"
    return f"{day.month}/{day.day} {name}"


def when_label(start: datetime, lang: str) -> str:
    name = WEEKDAY_NAMES[lang][start.weekday()]
    if lang == "mn":
        return f"{start.month}-р сарын {start.day}, {name}, {start:%H:%M}"
    if lang == "ko":
        return f"{start.month}월 {start.day}일 ({name}) {start:%H:%M}"
    return f"{name}, {MONTHS_EN[start.month - 1]} {start.day}, {start:%H:%M}"


def _qr(pairs) -> List[QuickReply]:
    return [QuickReply(title=t, payload=p) for t, p in pairs]


class BookingFlow:
    def __init__(self, store, clinic: Clinic, calendar=None):
        self.store = store
        self.clinic = clinic
        self.calendar = calendar

    # ---- entry ----
    def start(self, session: Session, lang: str, service: str = "",
              branch: str = "") -> Tuple[List[OutMsg], bool]:
        """service / branch: preselected ids (from a menu button or the model)."""
        book = session.data["book"] = {}
        if self.clinic.service(service):
            book["service"] = service
        b = self.clinic.branch(branch)
        if b:
            book.update(branch=b["id"], country=b["country"])
        return self._next(session, lang)

    def handle(self, session: Session, lang: str, text: str) -> Tuple[List[OutMsg], bool]:
        """Returns (messages, done). done=True hands the conversation back to chat."""
        t = T[lang]
        if text == "BCANCEL" or text.lower().strip(" .!") in CANCEL_WORDS:
            session.data.pop("book", None)
            return [OutMsg(t["cancelled"])], True

        book = session.data.setdefault("book", {})
        state = session.state

        if state == "BOOK_SERVICE":
            service = self._match_option(self.clinic.services, text, "BSVC_", extra="short")
            if not service:
                return self._ask_service(session, lang, t["pick_button"]), False
            book["service"] = service
            return self._next(session, lang)

        if state == "BOOK_COUNTRY":
            country = self._match_option(list(self.clinic.countries.values()), text, "BCTRY_")
            if not country:
                return self._ask_country(session, lang, t["pick_button"]), False
            book["country"] = country
            return self._next(session, lang)

        if state == "BOOK_BRANCH":
            if text == "BBACK":
                book.pop("country", None)
                return self._next(session, lang)
            branch = self._match_option(self.clinic.branches_in(book.get("country", "")), text, "BBR_")
            if not branch:
                return self._ask_branch(session, lang, t["pick_button"]), False
            book["branch"] = branch
            return self._next(session, lang)

        if state == "BOOK_DAY":
            day = self._match_day(session, text)
            if not day:
                return self._ask_day(session, lang, t["pick_button"])
            book["day"] = day.isoformat()
            return self._ask_time(session, lang)

        if state == "BOOK_TIME":
            start = self._match_time(session, text)
            if not start:
                msgs, done = self._ask_time(session, lang)
                return [OutMsg(t["pick_button"])] + msgs, done
            book["start"] = start.isoformat()
            session.state = "BOOK_NAME"
            return [OutMsg(t["ask_name"], _qr([(t["cancel_button"], "BCANCEL")]))], False

        if state == "BOOK_NAME":
            name = text.strip()
            if not re.search(r"[^\W\d_]", name) or len(name) > 60 or BUTTON_PAYLOAD_RE.match(name):
                return [OutMsg(t["bad_name"], _qr([(t["cancel_button"], "BCANCEL")]))], False
            book["name"] = name
            session.state = "BOOK_PHONE"
            return [OutMsg(t["ask_phone"], _qr([(t["cancel_button"], "BCANCEL")]))], False

        if state == "BOOK_PHONE":
            phone = normalize_phone(text)
            if not phone:
                return [OutMsg(t["bad_phone"], _qr([(t["cancel_button"], "BCANCEL")]))], False
            book["phone"] = phone
            session.state = "BOOK_CONFIRM"
            return [self._summary(lang, book)], False

        if state == "BOOK_CONFIRM":
            if text != "BOK":
                return [OutMsg(t["pick_button"]), self._summary(lang, book)], False
            return self._book(session, lang)

        session.data.pop("book", None)
        return [], True

    def understands(self, session: Session, lang: str, text: str) -> bool:
        """Whether `text` answers the current pick step (a button, its number, "10:00"...).
        Anything else is a question, and the bot answers it instead of insisting."""
        if session.state not in PICK_STATES or text in ("BCANCEL", "BOK", "BBACK"):
            return True
        book = session.data.get("book", {})
        if session.state == "BOOK_SERVICE":
            return bool(self._match_option(self.clinic.services, text, "BSVC_", extra="short"))
        if session.state == "BOOK_COUNTRY":
            return bool(self._match_option(list(self.clinic.countries.values()), text, "BCTRY_"))
        if session.state == "BOOK_BRANCH":
            return bool(self._match_option(self.clinic.branches_in(book.get("country", "")), text, "BBR_"))
        if session.state == "BOOK_DAY":
            return bool(self._match_day(session, text))
        return bool(self._match_time(session, text))

    # ---- steps ----
    def _next(self, session, lang) -> Tuple[List[OutMsg], bool]:
        book = session.data["book"]
        if "service" not in book:
            return self._ask_service(session, lang), False
        if "branch" not in book:
            if "country" not in book and len(self.clinic.countries) > 1:
                return self._ask_country(session, lang), False
            book.setdefault("country", next(iter(self.clinic.countries)))
            return self._ask_branch(session, lang), False
        return self._ask_day(session, lang)

    def _ask_service(self, session, lang, prefix: str = "") -> List[OutMsg]:
        t = T[lang]
        session.state = "BOOK_SERVICE"
        buttons = [(tr(s["short"], lang), f"BSVC_{s['id']}") for s in self.clinic.services[:MAX_TIME_BUTTONS]]
        buttons.append((t["cancel_button"], "BCANCEL"))
        return [OutMsg((prefix + "\n\n" if prefix else "") + t["ask_service"], _qr(buttons))]

    def _ask_country(self, session, lang, prefix: str = "") -> List[OutMsg]:
        t = T[lang]
        session.state = "BOOK_COUNTRY"
        buttons = [(f"{c['flag']} {tr(c['name'], lang)}", f"BCTRY_{c['id']}")
                   for c in self.clinic.countries.values()]
        buttons.append((t["cancel_button"], "BCANCEL"))
        return [OutMsg((prefix + "\n\n" if prefix else "") + t["ask_country"], _qr(buttons))]

    def _ask_branch(self, session, lang, prefix: str = "") -> List[OutMsg]:
        t = T[lang]
        session.state = "BOOK_BRANCH"
        branches = self.clinic.branches_in(session.data["book"]["country"])
        buttons = [(tr(b["name"], lang), f"BBR_{b['id']}") for b in branches]
        if len(self.clinic.countries) > 1:
            buttons.append((t["back_button"], "BBACK"))
        buttons.append((t["cancel_button"], "BCANCEL"))
        body = t["ask_branch"] + "\n\n" + "\n".join(self.clinic.branch_text(b, lang) for b in branches)
        return [OutMsg((prefix + "\n\n" if prefix else "") + body, _qr(buttons))]

    def _ask_day(self, session, lang, prefix: str = "") -> Tuple[List[OutMsg], bool]:
        t = T[lang]
        book = session.data["book"]
        branch, tz = self._branch_tz(book)
        now = datetime.now(tz)
        busy = self._busy(branch, now, now + timedelta(days=SEARCH_DAYS + 1))
        days = []
        for i in range(SEARCH_DAYS):
            day = now.date() + timedelta(days=i)
            if self._free(book, day, busy, now):
                days.append(day)
            if len(days) == MAX_DAY_BUTTONS:
                break
        if not days:
            session.data.pop("book", None)
            phone = self.clinic.phone(branch["country"])
            return [OutMsg(t["no_days"].format(phone=phone))], True
        session.state = "BOOK_DAY"
        book["days"] = [d.isoformat() for d in days]
        buttons = [(day_label(d, lang, now.date()), f"BDAY_{d:%Y%m%d}") for d in days]
        buttons.append((t["cancel_button"], "BCANCEL"))
        text = t["ask_day"].format(tz=self._tz_note(branch, lang))
        return [OutMsg((prefix + "\n\n" if prefix else "") + text, _qr(buttons))], False

    def _ask_time(self, session, lang) -> Tuple[List[OutMsg], bool]:
        t = T[lang]
        slots = self._slots_for(session)
        if not slots:
            return self._ask_day(session, lang, t["day_full"])
        session.state = "BOOK_TIME"
        book = session.data["book"]
        branch, tz = self._branch_tz(book)
        day = date.fromisoformat(book["day"])
        on_the_hour = [s for s in slots if s.minute == 0]
        shown = pick_evenly(on_the_hour if len(slots) > MAX_TIME_BUTTONS and on_the_hour else slots,
                            MAX_TIME_BUTTONS)
        buttons = [(f"{s:%H:%M}", f"BTIME_{s:%H%M}") for s in shown]
        buttons.append((t["cancel_button"], "BCANCEL"))
        label = day_label(day, lang, datetime.now(tz).date())
        return [OutMsg(t["ask_time"].format(day=label, tz=self._tz_note(branch, lang)), _qr(buttons))], False

    def _price(self, service: dict, branch: dict, lang: str) -> Tuple[Optional[int], str, str]:
        """(amount, currency, label) at this branch; options mean the price is a starting price."""
        currency = self.clinic.country_of(branch)["currency"]
        amount = service["price"].get(currency)
        label = money(amount, currency, lang) if amount is not None else "—"
        if service.get("options") and amount:
            label = T[lang]["price_from"].format(price=label)
        return amount, currency, label

    def _summary(self, lang, book) -> OutMsg:
        t = T[lang]
        service = self.clinic.service(book["service"])
        branch, _ = self._branch_tz(book)
        text = t["summary"].format(
            service=tr(service["name"], lang), branch=tr(branch["name"], lang),
            when=when_label(datetime.fromisoformat(book["start"]), lang),
            tz=self._tz_note(branch, lang), price=self._price(service, branch, lang)[2],
            name=book["name"], phone=book["phone"],
        )
        return OutMsg(text, _qr([(t["confirm_button"], "BOK"), (t["cancel_button"], "BCANCEL")]))

    def _book(self, session, lang) -> Tuple[List[OutMsg], bool]:
        t = T[lang]
        book = session.data["book"]
        service = self.clinic.service(book["service"])
        branch, tz = self._branch_tz(book)
        start = datetime.fromisoformat(book["start"])
        end = start + timedelta(minutes=service["minutes"])

        day_start = datetime.combine(start.date(), time.min, tz)
        busy = self._busy(branch, day_start, day_start + timedelta(days=1))
        if sum(start < b[1] and end > b[0] for b in busy) >= branch["capacity"]:
            msgs, done = self._ask_time(session, lang)
            return [OutMsg(t["slot_taken"])] + msgs, done

        amount, currency, price_label = self._price(service, branch, lang)
        event_id, calendar_status = None, "no_calendar"
        calendar_id = self._calendar_id()
        if self.calendar and calendar_id:
            try:
                event = self.calendar.create_event(
                    calendar_id,
                    summary=f"{tr(service['short'], 'mn')} — {book['name']} ({tr(branch['name'], 'mn')})",
                    description=(f"Утас: {book['phone']}\nЭмчилгээ: {tr(service['name'], 'mn')}\n"
                                 f"Салбар: {tr(branch['name'], 'mn')}\nҮнэ: {price_label}\n"
                                 f"Хэл: {lang}\nСуваг: {session.channel} (чатбот)"),
                    start=start, end=end, location=tr(branch["address"], "mn"),
                    private={"branch": branch["id"], "source": "chatbot", "sender": session.sender_id,
                             "service": service["id"], "name": book["name"], "phone": book["phone"]},
                )
                event_id, calendar_status = event.get("id"), "booked"
            except Exception as e:
                print(f"[booking] calendar insert failed: {e}")
                calendar_status = "calendar_failed"

        row = {
            "sender_id": session.sender_id, "channel": session.channel, "lang": lang,
            "service_id": service["id"], "branch_id": branch["id"], "country": branch["country"],
            "start_at": start.isoformat(), "end_at": end.isoformat(),
            "name": book["name"], "phone": book["phone"], "price": amount, "currency": currency,
            "event_id": event_id, "calendar_status": calendar_status,
        }
        row["id"] = self.store.save_booking(row)
        crm.enqueue(self.store, "booking", row["id"])   # patient + appointment in bas.mn
        link = payment.request_deposit(row)        # None until online payment is added
        if link:
            self.store.set_payment(row["id"], "pending", link)
        notify.booking(row, service_name=tr(service["name"], "mn"), branch_name=tr(branch["name"], "mn"),
                       price=money(amount, currency) if amount is not None else "—")

        session.data.pop("book", None)
        session.data["last_booking"] = row["id"]
        return [OutMsg(t["done"].format(
            service=tr(service["name"], lang), branch=tr(branch["name"], lang),
            address=tr(branch["address"], lang), when=when_label(start, lang),
            tz=self._tz_note(branch, lang), price=price_label,
            payment=t["pay_link"].format(link=link) if link else t["pay_at_clinic"],
            phone=self.clinic.phone(branch["country"]),
        ))], True

    # ---- helpers ----
    def _branch_tz(self, book) -> Tuple[dict, ZoneInfo]:
        branch = self.clinic.branch(book["branch"])
        return branch, ZoneInfo(self.clinic.country_of(branch)["tz"])

    def _tz_note(self, branch: dict, lang: str) -> str:
        return tr(self.clinic.country_of(branch)["time_note"], lang)

    def _busy(self, branch: dict, start: datetime, end: datetime) -> list:
        """(start, end) of everything booked at this branch: our database, plus events in
        the clinic's Google Calendar that aren't already one of ours."""
        busy, ours = [], set()
        for b in self.store.branch_bookings(branch["id"], start.isoformat(), end.isoformat()):
            busy.append((datetime.fromisoformat(b["start_at"]), datetime.fromisoformat(b["end_at"])))
            if b["event_id"]:
                ours.add(b["event_id"])
        # appointments staff typed into bas.mn (phone, walk-in), in the branch's own time
        tz = start.tzinfo
        busy += [(s.replace(tzinfo=tz), e.replace(tzinfo=tz)) for s, e in crm.busy(self.store, branch["id"])
                 if e.replace(tzinfo=tz) > start and s.replace(tzinfo=tz) < end]
        calendar_id = self._calendar_id()
        if self.calendar and calendar_id:
            try:
                for ev_start, ev_end, event_id in self.calendar.busy(calendar_id, start, end,
                                                                     branch=branch["id"]):
                    if event_id not in ours:
                        busy.append((ev_start, ev_end))
            except Exception as e:
                print(f"[booking] calendar read failed: {e}")
        return busy

    def _calendar_id(self) -> Optional[str]:
        """The clinic's Google Calendar, created on first use when a key is configured."""
        if not self.calendar:
            return None
        from .gcal import ensure_calendar
        try:
            return ensure_calendar(self.store, self.calendar, self.clinic.id,
                                   f"{self.clinic.name('mn')} · цаг захиалга")
        except Exception as e:
            print(f"[booking] could not create the clinic calendar: {e}")
            return None

    def _slots_for(self, session) -> List[datetime]:
        book = session.data["book"]
        branch, tz = self._branch_tz(book)
        day = date.fromisoformat(book["day"])
        day_start = datetime.combine(day, time.min, tz)
        busy = self._busy(branch, day_start, day_start + timedelta(days=1))
        return self._free(book, day, busy, datetime.now(tz))

    def _free(self, book, day, busy, now) -> List[datetime]:
        branch, tz = self._branch_tz(book)
        minutes = self.clinic.service(book["service"])["minutes"]
        return free_slots(branch["hours"], day, minutes, busy, now, tz, branch["capacity"])

    @staticmethod
    def _match_option(options, text, prefix, extra: str = "") -> Optional[str]:
        if text.startswith(prefix):
            wanted = text[len(prefix):]
            return wanted if any(o["id"] == wanted for o in options) else None
        if text.isdigit() and 1 <= int(text) <= len(options):
            return options[int(text) - 1]["id"]
        low = text.lower().strip()
        if len(low) < 2:
            return None
        for o in options:
            names = list(o["name"].values()) + (list(o[extra].values()) if extra else [])
            if any(n.lower() == low or (len(low) >= 4 and (n.lower() in low or low in n.lower()))
                   for n in names):
                return o["id"]
        return None

    def _match_day(self, session, text) -> Optional[date]:
        days = [date.fromisoformat(d) for d in session.data.get("book", {}).get("days", [])]
        if text.startswith("BDAY_"):
            try:
                day = datetime.strptime(text[5:], "%Y%m%d").date()
            except ValueError:
                return None
            return day if day in days else None
        if text.isdigit() and 1 <= int(text) <= len(days):
            return days[int(text) - 1]
        return None

    def _match_time(self, session, text) -> Optional[datetime]:
        if "day" not in session.data.get("book", {}):
            return None
        if text.startswith("BTIME_"):
            wanted = text[6:]
        else:
            m = re.fullmatch(r"\s*(\d{1,2})(?:[:.](\d{2}))?\s*(?:цаг(?:т)?|시)?\s*", text.lower())
            if not m:
                return None
            wanted = f"{int(m.group(1)):02d}{m.group(2) or '00'}"
        return next((s for s in self._slots_for(session) if f"{s:%H%M}" == wanted), None)
