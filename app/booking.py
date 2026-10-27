"""Demo appointment booking: service -> branch -> staff -> day -> time -> name
-> phone -> confirm -> Google Calendar event.

Businesses with a `staff:` list get one employee per booking. With
`choose_staff: true` the customer picks one (or "anyone"); otherwise the free
employee with the fewest bookings that day is assigned. The staff id goes into
the event's private properties, which is what the dashboard reads.

Button-driven so it works even when the LLM is down. Free slots come from the
business hours in seeds.yaml minus events already in the business's calendar.
Without a calendar (no key / not set up) bookings are still saved to SQLite.
"""
import re
from datetime import date, datetime, time, timedelta
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

from . import crm, notify
from .config import settings
from .demo_data import load_seeds
from .models import OutMsg, QuickReply, Session

WEEKDAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAY_NAMES = {
    "mn": ["Даваа", "Мягмар", "Лхагва", "Пүрэв", "Баасан", "Бямба", "Ням"],
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
}
MONTHS_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

SLOT_STEP_MINUTES = 30
LEAD_MINUTES = 60
SEARCH_DAYS = 14
MAX_DAY_BUTTONS = 7
MAX_TIME_BUTTONS = 12
# Google Calendar event colorIds, in the same order as the dashboard's staff colors.
STAFF_EVENT_COLORS = ["7", "6", "2", "5", "4", "10", "3", "11"]

BUTTON_PAYLOAD_RE = re.compile(r"^(BOOK|BOK|BCANCEL|MENU|[A-Z]+_\w+)$")
CANCEL_WORDS = {"болих", "болъё", "цуцлах", "cancel", "stop", "bolih", "tsutslah"}

# Only used when the LLM is unavailable; otherwise the LLM flags booking intent.
BOOK_INTENT = ["цаг захиал", "захиалмаар", "захиалга хий", "цаг авмаар", "уулзалтын цаг",
               "tsag zahial", "zahialmaar", "tsag avmaar", "tsag awmaar",
               "book an appointment", "make an appointment", "i want to book",
               "i'd like to book", "schedule an appointment", "book a visit", "book a tour"]

