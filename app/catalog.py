"""Product catalogs for demo businesses (currently MCC Foods / "wholesale").

    python -m app.catalog build     # (re)writes data/demo/catalogs/wholesale.json

A catalog is a JSON list of products. MCC's real products (names/brands/sizes from
mccfoods.mn) come first; a few hundred made-up items under invented brands (real=False)
make the catalog feel full-size. All prices are estimates.

Search understands Mongolian, English and Mongolian typed in Latin letters: both the
query and the product text are transliterated to Latin before matching.
Product images are generated cards (Pillow + Noto Sans), not photos.
"""
import argparse
import io
import json
import random
import re
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parent.parent
CATALOG_DIR = ROOT / "data" / "demo" / "catalogs"
FONT_DIR = Path(__file__).resolve().parent / "fonts"

CATEGORIES = {
    "noodles": {"mn": "Гоймон, макарон", "en": "Noodles & pasta", "emoji": "🍝",
                "color": (250, 224, 178), "accent": (214, 132, 40),
                "words": ["гоймон", "макарон", "noodle", "noodles", "pasta", "spaghetti", "спагетти",
                          "vermicelli", "гурилан"]},
    "rice": {"mn": "Будаа, үр тариа", "en": "Rice & grains", "emoji": "🍚",
             "color": (236, 232, 214), "accent": (128, 118, 76),
             "words": ["будаа", "rice", "grain", "сагаг", "buckwheat", "манна", "semolina", "арвай",
                       "barley", "шар будаа", "millet", "овъёос", "oat"]},
    "oil": {"mn": "Ургамлын тос", "en": "Cooking oil", "emoji": "🫒",
            "color": (252, 240, 170), "accent": (196, 160, 20),
            "words": ["тос", "oil", "ургамлын тос", "наранцэцгийн тос"]},
    "baking": {"mn": "Мөөгөнцөр, гурил, жигд", "en": "Yeast, flour & baking", "emoji": "🥖",
               "color": (243, 222, 205), "accent": (170, 100, 60),
               "words": ["мөөгөнцөр", "yeast", "дрожжи", "гурил", "flour", "жигд", "baking",
                         "сод", "soda", "какао", "cocoa", "ванил"]},
    "sugar": {"mn": "Чихэр, амтлагч", "en": "Sugar & sweets", "emoji": "🍬",
              "color": (250, 214, 222), "accent": (200, 80, 110),
              "words": ["чихэр", "sugar", "зөгийн бал", "honey", "үзэм", "raisin", "чангаанз"]},
    "canned": {"mn": "Лаазалсан хүнс", "en": "Canned goods", "emoji": "🥫",
               "color": (246, 205, 196), "accent": (190, 70, 50),
               "words": ["лааз", "лаазалсан", "canned", "эрдэнэ шиш", "corn", "шош", "beans",
                         "лоол", "tomato"]},
    "drinks": {"mn": "Цай, кофе", "en": "Tea & coffee", "emoji": "☕",
               "color": (220, 205, 190), "accent": (110, 70, 40),
               "words": ["цай", "tea", "кофе", "coffee", "какао"]},
    "other": {"mn": "Давс, сүмс, бусад", "en": "Salt, sauces & more", "emoji": "🧂",
              "color": (214, 228, 240), "accent": (60, 110, 160),
              "words": ["давс", "salt", "сүмс", "sauce", "шүдэнз", "match", "перец", "pepper",
                        "кетчуп", "ketchup", "майонез", "mayonnaise", "самар", "nuts", "үр", "seeds"]},
}

