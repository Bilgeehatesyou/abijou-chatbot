"""Guided tour: a "💡 Ajilt-AI" commentator that walks a prospect through a demo
business step by step (FAQ → language → unknown question → booking/request →
owner's view → extras → close). Texts live in data/demo/tours.yaml; this module
only decides which one to show and fills in live numbers.

The tour never blocks free chat: the visitor can type anything at any step, and
the ▶ button picks the tour back up.
"""
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

import yaml

from .booking import T as BOOK_T, local_tz
from .dashboard import customer_key
from .models import OutMsg, QuickReply, Session

TOURS_PATH = Path("data/demo/tours.yaml")
STEPS = ["welcome", "faq", "latin", "unknown", "action", "owner", "extras", "close"]
QUESTION_STEPS = ("faq", "latin", "unknown")
MIN_BOOKINGS_FOR_STATS = 5


def _qr(pairs) -> List[QuickReply]:
    return [QuickReply(title=t, payload=p) for t, p in pairs]


class TourGuide:
    def __init__(self, store, booking, requests):
        self.store = store
        self.booking = booking
        self.requests = requests
        self.tours = yaml.safe_load(TOURS_PATH.read_text(encoding="utf-8"))

    # ---- state ----
    @staticmethod
    def active(session: Session) -> bool:
        return "tour" in session.data

    @staticmethod
    def step(session: Session) -> str:
        return session.data.get("tour", {}).get("step", "")

    def has_tour(self, business_id: str) -> bool:
        return business_id in self.tours["businesses"]

    # ---- text helpers ----
    def _ctx(self, lang: str, biz: dict) -> tuple:
        g = self.tours["guide"][lang]
        ctx = dict(self.tours["industries"][biz["industry"]][lang])
        for key, value in self.tours["businesses"].get(biz["id"], {}).items():
            if key not in QUESTION_STEPS:
                ctx[key] = value[lang] if isinstance(value, dict) else value
        ctx["name"] = biz["name_" + lang]
        ctx.setdefault("customer_gen", ctx["customer"])
        return g, ctx

    def _say(self, lang: str, text: str, buttons=None) -> OutMsg:
        return OutMsg(f"{self.tours['guide'][lang]['prefix']} {text.strip()}", _qr(buttons) if buttons else None)

    def _question(self, lang: str, biz: dict, step: str) -> str:
        q = self.tours["businesses"][biz["id"]][step]
        return q[lang] if isinstance(q, dict) else q

    def continue_button(self, lang: str) -> tuple:
        return self.tours["guide"][lang]["next_button"], "TOUR_NEXT"

    def _nav(self, lang: str, *extra) -> list:
        g = self.tours["guide"][lang]
        return list(extra) + [(g["end_button"], "TOUR_END")]

    # ---- flow ----
    def start(self, session: Session, lang: str, biz: dict) -> List[OutMsg]:
        g, ctx = self._ctx(lang, biz)
        session.data["tour"] = {"step": "welcome", "did": ""}
        return [self._say(lang, g["welcome"].format(**ctx), self._nav(lang, (g["begin_button"], "TOUR_NEXT")))]

    def end(self, session: Session, lang: str) -> List[OutMsg]:
        session.data.pop("tour", None)
        return [self._say(lang, self.tours["guide"][lang]["ended"])]

    def next(self, session: Session, lang: str, biz: dict) -> List[OutMsg]:
        current = self.step(session)
        index = STEPS.index(current) + 1 if current in STEPS else 1
        return self._show(session, lang, biz, STEPS[min(index, len(STEPS) - 1)])

    def pending_question(self, session: Session, lang: str, biz: dict) -> Optional[str]:
        """The suggested message for 📨 Send on the current step."""
        step = self.step(session)
        return self._question(lang, biz, step) if step in QUESTION_STEPS else None

    def _show(self, session: Session, lang: str, biz: dict, step: str) -> List[OutMsg]:
        g, ctx = self._ctx(lang, biz)
        tour = session.data["tour"]
        tour.update(step=step, answered=False)

        if step in QUESTION_STEPS:
            text = g[step].format(question=self._question(lang, biz, step), **ctx)
            return [self._say(lang, text, self._nav(lang, (g["send_button"], "TOUR_SEND"),
                                                    (g["skip_button"], "TOUR_NEXT")))]

        if step == "action":
            if self.booking.is_bookable(biz["id"]):
                button = (self.booking_button(lang), "BOOK")
                text = g["action_booking"].format(**ctx)
            elif self.requests.has_request(biz["id"]):
                button = self.requests.button(lang, biz["id"])
                text = g["action_request"].format(**ctx)
            else:
                return self._show(session, lang, biz, "owner")
            return [self._say(lang, text, self._nav(lang, button, (g["skip_button"], "TOUR_NEXT")))]

        if step == "owner":
            stats = self._owner_stats(lang, biz, g, ctx) or g["owner_generic"]
            return [self._say(lang, g["owner"].format(stats=stats, **ctx),
                              self._nav(lang, (g["next_button"], "TOUR_NEXT")))]

        if step == "extras":
            lines = ctx.get("extras", []) + g["common_extras"]
            return [self._say(lang, g["extras"].format(extras="\n".join(f"• {x}" for x in lines)),
                              self._nav(lang, (g["next_button"], "TOUR_NEXT")))]

        # close: the tour is done; hand over to Ajilt-AI's own sales flow via the buttons
        done_part = {"booking": g["done_booking"], "request": g["done_request"]}.get(tour.get("did"), "")
        text = g["close"].format(done_part=done_part, **ctx)
        session.data.pop("tour", None)
        return [self._say(lang, text, [(g["call_button"], "LEAD_CALL"), (g["meet_button"], "LEAD_MEET"),
                                       self.other_business_button(lang)])]

    # ---- reactions to what the visitor just did ----
    def after_answer(self, session: Session, lang: str, biz: dict, seconds: float) -> Optional[OutMsg]:
        tour = session.data.get("tour", {})
        step = tour.get("step")
        if step not in QUESTION_STEPS or tour.get("answered"):
            return None
        tour["answered"] = True
        g, ctx = self._ctx(lang, biz)
        text = g[f"{step}_after"].format(seconds=f"{seconds:.1f}".rstrip("0").rstrip("."), **ctx)
        return self._say(lang, text, self._nav(lang, (g["next_button"], "TOUR_NEXT")))

    def after_action(self, session: Session, lang: str, biz: dict) -> Optional[OutMsg]:
        """Comment on a finished booking/request flow (called when it hands back to chat)."""
        tour = session.data.get("tour", {})
        booking = session.data.pop("last_booking", None)
        request = session.data.pop("last_request", None)
        if tour.get("step") != "action":
            return None
        g, ctx = self._ctx(lang, biz)
        nav = self._nav(lang, (g["next_button"], "TOUR_NEXT"))
        if booking:
            tour["did"] = "booking"
            staff_part = g["staff_part"].format(staff=booking["staff"]) if booking["staff"] else ""
            return self._say(lang, g["booked_after"].format(
                service=booking["service"], when=booking["when"], staff_part=staff_part, **ctx), nav)
        if request:
            tour["did"] = "request"
            return self._say(lang, g["requested_after"].format(
                title=request["title"], count=len(request["answers"]), **ctx), nav)
        return self._say(lang, g["action_cancelled"], nav)

    # ---- owner's view ----
    def _owner_stats(self, lang: str, biz: dict, g: dict, ctx: dict) -> Optional[str]:
        cfg = self.booking.configs.get(biz["id"])
        if not cfg:
            return None
        now = datetime.now(local_tz()).replace(tzinfo=None)
        since = now - timedelta(days=30)
        visits: dict = {}
        recent = []
        for row in self.store.calendar_events(biz["id"]):  # sorted by start
            if row["status"] == "cancelled":
                continue
            key = customer_key(row)
            visits[key] = visits.get(key, 0) + 1
            start = datetime.fromisoformat(row["start_at"])
            if since <= start <= now:
                recent.append((row, visits[key]))
        if len(recent) < MIN_BOOKINGS_FOR_STATS:
            return None
        new = sum(1 for _, visit in recent if visit == 1)
        services = {s["id"]: s["name"][lang] for s in cfg["services"]}
        top_id = Counter(r["service_id"] for r, _ in recent if r["service_id"]).most_common(1)
        busy = Counter(datetime.fromisoformat(r["start_at"]).weekday() for r, _ in recent).most_common(1)[0][0]
        return g["owner_stats"].format(
            count=len(recent), new=new, regular=len(recent) - new,
            top_service=services.get(top_id[0][0], top_id[0][0]) if top_id else "—",
            busy_day=g["weekdays"][busy], **ctx)

    # ---- labels reused by the demo engine ----
    @staticmethod
    def booking_button(lang: str) -> str:
        return BOOK_T[lang]["book_button"]

    def other_business_button(self, lang: str) -> tuple:
        return self.tours["guide"][lang]["other_button"], "MENU"

    def start_button(self, lang: str) -> tuple:
        return self.tours["guide"][lang]["start_button"], "TOUR_START"