T = {
    "mn": {
        "book_button": "📅 Цаг захиалах",
        "cancel_button": "✖ Болих",
        "confirm_button": "✅ Баталгаажуулах",
        "ask_service": "Ямар үйлчилгээнд цаг захиалах вэ?",
        "ask_branch": "Аль салбарт очих вэ?",
        "ask_staff": "Аль мэргэжилтэнд цаг авах вэ?",
        "any_staff": "Хэн ч болно",
        "staff_line": "🧑 {staff}\n",
        "ask_day": "Аль өдөр тохиромжтой вэ?",
        "ask_time": "{day} — сул цагуудаас сонгоно уу:",
        "ask_name": "Захиалгыг хэний нэр дээр бүртгэх вэ? Нэрээ бичнэ үү.",
        "ask_phone": "Холбогдох утасны дугаараа бичнэ үү.",
        "bad_phone": "Утасны дугаар буруу байна. 8 оронтой дугаараа бичнэ үү, жишээ нь 99112233.",
        "bad_name": "Нэрээ бичнэ үү.",
        "no_days": "Уучлаарай, ойрын 2 долоо хоногт сул цаг алга. {contact}.",
        "day_full": "Уучлаарай, тэр өдрийн цаг дүүрчихлээ. Өөр өдөр сонгоно уу.",
        "slot_taken": "Уучлаарай, тэр цагийг саяхан өөр хүн авчихлаа. Өөр цаг сонгоно уу.",
        "pick_button": "Доорх товчнуудаас сонгоно уу.",
        "summary": "Захиалгаа шалгана уу:\n\n📝 {service}\n{branch_line}{staff_line}📅 {when}\n👤 {name}\n📞 {phone}",
        "branch_line": "📍 {branch}\n",
        "item_line": "🏠 {item}\n📍 {address}\n",
        "done": "✅ Цаг захиалга баталгаажлаа!\n\n{service}\n{staff_line}📅 {when}\n📍 {address}\n\n"
                "Цагаа өөрчлөх, цуцлах бол {contact}.",
        "done_no_calendar": "✅ Захиалгыг хүлээн авлаа!\n\n{service}\n📅 {when}\n📍 {address}\n\n"
                            "Манай ажилтан {phone} дугаарт холбогдож баталгаажуулна.",
        "cancelled": "Захиалгыг цуцаллаа. Өөр асуух зүйл байвал бичээрэй.",
        "today": "Өнөөдөр",
        "tomorrow": "Маргааш",
    },
    "en": {
        "book_button": "📅 Book",
        "cancel_button": "✖ Cancel",
        "confirm_button": "✅ Confirm",
        "ask_service": "What would you like to book?",
        "ask_branch": "Which branch would you like to visit?",
        "ask_staff": "Who would you like to book with?",
        "any_staff": "Anyone available",
        "staff_line": "🧑 {staff}\n",
        "ask_day": "Which day works for you?",
        "ask_time": "{day} — pick a free time:",
        "ask_name": "What name should the booking be under?",
        "ask_phone": "What's your phone number?",
        "bad_phone": "That doesn't look like a phone number. Please send 8 digits, e.g. 99112233.",
        "bad_name": "Please type your name.",
        "no_days": "Sorry, there are no free slots in the next 2 weeks. Please {contact}.",
        "day_full": "Sorry, that day just filled up. Please pick another day.",
        "slot_taken": "Sorry, someone just took that time. Please pick another one.",
        "pick_button": "Please choose one of the buttons below.",
        "summary": "Please check your booking:\n\n📝 {service}\n{branch_line}{staff_line}📅 {when}\n👤 {name}\n📞 {phone}",
        "branch_line": "📍 {branch}\n",
        "item_line": "🏠 {item}\n📍 {address}\n",
        "done": "✅ You're booked!\n\n{service}\n{staff_line}📅 {when}\n📍 {address}\n\n"
                "To change or cancel, {contact}.",
        "done_no_calendar": "✅ Booking request received!\n\n{service}\n📅 {when}\n📍 {address}\n\n"
                            "Our staff will call {phone} to confirm.",
        "cancelled": "Booking cancelled. Let me know if you have any other questions.",
        "today": "Today",
        "tomorrow": "Tomorrow",
    },
}


def local_tz() -> ZoneInfo:
    return ZoneInfo(settings.BOOKING_TIMEZONE)


def opening_hours(hours: dict, day: date) -> Optional[Tuple[datetime, datetime]]:
    spec = hours.get(WEEKDAY_KEYS[day.weekday()])
    if not spec:
        return None
    start_s, end_s = spec.split("-")
    tz = local_tz()
    return (datetime.combine(day, time.fromisoformat(start_s.strip()), tz),
            datetime.combine(day, time.fromisoformat(end_s.strip()), tz))


def free_slots(hours: dict, day: date, minutes: int, busy, now: datetime) -> List[datetime]:
    window = opening_hours(hours, day)
    if not window:
        return []
    open_at, close_at = window
    earliest = now + timedelta(minutes=LEAD_MINUTES)
    slots, t = [], open_at
    length = timedelta(minutes=minutes)
    while t + length <= close_at:
        if t >= earliest and not any(t < b[1] and t + length > b[0] for b in busy):
            slots.append(t)
        t += timedelta(minutes=SLOT_STEP_MINUTES)
    return slots


def staff_busy(busy, staff_id: str) -> list:
    """Intervals that block one employee: their own bookings plus untagged events."""
    return [b for b in busy if b[2] in ("", staff_id)]


def free_staff(busy, staff_ids: List[str], start: datetime, end: datetime) -> List[str]:
    return [sid for sid in staff_ids
            if not any(start < b[1] and end > b[0] for b in staff_busy(busy, sid))]


def pick_evenly(items: list, n: int) -> list:
    if len(items) <= n:
        return items
    step = (len(items) - 1) / (n - 1)
    return [items[round(i * step)] for i in range(n)]


