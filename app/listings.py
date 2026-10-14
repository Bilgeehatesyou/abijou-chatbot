"""Property listings for the real-estate demo (data/demo/catalogs/real_estate.json).

Same role as the MCC product catalog (app/catalog.py) and the same interface, so the
demo engine treats both alike: browse by type, search from free text, picture cards
under the answer.

A listing can be for sale, for rent or both, and is available, sold or rented. Asking
about one that is gone shows what replaces it: first similar units in the same building
(other floors, similar size and rooms), then similar ones nearby (neighbourhoods have
real coordinates). When there are none, the customer is asked which area and type they
want and gets the closest matches.

Search understands areas and buildings ("Зайсан", "Ногоон Тал"), types ("байр", "оффис",
"зогсоол"), sale or rent ("түрээс", "rent"), rooms ("3 өрөө"), budgets ("400 сая хүртэл",
"2 сая хүртэл түрээс") and sizes ("80 м2"), in Mongolian, English and Mongolian typed in
Latin letters.
"""
import io
import math
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
    "parking": {"mn": "Зогсоол, гараж", "en": "Parking", "emoji": "🅿️",
                "color": (226, 232, 240), "accent": (71, 85, 105),
                "words": ["зогсоол", "гараж", "parking", "garage", "zogsool", "garaj"]},
    "land": {"mn": "Газар", "en": "Land", "emoji": "🌳",
             "color": (254, 243, 199), "accent": (180, 83, 9),
             "words": ["газар", "хашаа", "land", "plot", "gazar"]},
}
STATUS = {
    "available": {"mn": "✅ Боломжтой", "en": "✅ Available", "ribbon": None},
    "sold": {"mn": "🔴 Зарагдсан", "en": "🔴 Sold", "ribbon": {"mn": "ЗАРАГДСАН", "en": "SOLD"}},
    "rented": {"mn": "🔴 Түрээслэгдсэн", "en": "🔴 Rented out", "ribbon": {"mn": "ТҮРЭЭСЛЭГДСЭН", "en": "RENTED"}},
    "reserved": {"mn": "⏳ Захиалгатай", "en": "⏳ Reserved", "ribbon": {"mn": "ЗАХИАЛГАТАЙ", "en": "RESERVED"}},
}

UI = {
    "mn": {"browse": "🏠 Зарууд", "pick_type": "Ямар төрлийн зар үзэх вэ? Эсвэл бичээд хайгаарай "
                                            "(жишээ нь: «Зайсанд 3 өрөө», «400 сая хүртэл», «түрээсийн байр»).",
           "details": "ℹ Дэлгэрэнгүй", "view": "📅 Үзэх цаг авах", "similar": "🔁 Төстэй зар",
           "rooms": "{n} өрөө", "floor": "{floors}/{floor} давхарт", "storeys": "{floors} давхар",
           "built": "{year} онд ашиглалтад орсон", "sale": "Худалдах", "rent": "Түрээс",
           "per_month": "/сар", "per_m2": "1 м²", "terms": "Нөхцөл",
           "certificate": "📄 Гэрчилгээ бэлэн", "barter": "🔄 Бартер сонсоно",
           "mortgage": "🏦 8%-ийн ипотект хамрагдах боломжтой", "sample": "(Жишээ зар)",
           "sample_image": "Жишээ зураг"},
    "en": {"browse": "🏠 Listings", "pick_type": "Which kind of property would you like to see? Or "
                                               "type to search (e.g. “3-room in Zaisan”, “under 400 million”, "
                                               "“apartment for rent”).",
           "details": "ℹ Details", "view": "📅 Book a viewing", "similar": "🔁 Similar",
           "rooms": "{n} rooms", "floor": "floor {floor} of {floors}", "storeys": "{floors} storeys",
           "built": "built {year}", "sale": "For sale", "rent": "For rent",
           "per_month": "/month", "per_m2": "per m²", "terms": "Terms",
           "certificate": "📄 Certificate ready", "barter": "🔄 Trade-ins considered",
           "mortgage": "🏦 Eligible for the 8% mortgage programme", "sample": "(Sample listing)",
           "sample_image": "Sample image"},
}

NEARBY_KM = 4.0
SAME_BUILDING_SIZE = 0.2        # ±20% floor area counts as "a similar flat"
NEARBY_SIZE = 0.3
RENT_PRICE_LIMIT = 20e6         # a budget below this is a monthly rent, above it a price

