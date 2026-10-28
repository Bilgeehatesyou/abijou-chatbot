"""Terminal simulator — test the exact conversation without Meta.

    python -m app.cli

Type your answers. When the bot shows buttons you can type the number,
the button text, or free text. Bookings go into DB_PATH like real ones.
"""
from .bot import ClinicBot
from .clinic import get_clinic
from .config import settings
from .gcal import get_calendar
from .llm import get_llm
from .models import Session
from .store import Store


def _print(messages):
    for m in messages:
        print(f"\nBot> {m.text}")
        if m.quick_replies:
            opts = "   ".join(f"[{i+1}] {q.title}" for i, q in enumerate(m.quick_replies))
            print(f"      {opts}")


def main():
    store = Store(settings.DB_PATH)
    store.reset_session("cli-user")
    engine = ClinicBot(llm=get_llm(), store=store, clinic=get_clinic(), calendar=get_calendar())
    session = Session(sender_id="cli-user", channel="cli")

    print(f"=== {settings.BOT_NAME} simulator ===  (Ctrl-C to quit)")
    last_replies = engine.handle(session, "")  # kick off with greeting
    _print(last_replies)

    while True:
        try:
            user = input("\nYou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            break

        # Let the user type a number to pick the last shown quick reply.
        if user.isdigit() and last_replies:
            idx = int(user) - 1
            qrs = [q for m in last_replies for q in (m.quick_replies or [])]
            if 0 <= idx < len(qrs):
                user = qrs[idx].payload

        last_replies = engine.handle(session, user)
        _print(last_replies)


if __name__ == "__main__":
    main()