def normalize_phone(text: str) -> Optional[str]:
    digits = re.sub(r"\D", "", text)
    if len(digits) == 11 and digits.startswith("976"):
        digits = digits[3:]
    return digits if len(digits) == 8 else None


def wants_booking(text: str) -> bool:
    low = text.lower()
    return any(k in low for k in BOOK_INTENT)


def day_label(day: date, lang: str, today: date) -> str:
    if day == today:
        return T[lang]["today"]
    if day == today + timedelta(days=1):
        return T[lang]["tomorrow"]
    name = WEEKDAY_NAMES[lang][day.weekday()]
    return f"{day.month}/{day.day} {name}" if lang == "mn" else f"{name} {day.month}/{day.day}"


def when_label(start: datetime, lang: str) -> str:
    name = WEEKDAY_NAMES[lang][start.weekday()]
    if lang == "mn":
        return f"{start.month}-р сарын {start.day}, {name}, {start:%H:%M}"
    return f"{name}, {MONTHS_EN[start.month - 1]} {start.day}, {start:%H:%M}"


def staff_color(cfg: dict, staff: Optional[dict]) -> str:
    if not staff:
        return ""
    return STAFF_EVENT_COLORS[cfg["staff"].index(staff) % len(STAFF_EVENT_COLORS)]


def _qr(pairs) -> List[QuickReply]:
    return [QuickReply(title=t, payload=p) for t, p in pairs]


def contact_text(lang: str, phone: str) -> str:
    """How to reach the business: by phone, or here in the chat when it has no number."""
    if phone:
        return f"{phone} утсаар холбогдоно уу" if lang == "mn" else f"call {phone}"
    return "энд бичнэ үү" if lang == "mn" else "message us here"


def ajilt_ai_business() -> dict:
    """Ajilt-AI's own sales-meeting 'business', shaped like a demo business row."""
    seed = load_seeds()["ajilt_ai"]
    return {"id": "ajilt_ai", "name_mn": seed["name"]["mn"], "name_en": seed["name"]["en"],
            "profile": {"phone": seed.get("phone", "")}}


