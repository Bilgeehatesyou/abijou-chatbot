"""Property listings for the real-estate demo (data/demo/catalogs/real_estate.json).

Same role as the MCC product catalog (app/catalog.py) and the same interface, so the
demo engine treats both alike: browse by type, search from free text, picture cards
under the answer. A listing card's buttons show its details or book a viewing.

Search understands districts and areas ("Зайсан", "zaisan"), property types
("байр", "хаус", "оффис", "газар"), rooms ("3 өрөө", "3 room"), budgets
("400 сая хүртэл", "under 1 billion") and sizes ("80 м2"), in Mongolian, English
and Mongolian typed in Latin letters. Prices are quoted in total and per m².
"""
import io
import re

from .catalog import CARD, _font, _wrap, tokens, translit
from .models import Card, QuickReply

TYPES = {
    "apartment": {"mn": "Орон сууц", "en": "Apartments", "emoji": "🏢",
                  "color": (219, 234, 254), "accent": (37, 99, 235),
                  "words": ["байр", "орон сууц", "апартмент", "студио", "apartment", "flat",
                            "condo", "studio", "bair", "oron", "suuts"]},
    "house": {"mn": "Хаус, байшин", "en": "Houses", "emoji": "🏡",
              "color": (220, 252, 231), "accent": (22, 128, 61),
              "words": ["хаус", "байшин", "таунхаус", "вилла", "house", "home", "townhouse",
                        "villa", "haus", "baishin"]},
    "office": {"mn": "Оффис, талбай", "en": "Offices & retail", "emoji": "🏬",
               "color": (243, 232, 255), "accent": (126, 34, 206),
               "words": ["оффис", "офис", "талбай", "үйлчилгээний", "дэлгүүр", "office", "retail",
                         "shop", "commercial", "ofis", "talbai"]},
    "land": {"mn": "Газар", "en": "Land", "emoji": "🌳",
             "color": (254, 243, 199), "accent": (180, 83, 9),
             "words": ["газар", "хашаа", "land", "plot", "gazar"]},
}

UI = {
    "mn": {"browse": "🏠 Зарууд", "pick_type": "Ямар төрлийн зар үзэх вэ? Эсвэл бичээд хайгаарай "
                                            "(жишээ нь: «Зайсанд 3 өрөө», «400 сая хүртэл»).",
           "details": "ℹ Дэлгэрэнгүй", "view": "📅 Үзэх цаг авах",
           "rooms": "{n} өрөө", "floor": "Давхар", "year": "Ашиглалтад орсон", "area": "Талбай",
           "price": "Үнэ", "per_m2": "1 м² үнэ", "mortgage": "🏦 8%-ийн ипотекийн зээлд хамрагдах боломжтой",
           "sample": "Жишээ зар", "sample_image": "Жишээ зураг"},
    "en": {"browse": "🏠 Listings", "pick_type": "Which kind of property would you like to see? Or "
                                               "type to search (e.g. “3-room in Zaisan”, “under 400 million”).",
           "details": "ℹ Details", "view": "📅 Book a viewing",
           "rooms": "{n} rooms", "floor": "Floor", "year": "Built", "area": "Area",
           "price": "Price", "per_m2": "Price per m²", "mortgage": "🏦 Eligible for the 8% mortgage programme",
           "sample": "Sample listing", "sample_image": "Sample image"},
}

# Words that only carry numbers/units or chit-chat; they must not count as matches.
SEARCH_STOPWORDS = {"uruu", "oroo", "room", "rooms", "br", "bedroom", "say", "saya", "terbum",
                    "million", "mln", "billion", "bn", "m2", "mkv", "kv", "sqm", "hurtel",
                    "doosh", "deesh", "under", "below", "over", "above", "up", "to", "max",
                    "min", "zarna", "zarah", "zar", "zaruud", "avmaar", "uzmeer", "uzeh",
                    "bga", "bgaa", "baigaa", "baina", "bii", "yu", "yuu", "uu", "ve", "hed",
                    "une", "unetei", "m", "in", "with", "near", "there", "any", "an", "are",
                    "what", "which", "show", "me", "want", "looking", "buy", "sale",
                    "hudaldaj", "hudaldah", "zarag", "darj", "ali", "neg", "ner"}