# ---------- MCC Foods' real products (mccfoods.mn/en/products.php, 2026-09) ----------
# (brand, name_en, name_mn, category, [(size_label, est_price_mnt), ...])
REAL = [
    ("Arden", "Fusilli pasta", "Фузилли гоймон", "noodles", [("400гр", 3200)]),
    ("Arden", "Penne Rigate pasta", "Пенне ригате гоймон", "noodles", [("400гр", 3200)]),
    ("Arden", "Thimbles pasta", "Хуруувчин гоймон", "noodles", [("400гр", 3200)]),
    ("Arden", "Vermicelli", "Вермишель гоймон", "noodles", [("400гр", 3100)]),
    ("Leader", "Korean vermicelli noodle", "Солонгос шилэн гоймон", "noodles",
     [("500гр", 4500), ("1кг", 8500)]),
    ("Melnik", "Bitki noodles", "Битки гоймон", "noodles", [("3кг", 14500), ("5кг", 23000)]),
    ("Melnik", "Perishki noodles", "Перишки гоймон", "noodles", [("3кг", 14500), ("5кг", 23000)]),
    ("Melnik", "Periya noodles", "Перья гоймон", "noodles", [("3кг", 14500), ("5кг", 23000)]),
    ("Melnik", "Rakushki noodles", "Ракушки гоймон", "noodles", [("3кг", 14500), ("5кг", 23000)]),
    ("Melnik", "Spirali noodles", "Спираль гоймон", "noodles", [("3кг", 14500), ("5кг", 23000)]),
    ("Tsesna", "Bitki noodles", "Битки гоймон", "noodles", [("1.6кг", 8900), ("4кг", 20500)]),
    ("Tsesna", "Jaima noodles", "Жайма гоймон", "noodles", [("0.4кг", 2600)]),
    ("Tsesna", "Periya noodles", "Перья гоймон", "noodles", [("1.6кг", 8900), ("4кг", 20500)]),
    ("Tsesna", "Rakushki noodles", "Ракушки гоймон", "noodles", [("1.6кг", 8900), ("4кг", 20500)]),
    ("Tsesna", "Spaghetti", "Спагетти", "noodles", [("1.6кг", 9200)]),
    ("Tsesna", "Spiral noodles", "Спираль гоймон", "noodles", [("1.6кг", 8900), ("4кг", 20500)]),
    ("Korean", "Fine vermicelli noodle", "Нарийн шилэн гоймон", "noodles",
     [("250гр", 2400), ("500гр", 4300)]),
    ("Korean", "Vermicelli noodle", "Шилэн гоймон", "noodles",
     [("250гр", 2300), ("500гр", 4200), ("1кг", 7900)]),
    ("Able", "Refined palm olein oil", "Цэвэршүүлсэн далдуу модны тос", "oil", [("16л", 98000)]),
    ("Tsivetok", "Vegetable oil", "Ургамлын тос", "oil", [("1кг", 6200), ("5кг", 29500)]),
    ("Able Farm", "Cooking oil", "Хоолны тос", "oil", [("20л", 118000)]),
    ("Basmati", "Basmati rice", "Басмати будаа", "rice", [("1кг", 7800), ("2кг", 15000), ("5кг", 36000)]),
    ("Eco", "Rice", "Цагаан будаа", "rice", [("25кг", 82000)]),
    ("Harbin", "Rice (green pack)", "Цагаан будаа (ногоон уут)", "rice", [("25кг", 98000)]),
    ("Harbin", "Rice (red pack)", "Цагаан будаа (улаан уут)", "rice", [("5кг", 21500), ("25кг", 102000)]),
    ("Jasmin", "Jasmine rice", "Жасмин будаа", "rice", [("5кг", 26000)]),
    ("Kitchen King", "Rice", "Цагаан будаа", "rice", [("2кг", 14500), ("5кг", 34000)]),
    ("Leader", "Millet", "Шар будаа", "rice", [("2кг", 7400), ("5кг", 17500), ("25кг", 82000)]),
    ("Leader", "Rice", "Цагаан будаа", "rice", [("25кг", 88000)]),
    ("Leader", "Rice (green pack)", "Цагаан будаа (ногоон уут)", "rice", [("5кг", 18500)]),
    ("Leader", "Rice (red pack)", "Цагаан будаа (улаан уут)", "rice", [("5кг", 19000)]),
    ("Momy's", "Rice", "Цагаан будаа", "rice", [("25кг", 86000)]),
    ("MCC", "Semolina", "Манна будаа", "rice", [("25кг", 52000), ("50кг", 101000)]),
    ("MCC", "Buckwheat", "Сагаг", "rice", [("25кг", 95000), ("50кг", 186000)]),
    ("MCC", "Pearl barley", "Арвай", "rice", [("25кг", 48000)]),
    ("A-800", "Yeast", "Мөөгөнцөр", "baking", [("1кг", 16500)]),
    ("Angel", "Blue yeast", "Цэнхэр мөөгөнцөр", "baking", [("500гр", 9800)]),
    ("Angel", "Gold yeast", "Алтан мөөгөнцөр", "baking", [("500гр", 11200)]),
    ("Angel", "Yeast", "Мөөгөнцөр", "baking",
     [("12гр", 450), ("50гр", 1600), ("100гр", 2900), ("500гр", 8900)]),
    ("MCC", "Baking powder", "Жигд нунтаг", "baking", [("1кг", 7500)]),
    ("Gloripan", "Yeast", "Мөөгөнцөр", "baking",
     [("100гр", 2700), ("500гр", 9200), ("5кг", 72000), ("10кг", 138000)]),
    ("Хлебопечкин", "Baker's yeast", "Дрожжи мөөгөнцөр", "baking", [("500гр", 8700)]),
    ("Baikalochka", "Salt", "Давс", "other", [("1кг", 1300)]),
    ("Beans", "Soy sauce", "Шар буурцгийн сүмс", "other", [("900гр", 6800)]),
    ("Extra Soli", "Iodized salt", "Иодтой давс", "other", [("1кг", 1200)]),
    ("Extra Soli", "Non-iodized salt", "Иодгүй давс", "other", [("1кг", 1150)]),
    ("Extra Soli", "Salt", "Давс", "other", [("50кг", 38000)]),
    ("Leader", "Sweet corn", "Чихэрлэг эрдэнэ шиш", "canned", [("340гр", 3400)]),
    ("Russian", "Matches (10 boxes)", "Шүдэнз (10 хайрцаг)", "other", [("10ш", 1500)]),
    ("MCC", "Sweet raisin", "Үзэм", "sugar", [("8кг", 96000)]),
    ("MCC", "Tablet salt", "Шахмал давс", "other", [("25кг", 24000)]),
    ("MCC", "Baking soda", "Хүнсний сод", "baking", [("500гр", 2900)]),
]

