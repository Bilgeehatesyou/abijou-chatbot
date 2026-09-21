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
    "default": "Сайн байна уу! Ажилт-AI чатбот танай Messenger-т 24/7 хариулж, цаг захиалга авна. "
               "«Эхлэх» дээр дарж туршаад үзээрэй.",
    "en_US": "Hi! Ajilt-AI answers your Messenger 24/7 and takes bookings. Tap Get Started to try it.",
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


if __name__ == "__main__":
    print(set_get_started())


def _to_meta_message(m: OutMsg) -> dict:
    msg = {"text": m.text[:2000]}  # Messenger's text limit
    if m.quick_replies:
        msg["quick_replies"] = [
            {"content_type": "text", "title": q.title[:20], "payload": q.payload}
            for q in m.quick_replies
        ]
    return msg


def get_user_locale(user_id: str) -> Optional[str]:
    """Messenger user's Facebook language setting, e.g. "mn_MN". None if unavailable."""
    if not settings.PAGE_ACCESS_TOKEN:
        return None
    try:
        r = httpx.get(
            f"https://graph.facebook.com/{settings.GRAPH_API_VERSION}/{user_id}",
            params={"fields": "locale", "access_token": settings.PAGE_ACCESS_TOKEN},
            timeout=10,
        )
        return r.json().get("locale") if r.status_code == 200 else None
    except Exception:
        return None


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
        try:
            r = httpx.post(
                url,
                json={
                    "recipient": {"id": recipient_id},
                    "messaging_type": "RESPONSE",
                    "message": _to_meta_message(m),
                },
                timeout=15,
            )
            if r.status_code >= 400:
                print(f"[meta] send error {r.status_code}: {r.text}")
        except Exception as e:
            print(f"[meta] send exception: {e}")
