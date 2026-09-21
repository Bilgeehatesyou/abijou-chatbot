"""Small data structures shared across the app."""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


@dataclass
class QuickReply:
    title: str      # what the user sees on the button (<=20 chars for Meta)
    payload: str    # what we get back when they tap it


@dataclass
class OutMsg:
    """One outgoing message. Optionally carries quick-reply buttons."""
    text: str
    quick_replies: Optional[List[QuickReply]] = None


@dataclass
class Session:
    """Per-user conversation state, keyed by the Meta sender id (PSID/IGSID)."""
    sender_id: str
    channel: str = "messenger"          # "messenger" | "instagram" | "cli"
    state: str = "START"
    data: Dict[str, Any] = field(default_factory=dict)
