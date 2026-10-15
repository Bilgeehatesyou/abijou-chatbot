"""Property listings for the real-estate demo (data/demo/catalogs/real_estate.json).

Same role as the MCC product catalog (app/catalog.py) and the same interface, so the
demo engine treats both alike: browse by type, search from free text, picture cards
under the answer.

A listing can be for sale, for rent or both, and is available, sold or rented. Asking
about one that is gone shows what replaces it, in this order: the same type (same rooms,
similar size) on another floor of the same building; the same type in another block of
the same complex ("хотхон"); something similar nearby (neighbourhoods have real
coordinates). When there is none, the customer is asked where and what type they want
and gets the closest matches.

People name a unit the way agents write it: "Гэрлүг Виста 40-р байр 9 давхар 3 өрөө",
"hunnu 2222 2r eelj 5r bair 12 dawhar". Block, floor and phase ("ээлж") pick out that exact
unit; when no such unit exists, find() says so and returns the closest available ones
(same complex, same rooms, nearest block and floor).

Search understands complexes ("Гэрлүг Виста", "Хүннү"), types ("байр", "зогсоол", "гараж"),
sale or rent ("түрээс", "rent"), rooms ("3 өрөө"), budgets ("700 сая хүртэл", "3 сая хүртэл
түрээс"), sizes ("80 м2") and how the buyer pays ("зээлээр", "бартер"), in Mongolian,
English and Mongolian typed in Latin letters.
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
                "words": ["зогсоол", "гараж", "гарааш", "parking", "garage", "zogsool", "garaj",
                          "garaash"]},
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
                                            "(жишээ нь: «Гэрлүг Вистад 3 өрөө», «700 сая хүртэл», "
                                            "«Хүннү 2222 түрээс»).",
           "details": "ℹ Дэлгэрэнгүй", "view": "📅 Үзэх цаг авах", "similar": "🔁 Төстэй зар",
           "rooms": "{n} өрөө", "floor": "{floors}/{floor} давхарт", "storeys": "{floors} давхар",
           "built": "{year} онд ашиглалтад орсон", "sale": "Худалдах", "rent": "Түрээс",
           "per_month": "/сар", "per_m2": "1 м²", "terms": "Нөхцөл",
           "certificate": "📄 Гэрчилгээ бэлэн", "no_certificate": "📄 Гэрчилгээ гараагүй (зээл хараахан боломжгүй)",
           "barter": "🔄 Бартер сонсоно", "barter_with": "🔄 Бартер: {what}",
           "mortgage": "🏦 8%-ийн ипотект хамрагдах боломжтой", "sample": "(Жишээ зар)",
           "sample_image": "Жишээ зураг", "block": "{n}-р байр", "condition": "🛠",
           "pay": {"cash": "бэлэн", "loan": "банкны зээл", "mortgage": "8%-ийн ипотек", "barter": "бартер"},
           "unit_parking": "зогсоол, гараж", "unit_flat": "байр", "unit_rooms": "{n} өрөө",
           "unit_floor": "{n} давхарт"},
    "en": {"browse": "🏠 Listings", "pick_type": "Which kind of property would you like to see? Or "
                                               "type to search (e.g. “3-room in Gerlug Vista”, “under "
                                               "700 million”, “Hunnu 2222 for rent”).",
           "details": "ℹ Details", "view": "📅 Book a viewing", "similar": "🔁 Similar",
           "rooms": "{n} rooms", "floor": "floor {floor} of {floors}", "storeys": "{floors} storeys",
           "built": "built {year}", "sale": "For sale", "rent": "For rent",
           "per_month": "/month", "per_m2": "per m²", "terms": "Terms",
           "certificate": "📄 Certificate ready", "no_certificate": "📄 Certificate not issued yet (no bank loan yet)",
           "barter": "🔄 Trade-ins considered", "barter_with": "🔄 Trade-in: {what}",
           "mortgage": "🏦 Eligible for the 8% mortgage programme", "sample": "(Sample listing)",
           "sample_image": "Sample image", "block": "bldg {n}", "condition": "🛠",
           "pay": {"cash": "cash", "loan": "bank loan", "mortgage": "8% mortgage", "barter": "trade-in"},
           "unit_parking": "parking or garage", "unit_flat": "flat", "unit_rooms": "{n}-room",
           "unit_floor": "on floor {n}"},
}

NEARBY_KM = 4.0
SAME_BUILDING_SIZE = 0.2        # ±20% floor area counts as "the same type" of flat
SAME_COMPLEX_SIZE = 0.25
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
                    "baraa", "yamar", "ene", "this", "it", "tanai", "manai", "ted", "teruu",
                    "eelj", "eeljiin", "eeljind", "plas", "plus", "phase", "davhar", "davhart",
                    "dawhar", "dawhart", "davhriin", "floor"}
# Words in building names that say nothing about which building it is.
BUILDING_GENERIC = {"bair", "hothon", "hotkhon", "tsogtsolbor", "complex", "bldg", "horoolol",
                    "horoo", "apartment", "apartments", "tuv", "centre", "center", "area"}
RENT_WORDS = ("turees", "rent", "lease", "saraar", "sar tutam", "per month", "monthly")
SALE_WORDS = ("hudald", "zarna", "zarah", "buy", "purchase", "for sale", "avna", "avmaar")
ROOMS_RE = re.compile(r"(\d)\s*\+?\s*-?\s*(?:uruu|oroo|room|bedroom|br|bed)")
PRICE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(saya|say|million|mln|terbum|billion|bn)")
AREA_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:m2|m²|mkv|kvm|kv\.?m|sqm|kv)\b")
SKU_RE = re.compile(r"\b(gv|hn)\s*-?\s*(\d{1,3})\b")
# "3-р байр", "40r bair", "5-р блок" / "7 давхар", "2 dawhar", "7-р давхарт" / "2-р ээлж"
BLOCK_RE = re.compile(r"(\d+)\s*-?\s*(?:r\s*)?(?:bair|blok|block|bldg|building)")
FLOOR_RE = re.compile(r"(\d+)\s*-?\s*(?:r\s*)?(?:davh|dawh|floor)")
PHASE_RE = re.compile(r"(\d)\s*-?\s*(?:r\s*)?(?:eelj|phase)|\b(plas|plus)\b")
# how the buyer pays: "зээлээр", "ипотек", "бартер", "бэлнээр"
PAY_WORDS = {"barter": ("barter", "trade-in", "trade in", "solih", "solino"),
             "mortgage": ("8 huv", "8%", "8 %"),
             "loan": ("zeel", "ipotek", "mortgage", "loan", "bank")}
MAX_WORDS = ("hurtel", "doosh", "baga", "under", "below", "up to", "max", "less", "within")
MIN_WORDS = ("deesh", "iluu", "over", "above", "more than", "from", "at least")


def _hit(q: str, words: set) -> bool:
    """Exact, or the word plus a Mongolian case ending: «Хүннүд», «Вистад», «байраа»."""
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

    def __init__(self, items: list, areas: dict, complexes: dict = None):
        self.products = items                      # name kept so the engine can treat both alike
        self.areas = areas
        self.complexes = complexes or {}
        self.by_sku = {p["sku"]: p for p in items}
        # words that name a complex ("gerlug", "vista", "hunnu") and which complex a block is in
        self._complex_words = {cid: set(c.get("words") or tokens(c["name"]["mn"] + " " + c["name"]["en"]))
                               - BUILDING_GENERIC for cid, c in self.complexes.items()}
        self._block_complex = {p["block"]: self._complex(p) for p in items if p.get("block")}
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
            out["sku"] = f"{m.group(1).upper()}{int(m.group(2)):02d}"
        m = BLOCK_RE.search(low)
        if m and int(m.group(1)) < 1000:          # "Хүннү 2222 байр" names the complex, not a block
            out["block"] = int(m.group(1))
        m = FLOOR_RE.search(low)
        if m:
            out["floor"] = int(m.group(1))
        m = PHASE_RE.search(low)
        if m:
            out["phase"] = int(m.group(1)) if m.group(1) else "plus"
        for pay, words in PAY_WORDS.items():
            if any(w in low for w in words):
                out["pay"] = pay
                break
        return out

    @staticmethod
    def _block(p: dict) -> int:
        if p.get("block"):
            return p["block"]
        m = re.search(r"(\d+)-р байр", ((p.get("building") or {}).get("name") or {}).get("mn", ""))
        return int(m.group(1)) if m else 0

    @staticmethod
    def _complex(p: dict) -> str:
        return ((p.get("building") or {}).get("complex") or {}).get("id", "")

    @staticmethod
    def _passes(p: dict, f: dict) -> bool:
        offers = p["offers"]
        if f.get("deal") and f["deal"] not in offers:
            return False
        if "rooms" in f and p.get("rooms") != f["rooms"]:
            return False
        if "phase" in f and p.get("phase") != f["phase"]:
            return False
        if f.get("pay") and f.get("deal") != "rent" and ("sale" not in offers
                                                         or f["pay"] not in p.get("pay", [])):
            return False                       # paying by loan or trade-in means buying
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
        return self.find(text, limit)[0]

    def find(self, text: str, limit: int = 10):
        """(listings, missing). Available listings that fit; a sold or rented one comes back
        only when it was named (its unit or code), so the engine can say so and offer
        alternatives. When the customer names a unit or a kind of flat that isn't in the
        database ("Хүннү 2222 6 өрөө", "40-р байр 20 давхар"), missing describes it
        ({"mn", "en"}) and the listings are the closest available ones instead."""
        f = self.filters(text)
        if f.get("sku"):
            if f["sku"] in self.by_sku:
                return [self.by_sku[f["sku"]]], None
            return [], {"mn": f"{f['sku']} кодтой зар", "en": f"listing {f['sku']}"}
        query = [q for q in tokens(text) if q not in SEARCH_STOPWORDS and not q[0].isdigit()]
        cx = self._named_complex(query) or self._block_complex.get(f.get("block"), "")
        kind = self._named_kind(query)
        if f.get("block") or f.get("floor") or f.get("phase"):
            # a unit named the way agents write it: "40-р байр 9 давхар 3 өрөө", "2-р ээлж"
            unit_kind = kind or "apartment"
            exact = [p for p in self.products if p["type"] == unit_kind and self._passes(p, f)
                     and (not cx or self._complex(p) == cx)
                     and (not f.get("block") or self._block(p) == f["block"])
                     and (not f.get("floor") or p.get("floor") == f["floor"])]
            if not exact:
                return self._similar(f, cx, unit_kind, limit), self._describe(f, cx, unit_kind)
            if not (f.get("block") and f.get("floor")) and any(available(p) for p in exact):
                exact = [p for p in exact if available(p)]     # a whole block or phase: what's free
            exact.sort(key=lambda p: (not available(p), p.get("floor") or 0, self._sort_price(p)))
            return exact[:limit], None
        found = self._search(text, f, query, limit)
        if not found and cx and (kind or any(k in f for k in ("rooms", "price", "area", "deal"))):
            unit_kind = kind or "apartment"             # "Хүннү 2222 6 өрөө": none like it there
            return self._similar(f, cx, unit_kind, limit), self._describe(f, cx, unit_kind)
        return found, None

    def _named_complex(self, query: list) -> str:
        for cid, words in self._complex_words.items():
            if any(_hit(q, words) for q in query):
                return cid
        return ""

    @staticmethod
    def _named_kind(query: list) -> str:
        for kind in ("parking", "office", "house", "land", "apartment"):   # most specific first
            words = set(tokens(" ".join(TYPES[kind]["words"])))
            if any(_hit(q, words) for q in query):
                return kind
        return ""

    def _similar(self, f: dict, cx: str, kind: str, limit: int) -> list:
        """The closest available listings to a unit that doesn't exist: the same complex if it
        has any, then the nearest room count, the same block or phase, the nearest floor."""
        pool = [p for p in self.products if available(p) and p["type"] == kind
                and (not f.get("deal") or f["deal"] in p["offers"])]
        if cx and any(self._complex(p) == cx for p in pool):
            pool = [p for p in pool if self._complex(p) == cx]
        if f.get("pay") and any(self._passes(p, {"pay": f["pay"]}) for p in pool):
            pool = [p for p in pool if self._passes(p, {"pay": f["pay"]})]
        key = lambda p: (abs((p.get("rooms") or 0) - f["rooms"]) if "rooms" in f else 0,
                         bool(f.get("block")) and self._block(p) != f["block"],
                         bool(f.get("phase")) and p.get("phase") != f["phase"],
                         abs((p.get("floor") or 0) - f["floor"]) if f.get("floor") else 0,
                         self._sort_price(p))
        return sorted(pool, key=key)[:min(limit, 5)]

    def _describe(self, f: dict, cx: str, kind: str) -> dict:
        """«Гэрлүг Виста хотхон, 40-р байр, 20 давхарт 3 өрөө байр» — what was asked for."""
        out = {}
        for lang in ("mn", "en"):
            u = UI[lang]
            where = [self.complexes[cx]["name"][lang]] if cx in self.complexes else []
            if f.get("phase"):
                where.append(("Плас" if lang == "mn" else "Plus") if f["phase"] == "plus"
                             else (f"{f['phase']}-р ээлж" if lang == "mn" else f"phase {f['phase']}"))
            if f.get("block"):
                where.append(u["block"].format(n=f["block"]))
            what = [u["unit_floor"].format(n=f["floor"])] if f.get("floor") else []
            if "rooms" in f:
                what.append(u["unit_rooms"].format(n=f["rooms"]))
            what.append(u["unit_parking"] if kind == "parking" else u["unit_flat"])
            if lang == "mn":
                out[lang] = ", ".join(where + [" ".join(what)])
            else:
                flat = " ".join(what[1:] + what[:1]) if f.get("floor") else " ".join(what)
                out[lang] = "a " + flat + (" in " + ", ".join(where) if where else "")
        return out

    def _search(self, text: str, f: dict, query: list, limit: int) -> list:
        has_filters = any(k in f for k in ("rooms", "price", "area", "deal"))
        scored, matched_words = [], set()
        for p, place, building, kind, title in self._index:
            if not self._passes(p, f):
                continue
            named = [q for q in query if _hit(q, building)]
            in_place = [q for q in query if _hit(q, place) or q in named]
            of_kind = [q for q in query if q not in in_place and _hit(q, kind)]
            score = 3 * len(in_place) + 2 * len(named) + 2 * len(of_kind) + sum(
                1 for q in query if q not in in_place and q not in of_kind and _hit(q, title))
            if not available(p) and not (named or (in_place and (of_kind or has_filters))):
                continue    # gone: only when its building, or its area plus kind/rooms/price, was named
            if score or (has_filters and not query):
                scored.append((score, bool(in_place), bool(named), bool(of_kind), p))
                matched_words.update(in_place + named + of_kind)
        only_kind = scored and not has_filters and not any(s[1] or s[2] for s in scored)
        if only_kind and [q for q in query if q not in matched_words]:
            return []   # "байр ипотекоор авч болох уу?" is a question, not a request for listings
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
        scored.sort(key=lambda s: (-s[0], not available(s[1]), s[1]["type"] != "apartment",
                                   self._sort_price(s[1])))
        return [p for _, p in scored[:limit]]

    @staticmethod
    def _sort_price(p: dict) -> float:
        o = p["offers"]
        return o["sale"]["price_mnt"] if "sale" in o else o["rent"]["monthly_mnt"] * 150

    # ---- when a listing is gone ----
    def alternatives(self, p: dict, limit: int = 5) -> list:
        """[(listing, why, km)] for a sold or rented listing, best first:
        "same_building" — the same type on another floor of its building,
        "same_complex"  — the same type in another block of its complex,
        "nearby"        — something similar within NEARBY_KM."""
        deals = set(p["offers"])
        pool = [q for q in self.products if q is not p and available(q) and q["type"] == p["type"]
                and deals & set(q["offers"])]

        def same_type(q, spread, rooms_slack=0):
            size_ok = abs(q["area_m2"] - p["area_m2"]) <= p["area_m2"] * spread
            rooms_ok = not p.get("rooms") or abs((q.get("rooms") or 0) - p["rooms"]) <= rooms_slack
            return size_ok and rooms_ok

        def ids(q):
            b = q.get("building") or {}
            return b.get("id"), (b.get("complex") or {}).get("id")

        bid, cid = ids(p)
        by_size = lambda q: abs(q["area_m2"] - p["area_m2"])
        same = sorted((q for q in pool if bid and ids(q)[0] == bid and same_type(q, SAME_BUILDING_SIZE)),
                      key=by_size)
        block = sorted((q for q in pool if cid and ids(q)[1] == cid and ids(q)[0] != bid
                        and same_type(q, SAME_COMPLEX_SIZE)), key=by_size)
        taken = {q["sku"] for q in same + block}
        near = sorted(((q, km(p, q)) for q in pool if q["sku"] not in taken
                       and same_type(q, NEARBY_SIZE, rooms_slack=1)), key=lambda x: x[1])
        return ([(q, "same_building", 0.0) for q in same] + [(q, "same_complex", km(p, q)) for q in block]
                + [(q, "nearby", d) for q, d in near if d <= NEARBY_KM])[:limit]

    # ---- "what do you want?": rooms, complex, how you pay ----
    def complex_choices(self) -> list:
        """[(id, {"mn", "en"} short name)] of complexes with something available."""
        have = {self._complex(p) for p in self.products if available(p)}
        return [(cid, c.get("short") or c["name"]) for cid, c in self.complexes.items() if cid in have]

    def want(self, rooms: str, complex_id: str = "any", pay: str = "any", limit: int = 10):
        """(listings, exact) for the preference questions. rooms: "2".."5" ("5" means 5 or
        more) or "parking". With nothing that fits every answer, the payment and then the
        complex are let go, and exact is False."""
        def fits(p, use_complex, use_pay):
            if not available(p) or "sale" not in p["offers"]:       # these questions are for buyers
                return False
            if rooms == "parking":
                if p["type"] != "parking":
                    return False
            elif p["type"] != "apartment" or not (
                    (p.get("rooms") or 0) >= 5 if rooms == "5" else p.get("rooms") == int(rooms)):
                return False
            if use_complex and complex_id != "any" and self._complex(p) != complex_id:
                return False
            if use_pay and pay not in ("any", "cash") and pay not in p.get("pay", []):
                return False
            return True
        for use_complex, use_pay in ((True, True), (True, False), (False, False)):
            found = sorted((p for p in self.products if fits(p, use_complex, use_pay)), key=self._sort_price)
            if found:
                return found[:limit], (use_complex and use_pay)
        return [], False

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
        if p.get("condition"):
            lines.append(f"{u['condition']} {p['condition'][lang]}")
        if p.get("windows"):
            lines.append(f"🪟 {p['windows'][lang]}")
        s, r = p["offers"].get("sale"), p["offers"].get("rent")
        if s:
            per = f" ({u['per_m2']} {price_per_m2(p):,}₮)" if price_per_m2(p) else ""
            lines.append(f"💰 {u['sale']}: {s['price_mnt']:,}₮{per} · {u['terms']}: {s['terms'][lang]}")
        if r:
            per = f" ({u['per_m2']} {r['per_m2_monthly']:,}₮{u['per_month']})" if r.get("per_m2_monthly") else ""
            lines.append(f"🔑 {u['rent']}: {r['monthly_mnt']:,}₮{u['per_month']}{per} · {u['terms']}: {r['terms'][lang]}")
        flags = [u["certificate"]] if p.get("certificate") else (
            [u["no_certificate"]] if p.get("certificate") is False and s and p["type"] == "apartment" else [])
        if p.get("barter"):
            flags.append(u["barter_with"].format(what=p["barter_with"][lang]) if p.get("barter_with")
                         else u["barter"])
        if flags:
            lines.append(" · ".join(flags))
        if p.get("mortgage"):
            lines.append(u["mortgage"])
        lines += [f"✨ {p['features'][lang]}", u["sample"]]
        return "\n".join(lines)

    def booking_item(self, p: dict) -> dict:
        """What the booking flow needs to know about the property being viewed."""
        return {"id": p["sku"], "title": p["title"], "short": p["short"], "address": p["address"]}

    def _index_line(self, p: dict) -> str:
        """GV01 SOLD | Gerlug Vista bldg 40 16/9 | 3 rooms 78.03 m² | sale 655M (8.39M/m²) cash,loan"""
        s, r = p["offers"].get("sale"), p["offers"].get("rent")
        where = (p.get("building") or {}).get("name", {}).get("en", p["area_name"]["en"])
        if p.get("floors") and p.get("floor"):
            where += f" {p['floors']}/{p['floor']}"
        what = (f"{p['rooms']} rooms " if p.get("rooms") else TYPES[p["type"]]["en"].lower() + " ") + \
            f"{p['area_m2']:g} m²"
        deal = []
        if s:
            deal.append(f"sale {s['price_mnt'] / 1e6:g}M ({price_per_m2(p) / 1e6:.2f}M/m²) "
                        + ",".join(p.get("pay") or []) if price_per_m2(p) else f"sale {s['price_mnt'] / 1e6:g}M")
        if r:
            deal.append(f"rent {r['monthly_mnt'] / 1e6:g}M/month")
        return " | ".join([f"{p['sku']} {p['status'].upper()}", where, what, "; ".join(deal)])

    def _summary(self) -> str:
        """Per complex: blocks, and what is available by room count with the price range."""
        out = []
        for cid, c in self.complexes.items():
            mine = [p for p in self.products if self._complex(p) == cid]
            blocks = sorted({(self._block(p), p.get("floors") or 0, p.get("year") or 0, str(p.get("phase") or ""))
                             for p in mine if p["type"] == "apartment"})
            out.append(f"{c['name']['en']} ({c['about']['en']}). Blocks: " + ", ".join(
                f"{b} ({'phase ' + ph + ', ' if ph else ''}{fl} storeys, {y})" for b, fl, y, ph in blocks))
            groups = {}
            for p in mine:
                if available(p) and "sale" in p["offers"]:
                    key = f"{p['rooms']}-room" if p["type"] == "apartment" else "parking/garage"
                    groups.setdefault(key, []).append(p["offers"]["sale"]["price_mnt"])
            out.append("  available for sale: " + "; ".join(
                f"{k} ×{len(v)} {min(v) / 1e6:g}–{max(v) / 1e6:g}M" for k, v in sorted(groups.items())))
        return "\n".join(out)

    def prompt_context(self, matches: list, lang: str, missing: dict = None, focus: dict = None) -> str:
        """A one-line index of every listing, plus full details of the ones that matter now
        (the cards under the reply and their alternatives), so the LLM can compare and
        filter without a 30 KB prompt."""
        detailed = list(matches) + ([focus] if focus and focus not in matches else [])
        for p in list(detailed):
            if not available(p):
                detailed += [q for q, _, _ in self.alternatives(p) if q not in detailed]
        lines = []
        for p in detailed:
            s, r = p["offers"].get("sale"), p["offers"].get("rent")
            parts = [p["sku"], p["status"].upper(), TYPES[p["type"]]["en"], p["title"][lang],
                     p["address"][lang], f"{p['area_m2']:g} m²",
                     UI["en"]["rooms"].format(n=p["rooms"]) if p.get("rooms") else "",
                     floor_label(p, "en"), UI["en"]["built"].format(year=p["year"]) if p.get("year") else "",
                     f"windows: {p['windows']['en']}" if p.get("windows") else "",
                     f"condition: {p['condition']['en']}" if p.get("condition") else ""]
            if s:
                parts.append(f"FOR SALE {s['price_mnt']:,} MNT ({price_per_m2(p):,} MNT per m²), "
                             f"terms: {s['terms'][lang]}")
            if r:
                per = f" ({r['per_m2_monthly']:,} MNT per m² a month)" if r.get("per_m2_monthly") else ""
                parts.append(f"FOR RENT {r['monthly_mnt']:,} MNT a month{per}, terms: {r['terms'][lang]}")
            parts += ["certificate ready" if p.get("certificate") else
                      "certificate not issued yet, so no bank loan yet" if p.get("certificate") is False else "",
                      (f"trade-in considered ({p['barter_with']['en']})" if p.get("barter_with")
                       else "trade-ins considered") if p.get("barter") else "",
                      "8% mortgage eligible" if p.get("mortgage") else "", p["features"][lang]]
            if not available(p):
                alts = self.alternatives(p)
                parts.append("ALTERNATIVES: " + (", ".join(
                    f"{q['sku']} (same building, {floor_label(q, 'en')})" if why == "same_building"
                    else f"{q['sku']} (same complex, {q['building']['name']['en']}, {floor_label(q, 'en')})"
                    if why == "same_complex" else f"{q['sku']} ({d:.1f} km away)" for q, why, d in alts)
                    or "none — ask where and what type of property they want"))
            lines.append(" | ".join(x for x in parts if x))
        shown = ", ".join(p["sku"] for p in matches) or "none"
        names = " and ".join(c["name"]["en"] for c in self.complexes.values())
        not_found = ""
        if missing:
            not_found = (f"\nNOT FOUND: the customer asked about {missing['en']}, which is not in the "
                         "database (the chat has already told them so; don't repeat it). The cards "
                         "are the closest available options: introduce them briefly.\n")
        return (
            f"\n\nPROPERTY DATABASE: {len(self.products)} listings, all in {names} (fictional "
            "demo units; prices in MNT, price per m² = price / area; floors are written "
            "storeys/unit as in Mongolia, e.g. 16/9 = 9th floor of a 16-storey block; pay = how "
            "a buyer can pay: cash, loan = bank loan, mortgage = the 8% mortgage programme, "
            "barter = trade-in).\n" + self._summary() +
            "\n\nEVERY LISTING (one line each):\n" + "\n".join(self._index_line(p) for p in self.products) +
            "\n\nFULL DETAILS of the listings that matter now:\n" + ("\n".join(lines) or "none") +
            f"\n\nListings shown as picture cards under your reply: {shown}.\n" + not_found +
            "- Quote prices, sizes, floors and terms exactly from this data. A listing can be for "
            "sale, for rent or both: mention every option it has.\n"
            f"- The agency only has listings in {names}. If the customer asks about a complex, "
            "block, floor or flat that is not in this data, say plainly that it was not found, "
            "then offer the most similar listings from the data.\n"
            "- Always say whether a listing is AVAILABLE, SOLD, RESERVED or RENTED. If the one asked "
            "about is gone, say so first, then offer its ALTERNATIVES in their order: the same type "
            "on another floor of the same building, then another block of the same complex, then "
            "nearby. If it has none, ask where they want to buy and what type they want.\n"
            "- When the customer reacts to a listing (likes it, finds it too expensive, too small, "
            "wrong floor...), answer that briefly, then ask one follow-up: would they like to book a "
            "viewing of it, or, if it doesn't suit them, how many rooms they want, in which complex, "
            "and how they plan to pay (cash, bank loan or mortgage, or trade-in/barter).\n"
            "- Never offer a viewing of a listing that is not available. Mention at most 3 listings by name."
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
        place = p["area_name"][lang] + ", " + (UI[lang]["block"].format(n=p["block"]) if p.get("block")
                                               else p["district"][lang])
        for line in _wrap(d, place, f_place, 470, 1):
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