# ---------- invented extras (clearly fictional brands) ----------
FAKE_BRANDS = ["Tavan Tal", "Erdene Grain", "Uulyn Tsetseg", "Sunny Steppe", "Baya Foods",
               "Khangai Pack", "Orgil Select", "Tuul Valley"]
# (name_en, name_mn, category, sizes, price per size unit or per item)
FAKE_TYPES = [
    ("Wheat flour", "Гурил", "baking", [("2кг", 4200), ("5кг", 10200), ("25кг", 48000)]),
    ("Premium flour", "Дээд гурил", "baking", [("2кг", 4800), ("5кг", 11500), ("25кг", 55000)]),
    ("Baking powder", "Жигд нунтаг", "baking", [("100гр", 1400)]),
    ("Vanilla sugar", "Ванилийн чихэр", "baking", [("20гр", 700)]),
    ("Cocoa powder", "Какао", "baking", [("200гр", 7400)]),
    ("Granulated sugar", "Элсэн чихэр", "sugar", [("1кг", 2800), ("5кг", 13500), ("50кг", 128000)]),
    ("Honey", "Зөгийн бал", "sugar", [("500гр", 14500)]),
    ("Raisins", "Үзэм", "sugar", [("500гр", 8900)]),
    ("Dried apricots", "Хатаасан чангаанз", "sugar", [("500гр", 12800)]),
    ("Long grain rice", "Урт цагаан будаа", "rice", [("1кг", 3800), ("5кг", 18000), ("25кг", 86000)]),
    ("Oat flakes", "Овъёосны ширхэг", "rice", [("500гр", 3200), ("1кг", 5900)]),
    ("Buckwheat", "Сагаг", "rice", [("900гр", 6800)]),
    ("Spaghetti", "Спагетти", "noodles", [("400гр", 2900), ("1кг", 6600)]),
    ("Egg noodles", "Өндөгтэй гоймон", "noodles", [("400гр", 3100)]),
    ("Glass noodles", "Шилэн гоймон", "noodles", [("250гр", 2500)]),
    ("Sunflower oil", "Наранцэцгийн тос", "oil", [("1л", 6600), ("3л", 19200), ("5л", 31500)]),
    ("Tomato paste", "Улаан лоолийн оо", "canned", [("380гр", 3900), ("800гр", 8200)]),
    ("Canned beans", "Лаазалсан шош", "canned", [("400гр", 3600)]),
    ("Canned corn", "Лаазалсан эрдэнэ шиш", "canned", [("340гр", 3300)]),
    ("Canned peas", "Лаазалсан вандуй", "canned", [("400гр", 3500)]),
    ("Black tea (100 bags)", "Хар цай (100 уут)", "drinks", [("200гр", 7500)]),
    ("Green tea (100 bags)", "Ногоон цай (100 уут)", "drinks", [("200гр", 8200)]),
    ("Instant coffee", "Уусдаг кофе", "drinks", [("100гр", 9800)]),
    ("3in1 coffee (20 sachets)", "3в1 кофе (20 уут)", "drinks", [("360гр", 6900)]),
    ("Table salt", "Хоолны давс", "other", [("1кг", 1250)]),
    ("Black pepper", "Хар перец", "other", [("50гр", 2400)]),
    ("Soy sauce", "Шар буурцгийн сүмс", "other", [("500мл", 4200), ("1.8л", 12500)]),
    ("Ketchup", "Кетчуп", "other", [("500гр", 4600)]),
    ("Mayonnaise", "Майонез", "other", [("400гр", 5200)]),
    ("Peanuts", "Газрын самар", "other", [("500гр", 7900)]),
    ("Sunflower seeds", "Наранцэцгийн үр", "other", [("200гр", 2800)]),
]
FAKE_TARGET = 300