ROOMS_RE = re.compile(r"(\d)\s*-?\s*(?:uruu|oroo|room|bedroom|br|bed)")
PRICE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(saya|say|million|mln|terbum|billion|bn)")
AREA_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:m2|m²|mkv|kvm|kv\.?m|sqm|kv)\b")
SKU_RE = re.compile(r"\bre\s*-?\s*0?(\d{1,2})\b")
MAX_WORDS = ("hurtel", "doosh", "baga", "under", "below", "up to", "max", "less", "within")
MIN_WORDS = ("deesh", "iluu", "over", "above", "more than", "from", "at least")


def _hit(q: str, words: set) -> bool:
    """Exact, or the word plus a Mongolian case ending: «Зайсанд», «Яармагт», «байраа»."""
    return q in words or any(len(w) >= 4 and q.startswith(w) and len(q) - len(w) <= 4 for w in words)


def _num(text: str) -> float:
    return float(text.replace(",", "."))


def money(amount: float, lang: str) -> str:
    """865 сая₮ / 1.95 тэрбум₮ — the way people say property prices."""
    if amount >= 1e9:
        value = f"{amount / 1e9:.2f}".rstrip("0").rstrip(".")
        return f"{value} тэрбум₮" if lang == "mn" else f"MNT {value}B"
    if amount >= 1e6:
        value = f"{amount / 1e6:.1f}".rstrip("0").rstrip(".")
        return f"{value} сая₮" if lang == "mn" else f"MNT {value}M"
    value = f"{amount / 1e3:.0f}"
    return f"{value} мянга₮" if lang == "mn" else f"MNT {value}K"


def price_per_m2(p: dict) -> int:
    return round(p["price_mnt"] / p["area_m2"]) if p.get("area_m2") else 0


def per_m2_label(p: dict, lang: str) -> str:
    v = price_per_m2(p)
    if v >= 1e6:
        value = f"{v / 1e6:.2f}".rstrip("0").rstrip(".")
        return f"{value} сая₮/м²" if lang == "mn" else f"MNT {value}M/m²"
    return f"{v / 1e3:.0f} мянга₮/м²" if lang == "mn" else f"MNT {v / 1e3:.0f}K/m²"


def facts_line(p: dict, lang: str) -> str:
    """112.5 м² · 3 өрөө · 865 сая₮ (7.69 сая₮/м²)"""
    parts = [f"{p['area_m2']:g} м²" if lang == "mn" else f"{p['area_m2']:g} m²"]
    if p.get("rooms"):
        parts.append(UI[lang]["rooms"].format(n=p["rooms"]))
    parts.append(f"{money(p['price_mnt'], lang)} ({per_m2_label(p, lang)})")
    return " · ".join(parts)