class BookingFlow:
    def __init__(self, store, calendar=None):
        self.store = store
        self.calendar = calendar
        seeds = load_seeds()
        self.configs = {s["id"]: s["booking"] for s in seeds["businesses"] if "booking" in s}
        self.titles = {s["id"]: f"{s['name']['mn']} · Ajilt-AI демо" for s in seeds["businesses"]}
        if "ajilt_ai" in seeds:
            self.configs["ajilt_ai"] = seeds["ajilt_ai"]["booking"]
            self.titles["ajilt_ai"] = "Ажилт-AI · борлуулалтын уулзалт"

    def is_bookable(self, business_id: str) -> bool:
        return business_id in self.configs

    # ---- entry ----
    def start(self, session: Session, lang: str, biz: dict, item: Optional[dict] = None,
              service: str = "") -> Tuple[List[OutMsg], bool]:
        """item: the thing being booked when it isn't the business itself, e.g. the property
        for a viewing ({id, title, short, address}); its address is where the visit happens.
        service: preselected service id."""
        cfg = self.configs[biz["id"]]
        book = session.data["book"] = {"item": item} if item else {}
        ids = [s["id"] for s in cfg["services"]]
        if item and cfg.get("item_service") in ids:
            service = cfg["item_service"]
        if service in ids or len(ids) == 1:
            book["service"] = service if service in ids else ids[0]
            return self._after_service(session, lang, biz)
        return self._ask_service(session, lang, biz), False

    def handle(self, session: Session, lang: str, biz: dict, text: str) -> Tuple[List[OutMsg], bool]:
        """Returns (messages, done). done=True hands the conversation back to chat."""
        t = T[lang]
        if text == "BCANCEL" or text.lower() in CANCEL_WORDS:
            session.data.pop("book", None)
            return [OutMsg(t["cancelled"])], True

        cfg = self.configs[biz["id"]]
        book = session.data.setdefault("book", {})
        state = session.state

        if state == "BOOK_SERVICE":
            service = self._match_service(cfg, text)
            if not service:
                return self._ask_service(session, lang, biz, t["pick_button"]), False
            book["service"] = service
            return self._after_service(session, lang, biz)

        if state == "BOOK_BRANCH":
            branch = self._match_option(cfg["branches"], text, "BBR_")
            if not branch:
                return self._ask_branch(session, lang, biz, t["pick_button"]), False
            book["branch"] = branch
            return self._after_branch(session, lang, biz)

        if state == "BOOK_STAFF":
            if text == "BSTF_any":
                staff = "any"
            else:
                staff = self._match_option(self._eligible(cfg, book), text, "BSTF_")
            if not staff:
                return self._ask_staff(session, lang, biz, t["pick_button"]), False
            book["staff"] = staff
            return self._ask_day(session, lang, biz)

        if state == "BOOK_DAY":
            day = self._match_day(session, text)
            if not day:
                return self._ask_day(session, lang, biz, t["pick_button"])
            book["day"] = day.isoformat()
            return self._ask_time(session, lang, biz)

        if state == "BOOK_TIME":
            start = self._match_time(session, biz, text)
            if not start:
                msgs, done = self._ask_time(session, lang, biz)
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
            return [self._summary(lang, biz, book)], False

        if state == "BOOK_CONFIRM":
            if text != "BOK":
                return [OutMsg(t["pick_button"]), self._summary(lang, biz, book)], False
            return self._book(session, lang, biz)

        session.data.pop("book", None)
        return [], True

    # ---- steps ----
    def _ask_service(self, session, lang, biz, prefix: str = "") -> List[OutMsg]:
        t = T[lang]
        session.state = "BOOK_SERVICE"
        services = self.configs[biz["id"]]["services"][:MAX_TIME_BUTTONS]
        buttons = [(s["name"][lang], f"BSVC_{s['id']}") for s in services]
        buttons.append((t["cancel_button"], "BCANCEL"))
        return [OutMsg((prefix + "\n\n" if prefix else "") + t["ask_service"], _qr(buttons))]

    def _after_service(self, session, lang, biz) -> Tuple[List[OutMsg], bool]:
        if self.configs[biz["id"]].get("branches"):
            return self._ask_branch(session, lang, biz), False
        return self._after_branch(session, lang, biz)

    def _after_branch(self, session, lang, biz) -> Tuple[List[OutMsg], bool]:
        cfg, book = self.configs[biz["id"]], session.data["book"]
        if cfg.get("choose_staff") and len(self._eligible(cfg, book)) > 1:
            return self._ask_staff(session, lang, biz), False
        book["staff"] = "any"
        return self._ask_day(session, lang, biz)

    def _ask_staff(self, session, lang, biz, prefix: str = "") -> List[OutMsg]:
        t = T[lang]
        session.state = "BOOK_STAFF"
        options = self._eligible(self.configs[biz["id"]], session.data["book"])
        buttons = [(t["any_staff"], "BSTF_any")]
        buttons += [(p["name"][lang], f"BSTF_{p['id']}") for p in options[:MAX_TIME_BUTTONS - 1]]
        buttons.append((t["cancel_button"], "BCANCEL"))
        body = t["ask_staff"] + "\n\n" + "\n".join(f"🧑 {p['name'][lang]} — {p['role'][lang]}"
                                                     for p in options)
        return [OutMsg((prefix + "\n\n" if prefix else "") + body, _qr(buttons))]

    def _ask_branch(self, session, lang, biz, prefix: str = "") -> List[OutMsg]:
        t = T[lang]
        session.state = "BOOK_BRANCH"
        branches = self.configs[biz["id"]]["branches"]
        buttons = [(b["name"][lang], f"BBR_{b['id']}") for b in branches]
        buttons.append((t["cancel_button"], "BCANCEL"))
        body = t["ask_branch"] + "\n\n" + "\n".join(f"📍 {b['name'][lang]}: {b['address'][lang]}"
                                                     for b in branches)
        return [OutMsg((prefix + "\n\n" if prefix else "") + body, _qr(buttons))]

    def _ask_day(self, session, lang, biz, prefix: str = "") -> Tuple[List[OutMsg], bool]:
        t = T[lang]
        cfg, book = self.configs[biz["id"]], session.data["book"]
        now = datetime.now(local_tz())
        busy = self._busy(biz["id"], book.get("branch"), now, now + timedelta(days=SEARCH_DAYS + 1))
        days = []
        for i in range(SEARCH_DAYS):
            day = now.date() + timedelta(days=i)
            if self._free(cfg, book, day, busy, now):
                days.append(day)
            if len(days) == MAX_DAY_BUTTONS:
                break
        if not days:
            session.data.pop("book", None)
            return [OutMsg(t["no_days"].format(contact=contact_text(lang, biz["profile"]["phone"])))], True
        session.state = "BOOK_DAY"
        book["days"] = [d.isoformat() for d in days]
        buttons = [(day_label(d, lang, now.date()), f"BDAY_{d:%Y%m%d}") for d in days]
        buttons.append((t["cancel_button"], "BCANCEL"))
        return [OutMsg((prefix + "\n\n" if prefix else "") + t["ask_day"], _qr(buttons))], False

    def _ask_time(self, session, lang, biz) -> Tuple[List[OutMsg], bool]:
        t = T[lang]
        slots = self._slots_for(session, biz)
        if not slots:
            return self._ask_day(session, lang, biz, t["day_full"])
        session.state = "BOOK_TIME"
        day = date.fromisoformat(session.data["book"]["day"])
        on_the_hour = [s for s in slots if s.minute == 0]
        shown = pick_evenly(on_the_hour if len(slots) > MAX_TIME_BUTTONS and on_the_hour else slots,
                            MAX_TIME_BUTTONS)
        buttons = [(f"{s:%H:%M}", f"BTIME_{s:%H%M}") for s in shown]
        buttons.append((t["cancel_button"], "BCANCEL"))
        label = day_label(day, lang, datetime.now(local_tz()).date())
        return [OutMsg(t["ask_time"].format(day=label), _qr(buttons))], False

    def _summary(self, lang, biz, book) -> OutMsg:
        t = T[lang]
        cfg = self.configs[biz["id"]]
        branch = self._branch(cfg, book.get("branch"))
        staff = self._staff(cfg, book.get("staff"))
        item = book.get("item")
        text = t["summary"].format(
            service=self._service(cfg, book["service"])["name"][lang],
            branch_line=(t["item_line"].format(item=item["title"][lang], address=item["address"][lang])
                         if item else t["branch_line"].format(branch=branch["name"][lang]) if branch else ""),
            staff_line=t["staff_line"].format(staff=staff["name"][lang]) if staff else "",
            when=when_label(datetime.fromisoformat(book["start"]), lang),
            name=book["name"], phone=book["phone"],
        )
        return OutMsg(text, _qr([(t["confirm_button"], "BOK"), (t["cancel_button"], "BCANCEL")]))

    def _book(self, session, lang, biz) -> Tuple[List[OutMsg], bool]:
        t = T[lang]
        cfg, book = self.configs[biz["id"]], session.data["book"]
        service = self._service(cfg, book["service"])
        branch = self._branch(cfg, book.get("branch"))
        start = datetime.fromisoformat(book["start"])
        end = start + timedelta(minutes=service["minutes"])
        address = (branch or cfg)["address"][lang] if (branch or cfg.get("address")) else ""
        item = book.get("item")
        if item:                       # the visit happens at the property, not the office
            address = item["address"][lang]

        day_start = datetime.combine(start.date(), time.min, local_tz())
        busy = self._busy(biz["id"], book.get("branch"), day_start, day_start + timedelta(days=1))
        staff = None
        if cfg.get("staff"):
            free = free_staff(busy, self._wanted_staff(cfg, book), start, end)
            if free:
                # least busy that day, so "anyone" spreads work evenly
                staff = self._staff(cfg, min(free, key=lambda sid: sum(b[2] == sid for b in busy)))
            taken = not free
        else:
            taken = any(start < b[1] and end > b[0] for b in busy)
        if taken:
            msgs, done = self._ask_time(session, lang, biz)
            return [OutMsg(t["slot_taken"])] + msgs, done

        calendar_id = self._calendar_id(biz["id"])
        event_id, status = None, "no_calendar"
        service_mn = service["name"]["mn"] + (f": {item['short']['mn']}" if item else "")
        if self.calendar and calendar_id:
            try:
                event = self.calendar.create_event(
                    calendar_id,
                    summary=f"{service_mn} — {book['name']}"
                            + (f" ({staff['name']['mn']})" if staff else ""),
                    description=(f"Утас: {book['phone']}\nҮйлчилгээ: {service['name']['mn']}\n"
                                 + (f"Үл хөдлөх: {item['title']['mn']} ({item['id']})\n"
                                    f"Хаяг: {item['address']['mn']}\n" if item else "")
                                 + (f"Салбар: {branch['name']['mn']}\n" if branch else "")
                                 + (f"Ажилтан: {staff['name']['mn']}\n" if staff else "")
                                 + f"Хэл: {lang}\nMessenger-ээр захиалсан (Ajilt-AI демо)"),
                    start=start, end=end,
                    location=(item["address"]["mn"] if item
                              else (branch or cfg).get("address", {}).get("mn", "")),
                    private={"branch": book.get("branch") or "", "source": "ajilt-demo",
                             "sender": session.sender_id, "service": service["id"],
                             "staff": staff["id"] if staff else "", "name": book["name"],
                             "phone": book["phone"], "item": item["id"] if item else ""},
                    color_id=staff_color(cfg, staff),
                )
                event_id, status = event.get("id"), "booked"
            except Exception as e:
                print(f"[booking] calendar insert failed for {biz['id']}: {e}")
                status = "calendar_failed"

        booking_id = self.store.save_booking({
            "business_id": biz["id"], "sender_id": session.sender_id, "channel": session.channel,
            "service_id": service["id"], "branch_id": book.get("branch"),
            "staff_id": staff["id"] if staff else None,
            "start_at": start.isoformat(), "end_at": end.isoformat(),
            "name": book["name"], "phone": book["phone"], "event_id": event_id, "status": status,
        })
        crm.enqueue(self.store, "booking", booking_id, {
            "business": biz.get("name_mn") or biz["id"],
            "service": service_mn,
            "where": item["address"]["mn"] if item else "",
            "branch": branch["name"]["mn"] if branch else "",
            "staff": staff["name"]["mn"] if staff else "",
            "lang": lang,
        })
        if biz["id"] == "ajilt_ai":    # a real prospect; demo businesses' bookings are play
            notify.meeting(channel=session.channel, start=start.isoformat(), name=book["name"],
                           phone=book["phone"], what=service_mn, calendar_status=status)
        session.data.pop("book", None)
        # Read (and removed) by the guided tour to comment on what just happened.
        session.data["last_booking"] = {
            "status": status, "service": service["name"][lang], "when": when_label(start, lang),
            "staff": staff["name"][lang] if staff else "", "name": book["name"],
            "phone": book["phone"], "start": start.isoformat(),
            "item": item["title"][lang] if item else "",
        }
        template = t["done"] if status == "booked" else t["done_no_calendar"]
        return [OutMsg(template.format(
            service=service["name"][lang] + (f": {item['title'][lang]}" if item else ""),
            when=when_label(start, lang), address=address,
            staff_line=t["staff_line"].format(staff=staff["name"][lang]) if staff else "",
            contact=contact_text(lang, biz["profile"]["phone"]), phone=book["phone"],
        ))], True

    # ---- helpers ----
    def _busy(self, business_id, branch, start, end):
        # Ajilt-AI's own meetings also can't land on anything staff put in bas.mn.
        busy = crm.busy(self.store, start, end) if business_id == "ajilt_ai" else []
        calendar_id = self._calendar_id(business_id)
        if not (self.calendar and calendar_id):
            return busy
        try:
            return busy + self.calendar.busy(calendar_id, start, end, branch=branch)
        except Exception as e:
            print(f"[booking] calendar read failed for {business_id}: {e}")
            return busy

    def _calendar_id(self, business_id: str) -> Optional[str]:
        """The business's Google Calendar; a business added later gets one made on first use."""
        calendar_id = self.store.get_calendar_id(business_id)
        if calendar_id or not self.calendar:
            return calendar_id
        from .gcal import ensure_calendar
        try:
            return ensure_calendar(self.store, self.calendar, business_id,
                                   self.titles.get(business_id, business_id))
        except Exception as e:
            print(f"[booking] could not create a calendar for {business_id}: {e}")
            return None

    def _slots_for(self, session, biz) -> List[datetime]:
        cfg, book = self.configs[biz["id"]], session.data["book"]
        day = date.fromisoformat(book["day"])
        now = datetime.now(local_tz())
        tz = local_tz()
        day_start = datetime.combine(day, time.min, tz)
        busy = self._busy(biz["id"], book.get("branch"), day_start, day_start + timedelta(days=1))
        return self._free(cfg, book, day, busy, now)

    def _free(self, cfg, book, day, busy, now) -> List[datetime]:
        """Slots where the chosen employee (or any eligible one) is free."""
        minutes = self._service(cfg, book["service"])["minutes"]
        if not cfg.get("staff"):
            return free_slots(cfg["hours"], day, minutes, busy, now)
        slots = set()
        for sid in self._wanted_staff(cfg, book):
            slots.update(free_slots(cfg["hours"], day, minutes, staff_busy(busy, sid), now))
        return sorted(slots)

    def _wanted_staff(self, cfg, book) -> List[str]:
        if book.get("staff", "any") != "any":
            return [book["staff"]]
        return [p["id"] for p in self._eligible(cfg, book)]

    @staticmethod
    def _eligible(cfg, book) -> list:
        return [p for p in cfg.get("staff", [])
                if book.get("service") in p.get("services", [book.get("service")])
                and (not book.get("branch") or p.get("branch", book["branch"]) == book["branch"])]

    @staticmethod
    def _staff(cfg, staff_id):
        return next((p for p in cfg.get("staff", []) if p["id"] == staff_id), None)

    @staticmethod
    def _service(cfg, service_id):
        return next(s for s in cfg["services"] if s["id"] == service_id)

    @staticmethod
    def _branch(cfg, branch_id):
        return next((b for b in cfg.get("branches", []) if b["id"] == branch_id), None)

    def _match_service(self, cfg, text) -> Optional[str]:
        return self._match_option(cfg["services"], text, "BSVC_")

    @staticmethod
    def _match_option(options, text, prefix) -> Optional[str]:
        if text.startswith(prefix):
            wanted = text[len(prefix):]
            return wanted if any(o["id"] == wanted for o in options) else None
        if text.isdigit() and 1 <= int(text) <= len(options):
            return options[int(text) - 1]["id"]
        low = text.lower().strip()
        if len(low) < 3:
            return None
        for o in options:
            if any(name.lower() in low or low in name.lower() for name in o["name"].values()):
                return o["id"]
        return None

    def _match_day(self, session, text) -> Optional[date]:
        days = [date.fromisoformat(d) for d in session.data["book"].get("days", [])]
        if text.startswith("BDAY_"):
            try:
                day = datetime.strptime(text[5:], "%Y%m%d").date()
            except ValueError:
                return None
            return day if day in days else None
        if text.isdigit() and 1 <= int(text) <= len(days):
            return days[int(text) - 1]
        return None

    def _match_time(self, session, biz, text) -> Optional[datetime]:
        slots = self._slots_for(session, biz)
        if text.startswith("BTIME_"):
            wanted = text[6:]
        else:
            m = re.fullmatch(r"\s*(\d{1,2})(?:[:.](\d{2}))?\s*(?:цаг(?:т)?)?\s*", text.lower())
            if not m:
                return None
            wanted = f"{int(m.group(1)):02d}{m.group(2) or '00'}"
        return next((s for s in slots if f"{s:%H%M}" == wanted), None)