# How Mongolians type Cyrillic in Latin letters (used for matching only).
CYR_TO_LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "j", "з": "z",
    "и": "i", "й": "i", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "ө": "u", "п": "p",
    "р": "r", "с": "s", "т": "t", "у": "u", "ү": "u", "ф": "f", "х": "h", "ц": "ts", "ч": "ch",
    "ш": "sh", "щ": "sh", "ъ": "", "ы": "ii", "ь": "i", "э": "e", "ю": "yu", "я": "ya",
}
# Needs at least one exact brand/name match (3) or name-prefix + size.
MIN_MATCH_SCORE = 2.5
STOPWORDS = {"ve", "we", "uu", "yu", "bna", "baina", "bgaa", "baigaa", "hed", "une", "vne",
             "unetei", "ali", "ta", "tanai", "bii", "how", "much", "the", "is", "do", "you",
             "have", "price", "of", "and", "a", "for", "une?", "zarah", "avah", "avmaar"}


def translit(text: str) -> str:
    return "".join(CYR_TO_LAT.get(ch, ch) for ch in text.lower())


def tokens(text: str) -> List[str]:
    t = translit(text).replace(",", ".")
    t = re.sub(r"(\d)\s+(k?g|gr|kg|l|ml|sh)\b", r"\1\2", t)  # "25 кг" -> "25kg"
    return [w for w in re.findall(r"[a-z0-9.]+", t) if w not in STOPWORDS and len(w) >= 2]


def _unit(size: str) -> tuple:
    """(mn, en) selling unit for a size label."""
    m = re.match(r"([\d.]+)\s*(кг|л)", size)
    if m and float(m.group(1)) >= 16:
        return ("шуудай", "sack") if m.group(2) == "кг" else ("сав", "canister")
    return ("ширхэг", "piece")


