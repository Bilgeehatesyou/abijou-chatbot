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
LAST_TITLES = "_zev_titles"

# A ZevChat flow has a fixed set of quick replies, so we always return the same
# number of labels and pad the unused ones with a button that is never wrong.
BUTTON_SLOTS = 5
BUTTON_MAX = 20        # Messenger's quick-reply title limit
FILLER = ("🏠 Эхлэл", "HOME")


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
    texts, options, buttons, cards = [], [], [], []

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
            options, buttons = [], []
            for i, q in enumerate(m.quick_replies, 1):
                options.append(f"{i}) {q.title}")
                buttons.append((q.title[:BUTTON_MAX], q.payload))

    if cards:
        texts.append("\n".join(cards))
    # More options than button slots: the extras are still reachable by number.
    if len(options) > BUTTON_SLOTS:
        texts.append("\n".join(options) + "\n\nДугаараар нь бичээрэй.")

    slots = (buttons + [FILLER] * BUTTON_SLOTS)[:BUTTON_SLOTS]
    reply = "\n\n".join(t for t in texts if t).strip()
    out = {
        # Tested against ZevChat: a mapped subscriber field keeps emoji but is
        # dropped entirely if the value contains a line break, so everything
        # goes on one line separated by "·".
        "reply": one_line(reply),
        # Same without emoji, for a client whose database is plain utf8.
        "reply_plain": plain(reply),
        "options": " | ".join(options),
        "choices": [p for _, p in slots],
        "titles": [t for t, _ in slots],
    }
    for i, (title, _) in enumerate(slots, 1):
        out[f"opt{i}"] = title
    return out


EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]")


def one_line(text: str) -> str:
    return re.sub(r"\s*\n+\s*", " · ", text).strip()


def plain(text: str) -> str:
    return one_line(EMOJI.sub("", text))


def _key(text: str) -> str:
    return re.sub(r"\s+", " ", EMOJI.sub("", text or "")).strip().lower()


def resolve_choice(session: Session, text: str) -> str:
    """Turn what the visitor sent back into a button payload.

    Tapping a quick reply sends its *title*, and typing "2" means the second
    option, so both have to map back to what the engine expects.
    """
    choices = session.data.get(LAST_CHOICES) or []
    titles = session.data.get(LAST_TITLES) or []
    stripped = text.strip().strip(".)")

    if choices and stripped.isdigit():
        i = int(stripped)
        if 1 <= i <= len(choices):
            return choices[i - 1]

    tapped = _key(text)
    if not tapped:
        return text
    for title, payload in zip(titles, choices):
        if _key(title) == tapped:
            return payload
    # The filler button is on screen even in turns whose own options filled
    # every slot, so it has to work without being in that turn's list.
    if tapped == _key(FILLER[0]):
        return FILLER[1]
    return text


def remember_choices(session: Session, choices: List[str], titles: List[str] = ()):
    if choices:
        session.data[LAST_CHOICES] = choices
        session.data[LAST_TITLES] = list(titles)
    else:
        session.data.pop(LAST_CHOICES, None)
        session.data.pop(LAST_TITLES, None)