class Listings:
    kind = "listings"

    def __init__(self, items: list):
        self.products = items                      # name kept so the engine can treat both alike
        self.by_sku = {p["sku"]: p for p in items}
        self._index = []
        for p in items:
            place = set(tokens(" ".join(p[k][lang] for k in ("area_name", "district")
                                        for lang in ("mn", "en"))))
            kind = set(tokens(" ".join(TYPES[p["type"]]["words"] + [TYPES[p["type"]]["mn"],
                                                                    TYPES[p["type"]]["en"]])))
            title = set(tokens(p["title"]["mn"] + " " + p["title"]["en"]))
            self._index.append((p, place - SEARCH_STOPWORDS, kind - SEARCH_STOPWORDS,
                                title - SEARCH_STOPWORDS))

    # ---- browsing ----
    def categories(self) -> list:
        present = {p["type"] for p in self.products}
        return [t for t in TYPES if t in present]

    def in_category(self, category: str) -> list:
        return sorted((p for p in self.products if p["type"] == category), key=lambda p: p["price_mnt"])

    def category_label(self, category: str, lang: str) -> str:
        t = TYPES[category]
        return f"{t['emoji']} {t[lang]}"

    def browse_button(self, lang: str) -> str:
        return UI[lang]["browse"]

    def pick_text(self, lang: str) -> str:
        return UI[lang]["pick_type"]

    # ---- search ----
    @staticmethod
    def filters(text: str) -> dict:
        low = translit(text)
        out = {}
        m = ROOMS_RE.search(low)
        if m:
            out["rooms"] = int(m.group(1))
        m = PRICE_RE.search(low)
        if m:
            scale = 1e9 if m.group(2) in ("terbum", "billion", "bn") else 1e6   # "тэрбумаас" too
            out["price"] = _num(m.group(1)) * scale
            out["price_dir"] = ("max" if any(w in low for w in MAX_WORDS)
                                else "min" if any(w in low for w in MIN_WORDS) else "about")
        m = AREA_RE.search(low)
        if m:
            out["area"] = _num(m.group(1))
        m = SKU_RE.search(low)
        if m:
            out["sku"] = f"RE{int(m.group(1)):02d}"
        return out

    @staticmethod
    def _passes(p: dict, f: dict) -> bool:
        if "rooms" in f and p.get("rooms") != f["rooms"]:
            return False
        if "price" in f:
            price, budget = p["price_mnt"], f["price"]
            if f["price_dir"] == "max" and price > budget * 1.05:
                return False
            if f["price_dir"] == "min" and price < budget * 0.95:
                return False
            if f["price_dir"] == "about" and not budget * 0.75 <= price <= budget * 1.25:
                return False
        if "area" in f and not f["area"] * 0.75 <= p["area_m2"] <= f["area"] * 1.25:
            return False
        return True

    def search(self, text: str, limit: int = 10) -> list:
        f = self.filters(text)
        if f.get("sku") in self.by_sku:
            return [self.by_sku[f["sku"]]]
        query = [q for q in tokens(text) if q not in SEARCH_STOPWORDS and not q[0].isdigit()]
        has_filters = any(k in f for k in ("rooms", "price", "area"))
        scored, placed = [], False
        for p, place, kind, title in self._index:
            if not self._passes(p, f):
                continue
            in_place = [q for q in query if _hit(q, place)]
            placed = placed or bool(in_place)
            score = 3 * len(in_place) + sum(2 if _hit(q, kind) else 1 if _hit(q, title) else 0
                                            for q in query if q not in in_place)
            if score or (has_filters and not query):
                scored.append((score, bool(in_place), p))
        if placed:      # a place was named: only listings there
            scored = [s for s in scored if s[1]]
        scored = [(score, p) for score, _, p in scored]
        if not scored and has_filters and query:
            # e.g. "3 өрөө Гачуурт" with nothing in Gachuurt: offer what fits the numbers
            scored = [(0, p) for p, *_ in self._index if self._passes(p, f)]
        scored.sort(key=lambda s: (-s[0], s[1]["price_mnt"]))
        return [p for _, p in scored[:limit]]

    # ---- presentation ----
    def card(self, p: dict, lang: str, image_url: str) -> Card:
        return Card(
            title=p["title"][lang], subtitle=facts_line(p, lang)[:80], image_url=image_url,
            buttons=[QuickReply(UI[lang]["details"], f"INFO_{p['sku']}"),
                     QuickReply(UI[lang]["view"], f"VIEW_{p['sku']}")],
        )

    def details(self, p: dict, lang: str) -> str:
        u = UI[lang]
        lines = [f"{TYPES[p['type']]['emoji']} {p['title'][lang]} ({p['sku']})",
                 f"📍 {p['address'][lang]}",
                 f"📐 {u['area']}: {p['area_m2']:g} {'м²' if lang == 'mn' else 'm²'}"]
        extra = []
        if p.get("rooms"):
            extra.append(u["rooms"].format(n=p["rooms"]))
        if p.get("floor"):
            extra.append(f"{u['floor']}: {p['floor']}")
        if p.get("year"):
            extra.append(f"{u['year']}: {p['year']}")
        if extra:
            lines.append("🚪 " + " · ".join(extra))
        lines += [f"💰 {u['price']}: {p['price_mnt']:,}₮ ({money(p['price_mnt'], lang)})",
                  f"📊 {u['per_m2']}: {price_per_m2(p):,}₮",
                  f"✨ {p['features'][lang]}"]
        if p.get("mortgage"):
            lines.append(u["mortgage"])
        lines.append(f"({u['sample']})")
        return "\n".join(lines)

    def booking_item(self, p: dict) -> dict:
        """What the booking flow needs to know about the property being viewed."""
        return {"id": p["sku"], "title": p["title"], "short": p["short"], "address": p["address"]}

    def prompt_context(self, matches: list, lang: str) -> str:
        """Every listing goes to the LLM (there are few), so it can compare and filter."""
        lines = []
        for p in self.products:
            rooms = UI["en"]["rooms"].format(n=p["rooms"]) if p.get("rooms") else ""
            lines.append(" | ".join(x for x in (
                p["sku"], TYPES[p["type"]]["en"], p["title"][lang], p["address"][lang],
                f"{p['area_m2']:g} m²", rooms, f"floor {p['floor']}" if p.get("floor") else "",
                f"built {p['year']}" if p.get("year") else "", f"price {p['price_mnt']:,} MNT",
                f"{price_per_m2(p):,} MNT per m²", p["features"][lang],
                "8% mortgage eligible" if p.get("mortgage") else "") if x))
        shown = ", ".join(p["sku"] for p in matches) or "none"
        return (
            f"\n\nPROPERTY LISTINGS ({len(self.products)} for sale, all fictional demo data; "
            "prices in MNT, price per m² = price / area):\n" + "\n".join(lines) +
            f"\n\nListings shown as picture cards under your reply: {shown}. Quote prices and "
            "sizes exactly from this list, e.g. «865 сая₮ (1 м² нь 7.69 сая₮)». Mention at most 3 "
            "listings by name. Each card has buttons for details and booking a viewing."
        )

    # ---- picture card ----
    def render(self, p: dict, lang: str = "mn") -> bytes:
        from PIL import Image, ImageDraw
        t = TYPES[p["type"]]
        bg, accent = t["color"], t["accent"]
        img = Image.new("RGB", (CARD, CARD), bg)
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((40, 40, 560, 560), radius=36, fill=(255, 255, 255), outline=accent, width=6)
        d.rounded_rectangle((43, 43, 557, 120), radius=33, fill=accent, corners=(True, True, False, False))
        band = f"{t[lang].upper()} · {p['sku']}"
        f_band = _font(True, 34)
        d.text(((CARD - d.textlength(band, font=f_band)) / 2, 60), band, font=f_band, fill=(255, 255, 255))
        _building(d, p["type"], CARD // 2, 215, accent)
        f_place = _font(True, 34)
        y = 300
        for line in _wrap(d, p["area_name"][lang] + ", " + p["district"][lang], f_place, 470, 1):
            d.text(((CARD - d.textlength(line, font=f_place)) / 2, y), line, font=f_place, fill=(40, 40, 40))
        f_price = _font(True, 58)
        price = money(p["price_mnt"], lang)
        d.text(((CARD - d.textlength(price, font=f_price)) / 2, 350), price, font=f_price, fill=accent)
        f_facts = _font(False, 30)
        facts = f"{p['area_m2']:g} {'м²' if lang == 'mn' else 'm²'}"
        if p.get("rooms"):
            facts += " · " + UI[lang]["rooms"].format(n=p["rooms"])
        d.text(((CARD - d.textlength(facts, font=f_facts)) / 2, 435), facts, font=f_facts, fill=(60, 60, 60))
        per = per_m2_label(p, lang)
        f_per = _font(True, 30)
        w = d.textlength(per, font=f_per)
        d.rounded_rectangle(((CARD - w) / 2 - 20, 480, (CARD + w) / 2 + 20, 528), radius=24, fill=accent)
        d.text(((CARD - w) / 2, 484), per, font=f_per, fill=(255, 255, 255))
        tag = UI[lang]["sample_image"]
        small = _font(False, 20)
        d.text((CARD - 60 - d.textlength(tag, font=small), CARD - 34), tag, font=small, fill=accent)
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()


def _building(d, kind: str, cx: int, cy: int, color):
    """A simple drawn symbol per property type."""
    white = (255, 255, 255)
    if kind == "apartment":
        d.rectangle((cx - 55, cy - 75, cx + 55, cy + 60), fill=color)
        for row in range(4):
            for col in range(3):
                x, y = cx - 40 + col * 30, cy - 62 + row * 28
                d.rectangle((x, y, x + 18, y + 16), fill=white)
    elif kind == "house":
        d.polygon([(cx - 80, cy - 5), (cx, cy - 75), (cx + 80, cy - 5)], fill=color)
        d.rectangle((cx - 60, cy - 5, cx + 60, cy + 60), fill=color)
        d.rectangle((cx - 15, cy + 15, cx + 15, cy + 60), fill=white)
        d.rectangle((cx - 48, cy + 8, cx - 26, cy + 30), fill=white)
        d.rectangle((cx + 26, cy + 8, cx + 48, cy + 30), fill=white)
    elif kind == "office":
        d.rectangle((cx - 75, cy - 70, cx + 75, cy + 60), fill=color)
        for row in range(3):
            d.rectangle((cx - 62, cy - 58 + row * 36, cx + 62, cy - 34 + row * 36), fill=white)
    else:
        d.rectangle((cx - 85, cy + 30, cx + 85, cy + 60), fill=color)
        d.ellipse((cx - 30, cy - 75, cx + 30, cy - 15), fill=color)
        d.rectangle((cx - 6, cy - 20, cx + 6, cy + 32), fill=color)
        d.line((cx - 85, cy + 30, cx + 85, cy + 30), fill=white, width=3)