def _product(sku, brand, name_en, name_mn, category, size, price, real) -> dict:
    unit_mn, unit_en = _unit(size)
    size_en = size.replace("кг", "kg").replace("гр", "g").replace("мл", "ml").replace("л", "L").replace("ш", " pcs")
    return {
        "sku": sku, "real": real, "brand": brand, "category": category,
        "name": {"mn": f"{brand} {name_mn} {size}", "en": f"{brand} {name_en} {size_en}"},
        "size": {"mn": size, "en": size_en}, "price_mnt": price, "unit": {"mn": unit_mn, "en": unit_en},
    }


def build() -> list:
    products, n = [], 0
    for brand, name_en, name_mn, category, sizes in REAL:
        for size, price in sizes:
            n += 1
            products.append(_product(f"MCC{n:03d}", brand, name_en, name_mn, category, size, price, True))
    rng = random.Random(2026)
    combos = [(b, t) for b in FAKE_BRANDS for t in FAKE_TYPES]
    rng.shuffle(combos)
    fake, k = [], 0
    for brand, (name_en, name_mn, category, sizes) in combos:
        factor = rng.uniform(0.9, 1.15)
        for size, price in sizes:
            if len(fake) >= FAKE_TARGET:
                break
            k += 1
            est = int(round(price * factor / 50) * 50)
            fake.append(_product(f"DEM{k:03d}", brand, name_en, name_mn, category, size, est, False))
    return products + fake


# ---------- runtime ----------
class Catalog:
    """Products to order (MCC Foods). app/listings.Listings has the same interface."""
    kind = "products"

    def __init__(self, products: list):
        self.products = products
        self.by_sku = {p["sku"]: p for p in products}
        self._index = []
        for p in products:
            cat = CATEGORIES[p["category"]]
            name = set(tokens(p["name"]["mn"] + " " + p["name"]["en"]))
            category = set(tokens(" ".join([cat["mn"], cat["en"], " ".join(cat["words"])])))
            size = set(tokens(p["size"]["mn"] + " " + p["size"]["en"]))
            self._index.append((p, name - size, category, set(tokens(p["brand"])), size))

    def search(self, text: str, limit: int = 10) -> list:
        query = tokens(text)
        if not query:
            return []
        def prefix(q, words):
            return len(q) >= 4 and any(w.startswith(q) or q.startswith(w) for w in words if len(w) >= 4)

        scored = []
        for p, name, category, brand, size in self._index:
            score = 0.0
            for q in query:
                if q in brand:
                    score += 3
                elif q in name:
                    score += 3
                elif q in size:
                    score += 2
                elif prefix(q, name):
                    score += 1.5
                elif q in category or prefix(q, category):
                    score += 1
            if score:
                scored.append((score, p["real"], p))
        if not scored:
            return []
        best = max(s[0] for s in scored)
        if best < MIN_MATCH_SCORE:  # only loose/category hits: not a product question
            return []
        keep = [s for s in scored if s[0] >= max(1, best * 0.6)]
        keep.sort(key=lambda s: (s[0], s[1]), reverse=True)
        return [s[2] for s in keep[:limit]]

    def in_category(self, category: str) -> list:
        items = [p for p in self.products if p["category"] == category]
        return sorted(items, key=lambda p: (not p["real"], p["name"]["en"]))

    def categories(self) -> list:
        present = {p["category"] for p in self.products}
        return [c for c in CATEGORIES if c in present]

    # ---- presentation (shared interface with Listings) ----
    def category_label(self, category: str, lang: str) -> str:
        return f"{CATEGORIES[category]['emoji']} {CATEGORIES[category][lang]}"

    def browse_button(self, lang: str) -> str:
        return "🛒 Бүтээгдэхүүн" if lang == "mn" else "🛒 Products"

    def pick_text(self, lang: str) -> str:
        if lang == "mn":
            return ("Аль төрлийн бүтээгдэхүүн үзэх вэ? Эсвэл нэрээр нь бичээд хайгаарай "
                    "(жишээ нь: «Leader будаа 25кг»).")
        return ("Which kind of products would you like to see? Or type a product name "
                "to search (e.g. “Leader rice 25kg”).")

    def card(self, p: dict, lang: str, image_url: str) -> "Card":
        from .models import Card, QuickReply
        subtitle = price_label(p, lang)
        if not p["real"]:
            subtitle += " · " + ("жишээ бараа" if lang == "mn" else "sample item")
        return Card(title=p["name"][lang], subtitle=subtitle, image_url=image_url,
                    buttons=[QuickReply("📝 Захиалах" if lang == "mn" else "📝 Order",
                                        f"ORDER_{p['sku']}")])

    def prompt_context(self, matches: list, lang: str) -> str:
        found = "\n".join(f"- {m['name'][lang]}: {price_label(m, lang)}" for m in matches) or "- (none)"
        return (
            f"\n\nPRODUCT CATALOG: {len(self.products)} products in total. Closest matches to the "
            f"customer's message (prices are estimates):\n{found}\n"
            "Picture cards of these matches are shown under your reply, so mention at most "
            "2-3 of them in your text. If nothing matches, say so and suggest the 🛒 button."
        )

    def render(self, p: dict, lang: str = "mn") -> bytes:
        return render_card(p, lang)


