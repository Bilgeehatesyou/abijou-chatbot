"""The clinic's knowledge base: data/clinic.yaml, read once at start-up.

Everything the bot says about the clinic (services, prices, branches, hours,
policies, FAQs) comes from that file, in Mongolian, English and Korean.
"""
import re
from pathlib import Path
from typing import List, Optional

import yaml

CLINIC_PATH = Path(__file__).resolve().parent.parent / "data" / "clinic.yaml"
LANGS = ("mn", "en", "ko")
CURRENCY_FORMAT = {"MNT": "{:,}₮", "KRW": "₩{:,}"}
FREE = {"mn": "үнэгүй", "en": "free", "ko": "무료"}


def tr(obj, lang: str) -> str:
    """The text in `lang` from a {mn, en, ko} object (English, then Mongolian, as fallback)."""
    if not isinstance(obj, dict):
        return obj or ""
    return obj.get(lang) or obj.get("en") or obj.get("mn") or ""


def money(amount, currency: str, lang: str = "mn") -> str:
    if amount == 0:
        return FREE[lang]
    return CURRENCY_FORMAT[currency].format(int(amount))


# Question words that say nothing about the topic ("... хэд вэ?", "... yu ve").
STOPWORDS = {"вэ", "бэ", "уу", "үү", "юу", "юм", "хэд", "ve", "be", "uu", "yu", "hed", "the", "is",
             "are", "do", "you", "what", "how", "can", "나요", "있나요", "인가요"}


def _tokens(text: str) -> set:
    return {w for w in re.findall(r"\w+", text.lower()) if len(w) >= 2 and w not in STOPWORDS}


