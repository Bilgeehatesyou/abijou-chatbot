"""Terminal simulator — test the exact conversation flow without Meta.

    python -m app.cli

Type your answers. When the bot shows buttons you can type the number,
the button text, or free text.

BOT_MODE=demo starts at the "Ajilt-AI or demo?" choice and reads the FAQ data from
DB_PATH (run `python -m app.demo_data load` first). BOT_MODE=sales runs only the
sales flow and saves leads to cli.db. Set CLI_LOCALE=en_US to simulate an English
Facebook user.
"""
import os

from .config import settings
from .llm import get_llm
from .models import Session
from .store import Store


def _print(messages):
    for m in messages:
        print(f"\nBot> {m.text}")
        for i, c in enumerate(m.cards or []):
            buttons = "  ".join(f"<{b.title}: {b.payload}>" for b in c.buttons)
            print(f"      🃏 {c.title} — {c.subtitle}  {buttons}")
        if m.quick_replies:
            opts = "   ".join(f"[{i+1}] {q.title}" for i, q in enumerate(m.quick_replies))
            print(f"      {opts}")


def main():
    if settings.BOT_MODE == "sales":
        from .conversation import Engine
        from .pricing import Pricing
        store = Store("cli.db")
        engine = Engine(llm=get_llm(), pricing=Pricing(settings.PRICING_PATH), store=store)
    else:
        from .conversation import Engine
        from .demo import DemoEngine
        from .gcal import get_calendar
        from .pricing import Pricing
        from .router import AppRouter
        store = Store(settings.DB_PATH)
        store.reset_session("cli-user")
        locale = os.getenv("CLI_LOCALE")
        lookup = lambda _id: locale  # noqa: E731
        llm = get_llm()
        demo = DemoEngine(llm=llm, store=store, locale_lookup=lookup, calendar=get_calendar())
        sales = Engine(llm=llm, pricing=Pricing(settings.PRICING_PATH), store=store, booking=demo.booking)
        engine = AppRouter(demo, sales, store, locale_lookup=lookup)
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