@lru_cache(maxsize=None)
def load_catalog(business_id: str):
    """A business's Catalog (products) or Listings (properties), or None."""
    path = CATALOG_DIR / f"{business_id}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and data.get("kind") == "listings":
        from .listings import Listings
        return Listings(data["items"], data.get("areas", {}))
    return Catalog(data)


def price_label(p: dict, lang: str) -> str:
    unit = p["unit"][lang]
    if lang == "mn":
        return f"≈ {p['price_mnt']:,}₮ / {unit}"
    return f"≈ {p['price_mnt']:,} MNT / {unit}"


# ---------- product card image ----------
CARD = 600


@lru_cache(maxsize=4)
def _font(bold: bool, size: int):
    from PIL import ImageFont
    return ImageFont.truetype(str(FONT_DIR / ("NotoSans-Bold.ttf" if bold else "NotoSans-Regular.ttf")), size)


def _wrap(draw, text: str, font, width: int, max_lines: int) -> List[str]:
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= width:
            line = trial
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(".,") + "…"
    return lines


def _icon(draw, category: str, cx: int, cy: int, color):
    """A simple drawn symbol per category."""
    if category == "rice":
        for dx, dy in [(-40, -10), (-10, -30), (20, -8), (-25, 20), (8, 18), (38, 22), (-5, 45)]:
            draw.ellipse((cx + dx - 10, cy + dy - 18, cx + dx + 10, cy + dy + 18), fill=color)
    elif category == "noodles":
        for i in range(4):
            y = cy - 36 + i * 24
            draw.arc((cx - 70, y - 14, cx - 20, y + 14), 180, 360, fill=color, width=8)
            draw.arc((cx - 22, y - 14, cx + 28, y + 14), 0, 180, fill=color, width=8)
            draw.arc((cx + 26, y - 14, cx + 76, y + 14), 180, 360, fill=color, width=8)
    elif category == "oil":
        draw.ellipse((cx - 38, cy - 6, cx + 38, cy + 62), fill=color)
        draw.polygon([(cx - 36, cy + 14), (cx, cy - 62), (cx + 36, cy + 14)], fill=color)
    elif category == "baking":
        draw.rounded_rectangle((cx - 70, cy - 30, cx + 70, cy + 40), radius=34, fill=color)
        for dx in (-35, 0, 35):
            draw.line((cx + dx - 12, cy - 16, cx + dx + 12, cy + 8), fill=(255, 255, 255), width=6)
    elif category == "canned":
        draw.rectangle((cx - 45, cy - 45, cx + 45, cy + 55), fill=color)
        draw.ellipse((cx - 45, cy - 60, cx + 45, cy - 30), fill=color, outline=(255, 255, 255), width=4)
    elif category == "drinks":
        draw.rounded_rectangle((cx - 50, cy - 40, cx + 40, cy + 50), radius=14, fill=color)
        draw.arc((cx + 20, cy - 20, cx + 70, cy + 30), 270, 90, fill=color, width=12)
    elif category == "sugar":
        for dx, dy in [(-30, -20), (10, -30), (35, 10), (-15, 25), (-45, 18)]:
            draw.rectangle((cx + dx - 16, cy + dy - 16, cx + dx + 16, cy + dy + 16), fill=color)
    else:
        draw.polygon([(cx - 40, cy + 55), (cx - 28, cy - 40), (cx + 28, cy - 40), (cx + 40, cy + 55)], fill=color)
        draw.rectangle((cx - 30, cy - 62, cx + 30, cy - 42), fill=color)