# Words that only carry numbers/units or chit-chat; they must not count as matches.
SEARCH_STOPWORDS = {"uruu", "oroo", "room", "rooms", "br", "bedroom", "say", "saya", "terbum",
                    "million", "mln", "billion", "bn", "m2", "mkv", "kv", "sqm", "hurtel",
                    "doosh", "deesh", "under", "below", "over", "above", "up", "to", "max",
                    "min", "zarna", "zarah", "zar", "zaruud", "avmaar", "uzmeer", "uzeh",
                    "bga", "bgaa", "baigaa", "baina", "bna", "bii", "yu", "yuu", "uu", "ve", "hed",
                    "une", "unetei", "m", "in", "with", "near", "there", "any", "an", "are",
                    "what", "which", "show", "me", "want", "looking", "buy", "sale", "for",
                    "hudaldaj", "hudaldah", "hudaldana", "zarag", "darj", "ali", "neg", "ner",
                    "turees", "tureesiin", "tureesleh", "tureeslene", "rent", "rental", "renting",
                    "sar", "saraar", "month", "monthly", "hothon", "hotkhon", "complex", "zarlal",
                    "baraa"}
# Words in building names that say nothing about which building it is.
BUILDING_GENERIC = {"bair", "hothon", "hotkhon", "tsogtsolbor", "complex", "bldg", "horoolol",
                    "horoo", "apartment", "apartments", "tuv", "centre", "center", "area"}
RENT_WORDS = ("turees", "rent", "lease", "saraar", "sar tutam", "per month", "monthly")
SALE_WORDS = ("hudald", "zarna", "zarah", "buy", "purchase", "for sale", "avna", "avmaar")
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


