"""Front door of the chatbot: on first contact (or Messenger's Get Started button,
or "эхлэх"/"start") the visitor picks what they came for:

  🤖 Ajilt-AI  -> Ajilt-AI's own sales conversation (price estimate, callback, meeting)
  🎬 Demo      -> the demo businesses, free chat + guided tour

The demo tour's closing buttons (LEAD_CALL / LEAD_MEET) hand over to the sales side.
"""
from typing import List

from .demo import DEFAULT_LANG, NO_LANG_DETECT_STATES, PAYLOAD_RE, detect_lang
from .models import OutMsg, QuickReply, Session

HOME_WORDS = {"start", "restart", "home", "get started", "эхлэх", "эхлэл", "ehleh", "ehlel"}
# Saying hello while the choice is on screen isn't a wrong answer, so it gets
# the greeting again rather than "please choose one of the buttons below".
GREETINGS = {"hi", "hello", "hey", "сайн уу", "сайн байна уу", "сайн", "сайнуу",
             "sain uu", "sainuu", "sain baina uu", "sain bn uu", "sain bna uu", "sn uu"}
HOME_PAYLOADS = {"GET_STARTED", "HOME"}
# Router-owned keys that must survive the engines resetting session.data.
KEEP_KEYS = ("_mode", "lang", "lang_locked")

TEXT = {
    "mn": {
        "choose": "Сайн байна уу! 👋 Ажилт-AI бол танай Messenger, Instagram-д 24/7 хариулж, "
                  "цаг захиалга авдаг чатбот.\n\nЧатботыг юунд ашиглах вэ?\n"
                  "🤖 Ажилт-AI — үнийн санал авах, манай багтай холбогдох\n"
                  "🎬 Демо — жишээ бизнесүүд дээр чатботыг туршиж, тайлбартай аялал хийх",
        "sales_button": "🤖 Ажилт-AI",
        "demo_button": "🎬 Демо үзэх",
        "lang_button": "🌐 English",
        "pick": "Доорх товчнуудаас сонгоно уу.",
    },
    "en": {
        "choose": "Hi! 👋 Ajilt-AI is a chatbot that answers your Messenger and Instagram 24/7 "
                  "and takes bookings.\n\nWhat would you like to do?\n"
                  "🤖 Ajilt-AI — get a price and talk to our team\n"
                  "🎬 Demo — try the chatbot on example businesses, with a guided tour",
        "sales_button": "🤖 Ajilt-AI",
        "demo_button": "🎬 Try the demo",
        "lang_button": "🌐 Монгол",
        "pick": "Please choose one of the buttons below.",
    },
}


class AppRouter:
    def __init__(self, demo, sales, store):
        self.demo = demo
        self.sales = sales
        self.store = store

    def handle(self, session: Session, user_input: str) -> List[OutMsg]:
        text = (user_input or "").strip()
        keep = {k: session.data[k] for k in KEEP_KEYS if k in session.data}
        out = self._route(session, text, keep)
        # Engines may replace session.data; put the router's keys back.
        session.data["_mode"] = keep.get("_mode", "choose")
        for key in ("lang", "lang_locked"):
            if key in keep:
                session.data.setdefault(key, keep[key])
        self.store.save_session(session)
        return out

    def _lang(self, session: Session, text: str, keep: dict) -> str:
        if not keep.get("lang_locked"):
            skip = not text or PAYLOAD_RE.match(text) or session.state in NO_LANG_DETECT_STATES
            detected = None if skip else detect_lang(text)
            if detected:
                keep["lang"] = detected
        if not keep.get("lang"):
            keep["lang"] = DEFAULT_LANG
        session.data["lang"] = keep["lang"]
        return keep["lang"]

    def _choice(self, session: Session, lang: str, keep: dict, prefix: str = "") -> List[OutMsg]:
        t = TEXT[lang]
        keep["_mode"] = "choose"
        session.state = "CHOOSE_MODE"
        buttons = [QuickReply(t["sales_button"], "MODE_SALES"), QuickReply(t["demo_button"], "MODE_DEMO"),
                   QuickReply(t["lang_button"], "LANG_EN" if lang == "mn" else "LANG_MN")]
        return ([OutMsg(prefix)] if prefix else []) + [OutMsg(t["choose"], buttons)]

    def _route(self, session: Session, text: str, keep: dict) -> List[OutMsg]:
        mode = keep.get("_mode")

        if mode in (None, "choose") and text in ("LANG_MN", "LANG_EN"):
            keep.update(lang=text[-2:].lower(), lang_locked=True)
            session.data.update(lang=keep["lang"], lang_locked=True)
            return self._choice(session, keep["lang"], keep)

        lang = self._lang(session, text, keep)

        if text == "MODE_DEMO":
            keep["_mode"] = "demo"
            session.state = "START"
            session.data = {"lang": lang, "lang_locked": keep.get("lang_locked", False)}
            return self.demo.handle(session, "")

        if text == "MODE_SALES":
            keep["_mode"] = "sales"
            session.state = "START"
            session.data = {"lang": lang}
            return self.sales.handle(session, "")

        if text in ("LEAD_CALL", "LEAD_MEET"):
            keep["_mode"] = "sales"
            return self.sales.start_closing(session, lang, session.data.get("biz", ""), text)

        if text in HOME_PAYLOADS or text.lower() in HOME_WORDS or mode is None:
            return self._choice(session, lang, keep)

        if mode == "choose":
            greeting = text.lower().strip(" .!?,") in GREETINGS
            return self._choice(session, lang, keep,
                                prefix="" if greeting else TEXT[lang]["pick"])

        if mode == "demo":
            return self.demo.handle(session, text)
        return self.sales.handle(session, text)