def render_card(p: dict, lang: str = "mn") -> bytes:
    """A square 'packaging' style card: brand, product name, size, category icon."""
    from PIL import Image, ImageDraw
    cat = CATEGORIES[p["category"]]
    bg, accent = cat["color"], cat["accent"]
    img = Image.new("RGB", (CARD, CARD), bg)
    d = ImageDraw.Draw(img)
    # package
    d.rounded_rectangle((70, 60, 530, 540), radius=36, fill=(255, 255, 255), outline=accent, width=6)
    d.rounded_rectangle((73, 63, 527, 150), radius=33, fill=accent, corners=(True, True, False, False))
    brand_font = _font(True, 46)
    brand = p["brand"].upper()
    bw = d.textlength(brand, font=brand_font)
    if bw > 420:
        brand_font = _font(True, 34)
        bw = d.textlength(brand, font=brand_font)
    d.text(((CARD - bw) / 2, 80), brand, font=brand_font, fill=(255, 255, 255))
    _icon(d, p["category"], CARD // 2, 250, accent)
    # product name without brand/size, wrapped
    size = p["size"][lang]
    name = p["name"][lang].replace(p["brand"], "").replace(size, "").strip()
    name_font = _font(True, 36)
    y = 345
    for line in _wrap(d, name, name_font, 420, 2):
        w = d.textlength(line, font=name_font)
        d.text(((CARD - w) / 2, y), line, font=name_font, fill=(40, 40, 40))
        y += 46
    # size badge
    size_font = _font(True, 40)
    sw = d.textlength(size, font=size_font)
    d.rounded_rectangle(((CARD - sw) / 2 - 24, 450, (CARD + sw) / 2 + 24, 510), radius=28, fill=accent)
    d.text(((CARD - sw) / 2, 452), size, font=size_font, fill=(255, 255, 255))
    # honest label: this is a generated picture
    tag = "Жишээ зураг" if lang == "mn" else "Sample image"
    small = _font(False, 22)
    d.text((CARD - 30 - d.textlength(tag, font=small), CARD - 42), tag, font=small, fill=accent)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


@lru_cache(maxsize=512)
def card_png(business_id: str, sku: str, lang: str) -> Optional[bytes]:
    catalog = load_catalog(business_id)
    product = catalog.by_sku.get(sku) if catalog else None
    return catalog.render(product, lang) if product else None


def image_url(base_url: str, business_id: str, p: dict, lang: str) -> str:
    return f"{base_url}/img/{business_id}/{p['sku']}.png?lang={lang}" if base_url else ""


def cmd_build(args):
    products = build()
    CATALOG_DIR.mkdir(parents=True, exist_ok=True)
    path = CATALOG_DIR / "wholesale.json"
    path.write_text(json.dumps(products, ensure_ascii=False, indent=1), encoding="utf-8")
    real = sum(p["real"] for p in products)
    print(f"wrote {path.relative_to(ROOT)}: {len(products)} products ({real} real MCC, {len(products) - real} demo)")


def main():
    parser = argparse.ArgumentParser(prog="python -m app.catalog")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build", help="write the MCC Foods demo catalog").set_defaults(func=cmd_build)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