def km(a: dict, b: dict) -> float:
    """Distance between two points with lat/lng, in km."""
    la1, lo1, la2, lo2 = map(math.radians, (a["lat"], a["lng"], b["lat"], b["lng"]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def money(amount: float, lang: str) -> str:
    """865 сая₮ / 1.95 тэрбум₮ / 880 мянга₮ — the way people say prices."""
    if amount >= 1e9:
        value = f"{amount / 1e9:.2f}".rstrip("0").rstrip(".")
        return f"{value} тэрбум₮" if lang == "mn" else f"MNT {value}B"
    if amount >= 1e6:
        value = f"{amount / 1e6:.2f}".rstrip("0").rstrip(".")
        return f"{value} сая₮" if lang == "mn" else f"MNT {value}M"
    value = f"{amount / 1e3:.0f}"
    return f"{value} мянга₮" if lang == "mn" else f"MNT {value}K"


def price_per_m2(p: dict) -> int:
    s = p["offers"].get("sale")
    if not s or not p.get("area_m2") or p["type"] == "parking":   # parking is priced per space
        return 0
    return round(s["price_mnt"] / p["area_m2"])


def per_m2_label(p: dict, lang: str) -> str:
    v = price_per_m2(p)
    if not v:
        return ""
    if v >= 1e6:
        value = f"{v / 1e6:.2f}".rstrip("0").rstrip(".")
        return f"{value} сая₮/м²" if lang == "mn" else f"MNT {value}M/m²"
    return f"{v / 1e3:.0f} мянга₮/м²" if lang == "mn" else f"MNT {v / 1e3:.0f}K/m²"


def available(p: dict) -> bool:
    return p.get("status", "available") == "available"


def floor_label(p: dict, lang: str) -> str:
    u = UI[lang]
    if p.get("floors") and p.get("floor"):
        return u["floor"].format(floors=p["floors"], floor=p["floor"])
    if p.get("floors"):
        return u["storeys"].format(floors=p["floors"])
    return ""


def offer_line(p: dict, lang: str) -> str:
    """865 сая₮ (7.69 сая₮/м²) · 1.8 сая₮/сар"""
    u, parts = UI[lang], []
    s, r = p["offers"].get("sale"), p["offers"].get("rent")
    if s:
        per = per_m2_label(p, lang)
        parts.append(money(s["price_mnt"], lang) + (f" ({per})" if per else ""))
    if r:
        parts.append(money(r["monthly_mnt"], lang) + u["per_month"])
    return " · ".join(parts)


def facts_line(p: dict, lang: str) -> str:
    """112.5 м² · 3 өрөө · 865 сая₮ (7.69 сая₮/м²) — with the status first when it's gone."""
    parts = [] if available(p) else [STATUS[p["status"]][lang]]
    parts.append(f"{p['area_m2']:g} {'м²' if lang == 'mn' else 'm²'}")
    if p.get("rooms"):
        parts.append(UI[lang]["rooms"].format(n=p["rooms"]))
    parts.append(offer_line(p, lang))
    return " · ".join(parts)


ALL_KIND_WORDS = set(tokens(" ".join(w for t in TYPES.values() for w in t["words"] + [t["mn"], t["en"]])))


class Listings:
    kind = "listings"

    def __init__(self, items: list, areas: dict):
        self.products = items                      # name kept so the engine can treat both alike
        self.areas = areas
        self.by_sku = {p["sku"]: p for p in items}
        self._index = []
        for p in items:
            place = set(tokens(" ".join(p[k][lang] for k in ("area_name", "district")
                                        for lang in ("mn", "en"))))
            building = set(tokens(" ".join(p["building"]["name"][lang] for lang in ("mn", "en")))
                           ) if p.get("building") else set()
            kind = set(tokens(" ".join(TYPES[p["type"]]["words"] + [TYPES[p["type"]]["mn"],
                                                                    TYPES[p["type"]]["en"]])))
            title = set(tokens(p["title"]["mn"] + " " + p["title"]["en"]))
            # building names: only the distinctive words ("nogoon", "tal"), not "5-р байр"
            drop = (SEARCH_STOPWORDS | BUILDING_GENERIC | place | ALL_KIND_WORDS
                    | {w for w in building if w[0].isdigit() or len(w) < 3})
            self._index.append((p, place - SEARCH_STOPWORDS, building - drop,
                                kind - SEARCH_STOPWORDS, title - SEARCH_STOPWORDS))

    # ---- browsing ----
    def categories(self) -> list:
        present = {p["type"] for p in self.products if available(p)}
        return [t for t in TYPES if t in present]

    def in_category(self, category: str) -> list:
        return sorted((p for p in self.products if p["type"] == category and available(p)),
                      key=self._sort_price)

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
        if any(w in low for w in RENT_WORDS):
            out["deal"] = "rent"
        elif any(w in low for w in SALE_WORDS):
            out["deal"] = "sale"
        m = ROOMS_RE.search(low)
        if m:
            out["rooms"] = int(m.group(1))
        m = PRICE_RE.search(low)
        if m:
            scale = 1e9 if m.group(2) in ("terbum", "billion", "bn") else 1e6   # "тэрбумаас" too
            out["price"] = _num(m.group(1)) * scale
            out["price_dir"] = ("max" if any(w in low for w in MAX_WORDS)
                                else "min" if any(w in low for w in MIN_WORDS) else "about")
            if out["price"] < RENT_PRICE_LIMIT:          # "2 сая хүртэл" is a monthly rent
                out["deal"] = "rent"
        m = AREA_RE.search(low)
        if m:
            out["area"] = _num(m.group(1))
        m = SKU_RE.search(low)
        if m:
            out["sku"] = f"RE{int(m.group(1)):02d}"
        return out

    @staticmethod
    def _passes(p: dict, f: dict) -> bool:
        offers = p["offers"]
        if f.get("deal") and f["deal"] not in offers:
            return False
        if "rooms" in f and p.get("rooms") != f["rooms"]:
            return False
        if "price" in f:
            deal = f.get("deal") or "sale"   # small budgets were already marked as rent
            if deal not in offers:
                return False
            price = offers[deal]["price_mnt" if deal == "sale" else "monthly_mnt"]
            budget = f["price"]
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
        """Available listings that fit. A sold or rented one comes back only when it was
        named (its building or code), so the engine can say so and offer alternatives."""
        f = self.filters(text)
        if f.get("sku") in self.by_sku:
            return [self.by_sku[f["sku"]]]
        query = [q for q in tokens(text) if q not in SEARCH_STOPWORDS and not q[0].isdigit()]
        has_filters = any(k in f for k in ("rooms", "price", "area", "deal"))
        scored = []
        for p, place, building, kind, title in self._index:
            if not self._passes(p, f):
                continue
            named = [q for q in query if _hit(q, building)]
            in_place = [q for q in query if _hit(q, place) or q in named]
            of_kind = [q for q in query if q not in in_place and _hit(q, kind)]
            score = 3 * len(in_place) + 2 * len(named) + 2 * len(of_kind) + sum(
                1 for q in query if q not in in_place and q not in of_kind and _hit(q, title))
            if not available(p) and not (named or (in_place and of_kind)):
                continue    # gone: only when its building, or its area and kind, was named
            if score or (has_filters and not query):
                scored.append((score, bool(in_place), bool(named), bool(of_kind), p))
        if any(s[3] for s in scored):   # a type was named ("оффис"): only that type
            scored = [s for s in scored if s[3]]
        if any(s[1] for s in scored):   # an area or building was named: only listings there
            scored = [s for s in scored if s[1]]
            if any(available(s[4]) for s in scored):   # something is free there: skip what's gone,
                scored = [s for s in scored if available(s[4]) or s[2]]   # unless named by building
        scored = [(score, p) for score, *_, p in scored]
        if not scored and has_filters and query:
            # e.g. "3 өрөө Гачуурт" with nothing in Gachuurt: offer what fits the numbers
            scored = [(0, p) for p, *_ in self._index if available(p) and self._passes(p, f)]
        scored.sort(key=lambda s: (-s[0], not available(s[1]), self._sort_price(s[1])))
        return [p for _, p in scored[:limit]]

    @staticmethod
    def _sort_price(p: dict) -> float:
        o = p["offers"]
        return o["sale"]["price_mnt"] if "sale" in o else o["rent"]["monthly_mnt"] * 150

    # ---- when a listing is gone ----
    def alternatives(self, p: dict, limit: int = 5) -> list:
        """[(listing, "same_building" | "nearby", km)] for a sold or rented listing:
        similar units in the same building first, then similar ones nearby."""
        deals = set(p["offers"])
        pool = [q for q in self.products if q is not p and available(q) and q["type"] == p["type"]
                and deals & set(q["offers"])]

        def similar(q, spread):
            same_size = abs(q["area_m2"] - p["area_m2"]) <= p["area_m2"] * spread
            rooms_ok = not p.get("rooms") or abs((q.get("rooms") or 0) - p["rooms"]) <= 1
            return same_size and rooms_ok

        bid = (p.get("building") or {}).get("id")
        same = [q for q in pool if bid and (q.get("building") or {}).get("id") == bid
                and similar(q, SAME_BUILDING_SIZE)]
        same.sort(key=lambda q: abs(q["area_m2"] - p["area_m2"]))
        near = [(q, km(p, q)) for q in pool if q not in same and similar(q, NEARBY_SIZE)]
        near = sorted((x for x in near if x[1] <= NEARBY_KM), key=lambda x: x[1])
        return ([(q, "same_building", 0.0) for q in same] + [(q, "nearby", d) for q, d in near])[:limit]

    def area_choices(self) -> list:
        """Areas that have something available, west to east (for the "which area?" buttons)."""
        have = {p["area_id"] for p in self.products if available(p)}
        return sorted((a for a in self.areas if a in have), key=lambda a: self.areas[a]["lng"])

    def area_label(self, area_id: str, lang: str) -> str:
        return self.areas[area_id]["name"][lang]

    def recommend(self, area_id: str, category: str = "", limit: int = 6) -> list:
        """Available listings of a type, closest to an area first."""
        centre = self.areas[area_id]
        pool = [p for p in self.products if available(p) and (not category or p["type"] == category)]
        return sorted(pool, key=lambda p: km(centre, p))[:limit]

    def distance_from(self, area_id: str, p: dict) -> float:
        return km(self.areas[area_id], p)

    # ---- presentation ----
    def card(self, p: dict, lang: str, image_url: str) -> Card:
        u = UI[lang]
        second = (QuickReply(u["view"], f"VIEW_{p['sku']}") if available(p)
                  else QuickReply(u["similar"], f"SIMILAR_{p['sku']}"))
        return Card(title=p["title"][lang], subtitle=facts_line(p, lang)[:80], image_url=image_url,
                    buttons=[QuickReply(u["details"], f"INFO_{p['sku']}"), second])

    def details(self, p: dict, lang: str) -> str:
        u = UI[lang]
        lines = [f"{TYPES[p['type']]['emoji']} {p['title'][lang]} ({p['sku']}) · {STATUS[p['status']][lang]}",
                 f"📍 {p['address'][lang]}"]
        facts = [f"{p['area_m2']:g} {'м²' if lang == 'mn' else 'm²'}"]
        if p.get("rooms"):
            facts.append(u["rooms"].format(n=p["rooms"]))
        if floor_label(p, lang):
            facts.append(floor_label(p, lang))
        if p.get("year"):
            facts.append(u["built"].format(year=p["year"]))
        lines.append("📐 " + " · ".join(facts))
        if p.get("windows"):
            lines.append(f"🪟 {p['windows'][lang]}")
        s, r = p["offers"].get("sale"), p["offers"].get("rent")
        if s:
            per = f" ({u['per_m2']} {price_per_m2(p):,}₮)" if price_per_m2(p) else ""
            lines.append(f"💰 {u['sale']}: {s['price_mnt']:,}₮{per} · {u['terms']}: {s['terms'][lang]}")
        if r:
            per = f" ({u['per_m2']} {r['per_m2_monthly']:,}₮{u['per_month']})" if r.get("per_m2_monthly") else ""
            lines.append(f"🔑 {u['rent']}: {r['monthly_mnt']:,}₮{u['per_month']}{per} · {u['terms']}: {r['terms'][lang]}")
        flags = [u[k] for k in ("certificate", "barter") if p.get(k)]
        if flags:
            lines.append(" · ".join(flags))
        if p.get("mortgage"):
            lines.append(u["mortgage"])
        lines += [f"✨ {p['features'][lang]}", u["sample"]]
        return "\n".join(lines)

    def booking_item(self, p: dict) -> dict:
        """What the booking flow needs to know about the property being viewed."""
        return {"id": p["sku"], "title": p["title"], "short": p["short"], "address": p["address"]}

    def prompt_context(self, matches: list, lang: str) -> str:
        """Every listing goes to the LLM (there are few), so it can compare, filter and,
        for one that is gone, name the same alternatives the cards show."""
        lines = []
        for p in self.products:
            s, r = p["offers"].get("sale"), p["offers"].get("rent")
            parts = [p["sku"], p["status"].upper(), TYPES[p["type"]]["en"], p["title"][lang],
                     p["address"][lang], f"{p['area_m2']:g} m²",
                     UI["en"]["rooms"].format(n=p["rooms"]) if p.get("rooms") else "",
                     floor_label(p, "en"), UI["en"]["built"].format(year=p["year"]) if p.get("year") else "",
                     f"windows: {p['windows']['en']}" if p.get("windows") else ""]
            if s:
                parts.append(f"FOR SALE {s['price_mnt']:,} MNT ({price_per_m2(p):,} MNT per m²), "
                             f"terms: {s['terms'][lang]}")
            if r:
                per = f" ({r['per_m2_monthly']:,} MNT per m² a month)" if r.get("per_m2_monthly") else ""
                parts.append(f"FOR RENT {r['monthly_mnt']:,} MNT a month{per}, terms: {r['terms'][lang]}")
            parts += ["certificate ready" if p.get("certificate") else "",
                      "trade-ins considered" if p.get("barter") else "",
                      "8% mortgage eligible" if p.get("mortgage") else "", p["features"][lang]]
            if not available(p):
                alts = self.alternatives(p)
                parts.append("ALTERNATIVES: " + (", ".join(
                    f"{q['sku']} (same building, {floor_label(q, 'en')})" if why == "same_building"
                    else f"{q['sku']} ({d:.1f} km away)" for q, why, d in alts)
                    or "none — ask which area and type they want"))
            lines.append(" | ".join(x for x in parts if x))
        shown = ", ".join(p["sku"] for p in matches) or "none"
        return (
            f"\n\nPROPERTY LISTINGS ({len(self.products)}; fictional demo data; prices in MNT, "
            "price per m² = price / area; floors are written building/unit as in Mongolia, "
            "e.g. 12/10 = 10th floor of 12):\n" + "\n".join(lines) +
            f"\n\nListings shown as picture cards under your reply: {shown}.\n"
            "- Quote prices, sizes and terms exactly from this list. A listing can be for sale, "
            "for rent or both: mention every option it has.\n"
            "- Always say whether a listing is AVAILABLE, SOLD or RENTED. If the one asked about "
            "is sold or rented, say so first, then offer its ALTERNATIVES (same building first, "
            "then nearby). If it has none, ask which area and what type of property they want.\n"
            "- Never offer a viewing of a sold or rented listing. Mention at most 3 listings by name."
        )

    # ---- picture card ----
    def render(self, p: dict, lang: str = "mn") -> bytes:
        from PIL import Image, ImageDraw
        t = TYPES[p["type"]]
        bg, accent = t["color"], t["accent"]
        gone = not available(p)
        if gone:
            accent = (120, 120, 120)
        img = Image.new("RGB", (CARD, CARD), bg)
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((40, 40, 560, 560), radius=36, fill=(255, 255, 255), outline=accent, width=6)
        d.rounded_rectangle((43, 43, 557, 120), radius=33, fill=accent, corners=(True, True, False, False))
        band = f"{t[lang].upper()} · {p['sku']}"
        f_band = _font(True, 34)
        d.text(((CARD - d.textlength(band, font=f_band)) / 2, 60), band, font=f_band, fill=(255, 255, 255))
        _building(d, p["type"], CARD // 2, 205, accent)
        f_place = _font(True, 32)
        for line in _wrap(d, p["area_name"][lang] + ", " + p["district"][lang], f_place, 470, 1):
            d.text(((CARD - d.textlength(line, font=f_place)) / 2, 290), line, font=f_place, fill=(40, 40, 40))
        s, r = p["offers"].get("sale"), p["offers"].get("rent")
        price = money(s["price_mnt"], lang) if s else money(r["monthly_mnt"], lang) + UI[lang]["per_month"]
        f_price = _font(True, 54 if s else 46)
        d.text(((CARD - d.textlength(price, font=f_price)) / 2, 338), price, font=f_price, fill=accent)
        f_facts = _font(False, 28)
        facts = f"{p['area_m2']:g} {'м²' if lang == 'mn' else 'm²'}"
        if p.get("rooms"):
            facts += " · " + UI[lang]["rooms"].format(n=p["rooms"])
        if floor_label(p, lang):
            facts += " · " + floor_label(p, lang)
        d.text(((CARD - d.textlength(facts, font=f_facts)) / 2, 418), facts, font=f_facts, fill=(60, 60, 60))
        badge = (per_m2_label(p, lang) or UI[lang]["sale"]) if s else UI[lang]["rent"]
        if s and r:
            badge += f" · {UI[lang]['rent'].lower()} {money(r['monthly_mnt'], lang)}"
        f_badge = _font(True, 26)
        w = d.textlength(badge, font=f_badge)
        d.rounded_rectangle(((CARD - w) / 2 - 18, 470, (CARD + w) / 2 + 18, 514), radius=22, fill=accent)
        d.text(((CARD - w) / 2, 474), badge, font=f_badge, fill=(255, 255, 255))
        if gone:   # a diagonal ribbon across the card
            ribbon = STATUS[p["status"]]["ribbon"][lang]
            layer = Image.new("RGBA", (CARD, CARD), (0, 0, 0, 0))
            ld = ImageDraw.Draw(layer)
            ld.rectangle((-100, 255, CARD + 100, 335), fill=(220, 38, 38, 235))
            f_r = _font(True, 44)
            ld.text(((CARD - ld.textlength(ribbon, font=f_r)) / 2, 268), ribbon, font=f_r, fill=(255, 255, 255))
            img = Image.alpha_composite(img.convert("RGBA"),
                                        layer.rotate(18, center=(CARD / 2, CARD / 2))).convert("RGB")
            d = ImageDraw.Draw(img)
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
    elif kind == "parking":
        d.rounded_rectangle((cx - 60, cy - 70, cx + 60, cy + 60), radius=20, fill=color)
        f = _font(True, 110)
        d.text((cx - d.textlength("P", font=f) / 2, cy - 78), "P", font=f, fill=white)
    else:
        d.rectangle((cx - 85, cy + 30, cx + 85, cy + 60), fill=color)
        d.ellipse((cx - 30, cy - 75, cx + 30, cy - 15), fill=color)
        d.rectangle((cx - 6, cy - 20, cx + 6, cy + 32), fill=color)
        d.line((cx - 85, cy + 30, cx + 85, cy + 30), fill=white, width=3)
