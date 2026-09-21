"""Order / stay requests for businesses that don't book fixed time slots
(wholesale orders, resort and apartment stays): a couple of free-text questions
from seeds.yaml `request:`, then name + phone, a confirmation, and a saved row
that staff follow up by phone.
"""
import re
from typing import List, Tuple

from .booking import BUTTON_PAYLOAD_RE, CANCEL_WORDS, T as BOOK_T, normalize_phone
from .demo_data import load_seeds
from .models import OutMsg, QuickReply, Session

T = {
    "mn": {
        "summary": "Шалгаад баталгаажуулна уу — {title}:\n\n{answers}\n👤 {name}\n📞 {phone}",
        "done": "✅ {title} хүлээн авлаа!\n\n{answers}\n\n{next}",
        "bad_answer": "Жаахан дэлгэрэнгүй бичнэ үү.",
        "ask_quantity": "«{product}» — хэдийг захиалах вэ? (жишээ нь: 10 шуудай)",
        "cancelled": "Захиалгыг цуцаллаа. Өөр асуух зүйл байвал бичээрэй.",
    },
    "en": {
        "summary": "Please check and confirm — {title}:\n\n{answers}\n👤 {name}\n📞 {phone}",
        "done": "✅ {title} received!\n\n{answers}\n\n{next}",
        "bad_answer": "Please add a little more detail.",
        "ask_quantity": "“{product}” — how many would you like? (e.g. 10 sacks)",
        "cancelled": "Request cancelled. Let me know if you have any other questions.",
    },
}


def _qr(pairs) -> List[QuickReply]:
    return [QuickReply(title=t, payload=p) for t, p in pairs]


class RequestFlow:
    def __init__(self, store):
        self.store = store
        self.configs = {s["id"]: s["request"] for s in load_seeds()["businesses"] if "request" in s}

    def has_request(self, business_id: str) -> bool:
        return business_id in self.configs

    def button(self, lang: str, business_id: str) -> Tuple[str, str]:
        return self.configs[business_id]["button"][lang], "REQ"

    def start(self, session: Session, lang: str, biz: dict, product: str = "") -> List[OutMsg]:
        """product: when ordering from a catalog card, the first question becomes
        'how many of <product>?' instead of 'what would you like to order?'."""
        session.data["req"] = {"answers": [], "product": product}
        if product:
            session.state = "REQ_Q0"
            return [OutMsg(T[lang]["ask_quantity"].format(product=product),
                           _qr([(BOOK_T[lang]["cancel_button"], "BCANCEL")]))]
        return self._ask_question(session, lang, biz, 0)

    def handle(self, session: Session, lang: str, biz: dict, text: str) -> Tuple[List[OutMsg], bool]:
        """Returns (messages, done). done=True hands the conversation back to chat."""
        t, bt = T[lang], BOOK_T[lang]
        cancel = _qr([(bt["cancel_button"], "BCANCEL")])
        if text == "BCANCEL" or text.lower() in CANCEL_WORDS:
            session.data.pop("req", None)
            return [OutMsg(t["cancelled"])], True

        cfg = self.configs[biz["id"]]
        req = session.data.setdefault("req", {"answers": []})
        state = session.state

        if state.startswith("REQ_Q"):
            index = int(state[5:])
            if len(text.strip()) < 2 or BUTTON_PAYLOAD_RE.match(text):
                return [OutMsg(t["bad_answer"], cancel)], False
            answer = text.strip()
            if index == 0 and req.get("product"):
                answer = f"{req['product']} × {answer}"
            req["answers"].append(answer)
            if index + 1 < len(cfg["questions"]):
                return self._ask_question(session, lang, biz, index + 1), False
            session.state = "REQ_NAME"
            return [OutMsg(bt["ask_name"], cancel)], False

        if state == "REQ_NAME":
            name = text.strip()
            if not re.search(r"[^\W\d_]", name) or len(name) > 60 or BUTTON_PAYLOAD_RE.match(name):
                return [OutMsg(bt["bad_name"], cancel)], False
            req["name"] = name
            session.state = "REQ_PHONE"
            return [OutMsg(bt["ask_phone"], cancel)], False

        if state == "REQ_PHONE":
            phone = normalize_phone(text)
            if not phone:
                return [OutMsg(bt["bad_phone"], cancel)], False
            req["phone"] = phone
            session.state = "REQ_CONFIRM"
            return [self._summary(lang, cfg, req)], False

        if state == "REQ_CONFIRM":
            if text != "BOK":
                return [OutMsg(bt["pick_button"]), self._summary(lang, cfg, req)], False
            return self._save(session, lang, biz, cfg, req)

        session.data.pop("req", None)
        return [], True

    def _ask_question(self, session, lang, biz, index: int) -> List[OutMsg]:
        session.state = f"REQ_Q{index}"
        question = self.configs[biz["id"]]["questions"][index][lang]
        return [OutMsg(question, _qr([(BOOK_T[lang]["cancel_button"], "BCANCEL")]))]

    @staticmethod
    def _answers_text(req) -> str:
        return "\n".join(f"• {a}" for a in req["answers"])

    def _summary(self, lang, cfg, req) -> OutMsg:
        bt = BOOK_T[lang]
        text = T[lang]["summary"].format(title=cfg["title"][lang], answers=self._answers_text(req),
                                         name=req["name"], phone=req["phone"])
        return OutMsg(text, _qr([(bt["confirm_button"], "BOK"), (bt["cancel_button"], "BCANCEL")]))

    def _save(self, session, lang, biz, cfg, req) -> Tuple[List[OutMsg], bool]:
        self.store.save_request({
            "business_id": biz["id"], "sender_id": session.sender_id, "channel": session.channel,
            "title": cfg["title"]["mn"], "details": req["answers"], "name": req["name"],
            "phone": req["phone"],
        })
        session.data.pop("req", None)
        session.data["last_request"] = {"title": cfg["title"][lang], "answers": req["answers"],
                                        "name": req["name"], "phone": req["phone"]}
        text = T[lang]["done"].format(title=cfg["title"][lang], answers=self._answers_text(req),
                                      next=cfg["done"][lang])
        return [OutMsg(text)], True
