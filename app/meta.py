"""Meta Messaging API helpers — sending and parsing for both Messenger and
Instagram. Both channels use the same webhook + Send API shape; they differ
only in the top-level `object` field ("page" vs "instagram")."""
import hashlib
import hmac
from typing import List, Optional, Tuple

import httpx

from .config import settings
from .models import OutMsg


def verify_signature(app_secret: str, payload: bytes, header: Optional[str]) -> bool:
    """Validate X-Hub-Signature-256. If no app secret is configured, skip
    (useful for local testing)."""
    if not app_secret:
        return True
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.split("=", 1)[1])


def parse_events(body: dict) -> List[Tuple[str, str, str]]:
    """Turn a webhook body into a list of (channel, sender_id, user_input).

    user_input is the quick-reply payload when the user tapped a button,
    otherwise the raw message text. Non-message events (delivery, read,
    echoes) are ignored.
    """
    obj = body.get("object", "")
    channel = "instagram" if obj == "instagram" else "messenger"
    events: List[Tuple[str, str, str]] = []

    for entry in body.get("entry", []):
        for msg in entry.get("messaging", []):
            sender = msg.get("sender", {}).get("id")
            if not sender:
                continue
            postback = msg.get("postback")  # Get Started button / persistent menu
            if postback and postback.get("payload"):
                events.append((channel, sender, postback["payload"]))
                continue
            message = msg.get("message")
            if not message or message.get("is_echo"):
                continue
            qr = message.get("quick_reply")
            user_input = qr["payload"] if qr else message.get("text", "")
            events.append((channel, sender, user_input))
    return events


GREETING = {
    "default": "Сайн байна уу! Abijou клиникийн туслах 24/7 хариулж, Монгол, Солонгос салбарт цаг "
               "захиална. «Эхлэх» дээр дарна уу.",
    "en_US": "Hi! Abijou Clinic's assistant answers 24/7 and books appointments in Mongolia and Korea. "
             "Tap Get Started.",
    "ko_KR": "안녕하세요! 아비쥬의원 상담원이 24시간 답변하고 몽골·한국 지점 예약을 도와드립니다. "
             "시작하기를 눌러 주세요.",
}


def set_get_started() -> dict:
    """Configure the Page's Get Started button (sends the GET_STARTED postback) and
    the greeting shown before a new visitor's first message."""
    body = {
        "get_started": {"payload": "GET_STARTED"},
        "greeting": [{"locale": loc, "text": text[:160]} for loc, text in GREETING.items()],
    }
    r = httpx.post(
        f"https://graph.facebook.com/{settings.GRAPH_API_VERSION}/me/messenger_profile",
        params={"access_token": settings.PAGE_ACCESS_TOKEN}, json=body, timeout=15,
    )
    return {"status": r.status_code, "body": r.json()}


def _to_meta_messages(m: OutMsg) -> List[dict]:
    """One OutMsg -> Messenger messages: the text, then a carousel if it has cards.
    Quick replies go on the last message so they stay visible."""
    msgs = []
    if m.text:
        msgs.append({"text": m.text[:2000]})  # Messenger's text limit
    if m.cards:
        elements = []
        for c in m.cards[:10]:  # Messenger shows at most 10 cards
            el = {"title": c.title[:80], "subtitle": c.subtitle[:80]}
            if c.image_url:
                el["image_url"] = c.image_url
            if c.buttons:
                el["buttons"] = [{"type": "postback", "title": b.title[:20], "payload": b.payload}
                                 for b in c.buttons[:3]]
            elements.append(el)
        msgs.append({"attachment": {"type": "template", "payload": {
            "template_type": "generic", "image_aspect_ratio": "square", "elements": elements}}})
    if m.quick_replies and msgs:
        msgs[-1]["quick_replies"] = [
            {"content_type": "text", "title": q.title[:20], "payload": q.payload}
            for q in m.quick_replies
        ]
    return msgs


def send_typing(recipient_id: str):
    """Show the '...' typing bubble while the LLM is working."""
    if not settings.PAGE_ACCESS_TOKEN:
        return
    try:
        httpx.post(
            f"https://graph.facebook.com/{settings.GRAPH_API_VERSION}/me/messages",
            params={"access_token": settings.PAGE_ACCESS_TOKEN},
            json={"recipient": {"id": recipient_id}, "sender_action": "typing_on"},
            timeout=10,
        )
    except Exception:
        pass


def send(recipient_id: str, messages: List[OutMsg]):
    """Send one or more messages back to the user via the Send API."""
    if not settings.PAGE_ACCESS_TOKEN:
        print("[meta] PAGE_ACCESS_TOKEN not set — skipping send.")
        return
    url = (f"https://graph.facebook.com/{settings.GRAPH_API_VERSION}/me/messages"
           f"?access_token={settings.PAGE_ACCESS_TOKEN}")
    for m in messages:
        for message in _to_meta_messages(m):
            try:
                r = httpx.post(
                    url,
                    json={
                        "recipient": {"id": recipient_id},
                        "messaging_type": "RESPONSE",
                        "message": message,
                    },
                    timeout=15,
                )
                if r.status_code >= 400:
                    print(f"[meta] send error {r.status_code}: {r.text}")
            except Exception as e:
                print(f"[meta] send exception: {e}")


if __name__ == "__main__":
    print(set_get_started())
