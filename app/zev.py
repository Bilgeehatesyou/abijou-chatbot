"""ZevChat door into the same bot.

ZevChat's "HTTP API Integration" calls one URL and maps the response's *fields*
onto subscriber fields, so everything it gets back has to be flat text — no
nested messages, no carousels. This module squashes the engine's normal output
(text + quick replies + product cards) into that shape, and turns the visitor's
"2" back into the button payload it stands for.
"""
from typing import List

from .models import Session

MAX_CARDS = 5          # a Messenger text bubble is 2000 chars; keep it short
LAST_CHOICES = "_zev_choices"


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

    return {
        "reply": "\n\n".join(t for t in texts if t).strip(),
        "options": " | ".join(options),
        "choices": choices,
    }


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
