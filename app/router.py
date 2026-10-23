"""Front door of the chatbot. Every conversation opens with Ajilt-AI's AI sales
agent (app/agent.py): it greets, asks about the visitor's business and leads the
talk towards a package, a price and a meeting. Nobody has to pick a button first.

  🎬 Демо (MODE_DEMO)  -> the demo businesses, free chat + guided tour; offered by
                          the agent when it fits, and as a chip on the greeting
  HOME / "эхлэх"        -> a fresh greeting from the agent

The demo tour's closing buttons (LEAD_CALL / LEAD_MEET) hand back to the agent.
"""
import time
from typing import List

from .config import settings
from .demo import DEFAULT_LANG, NO_LANG_DETECT_STATES, PAYLOAD_RE, detect_lang
from .models import OutMsg, Session

HOME_WORDS = {"start", "restart", "home", "get started", "эхлэх", "эхлэл", "ehleh", "ehlel"}
# A hello as the very first message gets the agent's greeting, not a model call.
GREETINGS = {"hi", "hello", "hey", "сайн уу", "сайн байна уу", "сайн", "сайнуу",
             "sain uu", "sainuu", "sain baina uu", "sain bn uu", "sain bna uu", "sn uu"}
HOME_PAYLOADS = {"GET_STARTED", "HOME", "MODE_SALES"}
# Router-owned keys that must survive the engines resetting session.data.
KEEP_KEYS = ("_mode", "lang", "lang_locked")


class AppRouter:
    def __init__(self, demo, sales, store):
        self.demo = demo
        self.sales = sales      # agent.SalesAgent
        self.store = store

    def handle(self, session: Session, user_input: str) -> List[OutMsg]:
        text = (user_input or "").strip()
        idle = time.time() - session.updated_at if session.updated_at else 0
        if settings.SESSION_FRESH_HOURS and idle > settings.SESSION_FRESH_HOURS * 3600:
            # Back after a long gap: a clean start, as if they'd never written (language kept).
            session.data = {k: session.data[k] for k in ("lang", "lang_locked") if k in session.data}
            session.state = "START"
        keep = {k: session.data[k] for k in KEEP_KEYS if k in session.data}
        out = self._route(session, text, keep)
        # Engines may replace session.data; put the router's keys back.
        session.data["_mode"] = keep.get("_mode", "sales")
        for key in ("lang", "lang_locked"):
            if key in keep:
                session.data.setdefault(key, keep[key])
        self.store.save_session(session)
        return out

    def _lang(self, session: Session, text: str, keep: dict) -> str:
        if not keep.get("lang_locked"):
            skip = (not text or PAYLOAD_RE.match(text) or session.state in NO_LANG_DETECT_STATES
                    or text.lower() in HOME_WORDS)   # Messenger's "Get Started" isn't English
            detected = None if skip else detect_lang(text)
            if detected:
                keep["lang"] = detected
        if not keep.get("lang"):
            keep["lang"] = DEFAULT_LANG
        session.data["lang"] = keep["lang"]
        return keep["lang"]

    def _greet(self, session: Session, lang: str, keep: dict) -> List[OutMsg]:
        keep["_mode"] = "sales"
        return self.sales.greet(session, lang)

    def _route(self, session: Session, text: str, keep: dict) -> List[OutMsg]:
        mode = keep.get("_mode")

        if text in ("LANG_MN", "LANG_EN"):
            keep.update(lang=text[-2:].lower(), lang_locked=True)
            return self._greet(session, keep["lang"], keep)

        lang = self._lang(session, text, keep)

        if text == "MODE_DEMO":
            keep["_mode"] = "demo"
            session.state = "START"
            session.data = {"lang": lang, "lang_locked": keep.get("lang_locked", False)}
            return self.demo.handle(session, "")

        if text in ("LEAD_CALL", "LEAD_MEET"):
            keep["_mode"] = "sales"
            return self.sales.start_closing(session, lang, session.data.get("biz", ""), text)

        if text in HOME_PAYLOADS or text.lower() in HOME_WORDS:
            return self._greet(session, lang, keep)

        if mode == "demo":
            return self.demo.handle(session, text)

        if mode not in ("sales",):   # first contact (or a session from the old menu)
            if not text or text.lower().strip(" .!?,") in GREETINGS or PAYLOAD_RE.match(text):
                return self._greet(session, lang, keep)
            # A first message: on Messenger it's usually the answer to Meta's instant reply,
            # which is our greeting, so the agent starts from that greeting too.
            keep["_mode"] = "sales"
            self.sales.greet(session, lang)
        return self.sales.handle(session, text)