class Clinic:
    def __init__(self, path: Path = CLINIC_PATH):
        self.data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        d = self.data
        self.id = d["id"]
        self.countries = {c["id"]: c for c in d["countries"]}
        self.branches = d["branches"]
        self.services = d["services"]
        self.categories = d["categories"]
        self.faqs = d.get("faqs", [])
        for b in self.branches:
            b.setdefault("capacity", d.get("default_capacity", 1))

    # ---- lookups ----
    def name(self, lang: str) -> str:
        return tr(self.data["name"], lang)

    def branch(self, branch_id: Optional[str]) -> Optional[dict]:
        return next((b for b in self.branches if b["id"] == branch_id), None)

    def service(self, service_id: Optional[str]) -> Optional[dict]:
        return next((s for s in self.services if s["id"] == service_id), None)

    def branches_in(self, country_id: str) -> List[dict]:
        return [b for b in self.branches if b["country"] == country_id]

    def services_in(self, category_id: str) -> List[dict]:
        return [s for s in self.services if s["category"] == category_id]

    def country_of(self, branch: dict) -> dict:
        return self.countries[branch["country"]]

    def phone(self, country_id: str = "mn") -> str:
        return self.data["contacts"][country_id]["phone"]

    def contact_lines(self, lang: str) -> str:
        lines = [f"📞 {tr(c['label'], lang)}: {c['phone']}" for c in self.data["contacts"].values()]
        lines.append(f"✉️ {self.data['email']}")
        lines.append(f"📷 Instagram: {self.data['instagram']}")
        return "\n".join(lines)

    # ---- prices ----
    def price_line(self, service: dict, lang: str, country_id: Optional[str] = None) -> str:
        """'180,000₮ · ₩99,000' (or one currency when the country is known)."""
        countries = [self.countries[country_id]] if country_id else list(self.countries.values())
        parts = []
        for c in countries:
            amount = service["price"].get(c["currency"])
            if amount is None:
                continue
            label = money(amount, c["currency"], lang)
            parts.append(label if country_id else f"{c['flag']} {label}")
        return " · ".join(parts)

    def service_text(self, service: dict, lang: str, country_id: Optional[str] = None) -> str:
        """A service with its price, packages and options, for menus and the model."""
        currencies = ([self.countries[country_id]["currency"]] if country_id
                      else [c["currency"] for c in self.countries.values()])
        lines = [f"{tr(service['name'], lang)} — {self.price_line(service, lang, country_id)}"]
        for o in service.get("options", []):
            prices = " · ".join(money(o[c], c, lang) for c in currencies if c in o)
            lines.append(f"   • {tr(o['name'], lang)}: {prices}")
        for p in service.get("packages", []):
            prices = " · ".join(money(p[c], c, lang) for c in currencies if c in p)
            label = {"mn": f"{p['sessions']} удаагийн багц", "en": f"{p['sessions']}-session package",
                     "ko": f"{p['sessions']}회 패키지"}[lang]
            lines.append(f"   • {label}: {prices}")
        if service.get("price_note"):
            lines.append(f"   ({tr(service['price_note'], lang)})")
        return "\n".join(lines)

    def branch_text(self, branch: dict, lang: str) -> str:
        lines = [f"📍 {tr(branch['name'], lang)}", f"   {tr(branch['address'], lang)}",
                 f"   🕐 {tr(branch['hours_text'], lang)}"]
        if branch.get("note"):
            lines.append(f"   ⭐ {tr(branch['note'], lang)}")
        return "\n".join(lines)

    # ---- everything, for the model ----
    def knowledge(self, lang: str) -> str:
        d = self.data
        out = [tr(d["summary"], lang), "",
               "CONTACT", self.contact_lines(lang), "",
               "PAYMENT", tr(d["payment_methods"], lang), "",
               "PRICES: MNT (₮) at the Mongolia branches, KRW (₩) at the Korea branches.", "",
               "SERVICES"]
        for cat in self.categories:
            out.append(f"[{tr(cat['name'], lang)}]")
            for s in self.services_in(cat["id"]):
                out.append("- " + self.service_text(s, lang).replace("\n   ", "\n    "))
                out.append(f"    {tr(s['details'], lang)}")
        out += ["", "PROMOTIONS"] + [f"- {tr(p, lang)}" for p in d.get("promotions", [])]
        out += ["", "BRANCHES"]
        for country in self.countries.values():
            out.append(f"[{tr(country['name'], lang)}]")
            out += [self.branch_text(b, lang) for b in self.branches_in(country["id"])]
        out += ["", "POLICIES"] + [f"- {tr(p['title'], lang)}: {tr(p['text'], lang)}"
                                   for p in d.get("policies", [])]
        out += ["", "FAQ"] + [f"Q: {tr(f['question'], lang)}\nA: {tr(f['answer'], lang)}"
                              for f in self.faqs]
        return "\n".join(out)

    # ---- keyword matching (used when the model is down) ----
    def match_faq(self, text: str, lang: str) -> Optional[dict]:
        asked = _tokens(text)
        if not asked:
            return None
        best, best_score = None, 0.0
        for f in self.faqs:
            phrasings = [*f["question"].values()] + [v for vs in f.get("variants", {}).values() for v in vs]
            for ph in phrasings:
                words = _tokens(ph)
                if not words:
                    continue
                score = len(asked & words) / min(len(asked), len(words))
                if score > best_score:
                    best, best_score = f, score
        return best if best_score >= 0.5 else None

    def match_service(self, text: str) -> Optional[dict]:
        """A service named in free text ("neobeam", "Rejuran", "пико тонинг", "엑셀V")."""
        low = text.lower()
        for s in self.services:
            names = [*s["name"].values(), *s["short"].values(), s["id"].replace("_", " ")]
            names += [n for o in s.get("options", []) for n in o["name"].values()]
            for n in names:
                key = n.lower().split(" (")[0].strip()
                # Hangul packs a syllable per letter: "엑셀v", "리쥬란" are whole names
                shortest = 3 if re.search(r"[가-힣]", key) else 4
                if len(key) >= shortest and key in low:
                    return s
        return None


_clinic: Optional[Clinic] = None


def get_clinic() -> Clinic:
    global _clinic
    if _clinic is None:
        _clinic = Clinic()
    return _clinic
