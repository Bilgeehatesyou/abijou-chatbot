"""Mirror what the chatbot collects into the client's CRM (bas.mn).

Our database stays the source of truth for the conversation; the CRM is where
the client actually works. Every push here is best-effort: a CRM that is down,
slow or misconfigured must never cost the visitor their answer, so failures are
logged and swallowed.

Perfex has no order object and this build has no custom tables, so an order is
written as a Lead with the items in its description. When Robot Soft adds the
`ajilt_orders` table, `push_order` is the only thing that changes.
"""
from datetime import datetime
from typing import List, Optional

from .basmn import BasMN, configured

# Every lead a bot creates is assigned to this staff member and marked with
# this source/status until a client asks for their own pipeline ids.
DEFAULT_SOURCE = 1
DEFAULT_STATUS = 1
DEFAULT_ASSIGNED = 1

CHANNELS = {"messenger": "Messenger", "instagram": "Instagram",
            "zevchat": "Messenger (ZevChat)", "web": "Вэбсайт", "cli": "Туршилт"}


def _client() -> Optional[BasMN]:
    return BasMN() if configured() else None


def _note(lines: List[str]) -> str:
    return "\n".join(line for line in lines if line)


def push_lead(name: str, phone: str, *, business: str = "", channel: str = "",
              interest: str = "", note: str = "") -> Optional[str]:
    """Someone left their name and number."""
    bas = _client()
    if not bas:
        return None
    try:
        return bas.create_lead(
            name=name or "Чатботын лид",
            phone=phone,
            note=_note([interest, note,
                        f"Суваг: {CHANNELS.get(channel, channel or '—')}",
                        f"Бизнес: {business}" if business else "",
                        "Ажилт-AI чатботоор бүртгэгдсэн."]),
            source=DEFAULT_SOURCE, status=DEFAULT_STATUS, assigned=DEFAULT_ASSIGNED,
        )
    except Exception as e:      # never at the visitor's expense
        print(f"[crm] lead push failed: {type(e).__name__}: {e}")
        return None


def push_booking(*, title: str, start: datetime, end: datetime, name: str, phone: str,
                 business: str = "", service: str = "", staff: str = "",
                 channel: str = "") -> Optional[str]:
    """A confirmed appointment goes in the CRM calendar."""
    bas = _client()
    if not bas:
        return None
    try:
        return bas.create_event(
            title=title,
            start=start, end=end,
            staff_id=DEFAULT_ASSIGNED,
            description=_note([
                f"Үйлчилгээ: {service}" if service else "",
                f"Үйлчлүүлэгч: {name} · {phone}",
                f"Ажилтан: {staff}" if staff else "",
                f"Бизнес: {business}" if business else "",
                f"Суваг: {CHANNELS.get(channel, channel or '—')}",
                "Ажилт-AI чатботоор захиалсан.",
            ]),
        )
    except Exception as e:
        print(f"[crm] booking push failed: {type(e).__name__}: {e}")
        return None


def push_order(*, name: str, phone: str, details: List[str], business: str = "",
               title: str = "", channel: str = "") -> Optional[str]:
    """An order or stay request. A Lead for now — see the module docstring."""
    return push_lead(
        name=name, phone=phone, business=business, channel=channel,
        interest=title or "Захиалга",
        note=_note(["Захиалгын мэдээлэл:", *(f"• {d}" for d in details if d)]),
    )
