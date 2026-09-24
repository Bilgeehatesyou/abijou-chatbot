"""ZevChat door into the same bot.

ZevChat's "HTTP API Integration" calls one URL and maps the response's *fields*
onto subscriber fields, so everything it gets back has to be flat text — no
nested messages, no carousels. This module squashes the engine's normal output
(text + quick replies + product cards) into that shape, and turns the visitor's
"2" back into the button payload it stands for.
"""
import re
from typing import List, Optional

from .models import Session

MAX_CARDS = 5          # a Messenger text bubble is 2000 chars; keep it short
LAST_CHOICES = "_zev_choices"


PLACEHOLDER = re.compile(r"#[A-Za-z0-9_]+#")


def clean_incoming(text: str) -> str:
    """Drop ZevChat variables it didn't fill in.

    A test call (or a flow step with no message yet) arrives as the literal
    "#LEAD_USER_LAST_CHAT#". Treated as real text it looks like English and
    flips the whole conversation's language, so it counts as nothing said.
    """
    return PLACEHOLDER.sub(" ", text or "").strip()


def salvage(raw: str) -> Optional[dict]:
    """Rescue a body whose JSON a visitor's own quote broke.

    ZevChat builds the body from a template, so `{"message": "he said "hi""}`
    is a normal thing to receive. Pull the two fields out by hand instead of
    losing the message.
    """
    sub = re.search(r'"subscriber_id"\s*:\s*"?([^",}]*)"?', raw)
    msg = re.search(r'"message"\s*:\s*"(.*)"\s*}\s*$', raw, re.S)
    if not sub:
        return None
    return {"subscriber_id": sub.group(1).strip(),
            "message": msg.group(1) if msg else ""}


def flatten(messages: List) -> dict:
    """Engine messages -> the flat fields a ZevChat flow can use."""
    texts, options, choices, cards = [], [], [], []

    for m in messages:
        if m.text:
            texts.append(m.text)
        for c in (m.cards or [])[:MAX_CARDS]:
            line = f"• {c.title}"
            if c.subtitle:
                line += f" — {c.subtitle}"
            cards.append(line)
        # Only the last message's buttons matter; earlier ones are already answered.
        if m.quick_replies:
            options, choices = [], []
            for i, q in enumerate(m.quick_replies, 1):
                options.append(f"{i}) {q.title}")
                choices.append(q.payload)

    if cards:
        texts.append("\n".join(cards))
    if options:
        texts.append("\n".join(options) + "\n\nДугаараар нь бичээрэй.")

    reply = "\n\n".join(t for t in texts if t).strip()
    return {
        # Tested against ZevChat: a mapped subscriber field keeps emoji but is
        # dropped entirely if the value contains a line break, so everything
        # goes on one line separated by "·".
        "reply": one_line(reply),
        # Same without emoji, for a client whose database is plain utf8.
        "reply_plain": plain(reply),
        "options": " | ".join(options),
        "choices": choices,
    }


EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]")


def one_line(text: str) -> str:
    return re.sub(r"\s*\n+\s*", " · ", text).strip()


def plain(text: str) -> str:
    return one_line(EMOJI.sub("", text))


def resolve_choice(session: Session, text: str) -> str:
    """"2" -> the payload of the second button we offered last turn."""
    choices = session.data.get(LAST_CHOICES) or []
    stripped = text.strip().strip(".)")
    if choices and stripped.isdigit():
        i = int(stripped)
        if 1 <= i <= len(choices):
            return choices[i - 1]
    return text


def remember_choices(session: Session, choices: List[str]):
    if choices:
        session.data[LAST_CHOICES] = choices
    else:
        session.data.pop(LAST_CHOICES, None)
