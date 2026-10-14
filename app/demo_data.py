"""Generate and load the demo FAQ knowledge base.

    python -m app.demo_data generate              # all businesses missing a JSON file
    python -m app.demo_data generate --only dental --force
    python -m app.demo_data check                 # fix phones + list warnings after hand edits
    python -m app.demo_data load                  # JSON files -> SQLite (DB_PATH)

Generation uses whatever LLM_* settings are in .env (meant for Gemini).
Each business is two steps: a profile first, then FAQs written from that
profile, so prices and hours stay consistent across answers.
"""
import argparse
import hashlib
import json
import re
import time
from pathlib import Path

import yaml

from .config import settings
from .llm import get_llm
from .store import Store

DEMO_DIR = Path("data/demo")
SEEDS_PATH = DEMO_DIR / "seeds.yaml"
BUSINESS_DIR = DEMO_DIR / "businesses"

GENERATION_TIMEOUT = 300
MAX_ATTEMPTS = 6
RETRY_WAIT_SECONDS = 20

SYSTEM = (
    "You create realistic demo data for customer-service chatbots of small and "
    "medium businesses in Mongolia. Everything you write is fictional but must "
    "feel authentic to Ulaanbaatar in 2026: realistic MNT prices, local payment "
    "methods (QPay, SocialPay, bank transfer, card, cash), e-barimt receipts, "
    "10% VAT (НӨАТ) where relevant, Mongolian public holidays (Tsagaan Sar, "
    "Naadam) affecting schedules. Mongolian text must be natural, fluent "
    "Cyrillic as real Mongolian businesses write it, not a translation of "
    "English. English text must be natural too. Never use real brand, company, "
    "hospital or person names. Respond with valid JSON only, no markdown fences."
)

PROFILE_PROMPT = """Create the business profile for this {nature} business.

Fixed facts (use exactly as given):
{fixed_facts}
Brief: {brief}

Invent everything else ({invent}).
Include 10-20 offerings with concrete MNT prices (integers, no separators) where a
real business would publish a price, and 5-8 policies.

Return JSON with exactly this shape. Every {{"mn","en"}} object needs both languages:
{{
  "summary": {{"mn": "...", "en": "..."}},
  "address": {{"mn": "...", "en": "..."}},
  "phone": "{phone}",
  "email": "{email}",
  "website": "{website}",
  "hours": {{"mn": "...", "en": "..."}},
  "payment_methods": {{"mn": "...", "en": "..."}},
  "offerings": [
    {{"name": {{"mn": "...", "en": "..."}}, "price_mnt": 150000,
      "price_note": {{"mn": "...", "en": "..."}},
      "details": {{"mn": "...", "en": "..."}}}}
  ],
  "policies": [
    {{"title": {{"mn": "...", "en": "..."}}, "text": {{"mn": "...", "en": "..."}}}}
  ]
}}
price_mnt may be null for "price on request"; price_note may be empty strings."""

FAQ_PROMPT = """Here is the profile of a {nature} {kind_en} named "{name_en}":

{profile_json}

Write {count} FAQs that real customers of this business ask on Facebook Messenger.
Focus: {focus}
Do not repeat these existing questions: {existing}

Rules:
- Answers must use ONLY facts from the profile. Never invent new prices, hours,
  services or policies. If a price is in the profile, quote it exactly.
- Only write FAQs the profile can actually answer; skip a question (e.g. parking,
  discounts) if the profile doesn't cover it. Never mention "the profile", "our
  records" or "the available information" — customers must not see how this was made.
- Answers are short and friendly, 1-4 sentences, plain text (no markdown),
  like a helpful receptionist writing in Messenger.
- "variants" are other ways customers type the same question:
  "mn": 2 casual Mongolian Cyrillic phrasings (short, informal, like chat),
  "mn_latin": 2 phrasings of Mongolian written in Latin letters the way
  Mongolians type on phones (e.g. "une hed ve", "hezee ajilladag ve"),
  "en": 1 casual English phrasing.
- "id" is a short snake_case key, unique.
- "category" is one of: {categories}

Return a JSON array:
[
  {{"id": "...", "category": "...",
    "question": {{"mn": "...", "en": "..."}},
    "answer": {{"mn": "...", "en": "..."}},
    "variants": {{"mn": ["...", "..."], "mn_latin": ["...", "..."], "en": ["..."]}}}}
]"""

FAQ_BATCHES = [
    (16, "general questions every business gets: opening hours, location and "
         "parking, how to book or order, prices of the most popular items, payment "
         "methods, discounts, cancellations/refunds, contact and response times."),
    (18, "questions specific to this type of business and its services, the "
         "details first-time customers worry about, and a few tricky edge cases "
         "(holidays, special requests, complaints, eligibility)."),
]

CATEGORIES = ["hours_location", "booking", "pricing", "payment", "policies",
              "services", "contact", "other"]


class QuotaExhausted(Exception):
    """Daily API quota is gone; retrying or moving to the next business is pointless."""


def load_seeds() -> dict:
    return yaml.safe_load(SEEDS_PATH.read_text(encoding="utf-8"))


def _parse_json(text: str):
    starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    if not starts:
        raise ValueError("no JSON in reply")
    data, _ = json.JSONDecoder().raw_decode(text[min(starts):])
    return data


def _bilingual(obj) -> bool:
    return isinstance(obj, dict) and bool(obj.get("mn")) and bool(obj.get("en"))


def _check_profile(p: dict):
    for key in ("summary", "address", "hours", "payment_methods"):
        if not _bilingual(p.get(key)):
            raise ValueError(f"profile.{key} missing mn/en")
    if len(p.get("offerings", [])) < 5:
        raise ValueError("profile has fewer than 5 offerings")
    for o in p["offerings"]:
        if not _bilingual(o.get("name")):
            raise ValueError("offering name missing mn/en")


def _check_faqs(faqs) -> list:
    if not isinstance(faqs, list) or len(faqs) < 8:
        raise ValueError("expected a JSON array of FAQs")
    for f in faqs:
        if not (f.get("id") and _bilingual(f.get("question")) and _bilingual(f.get("answer"))):
            raise ValueError(f"FAQ incomplete: {str(f)[:80]}")
        if f.get("category") not in CATEGORIES:
            f["category"] = "other"
        f.setdefault("variants", {})
    return faqs


def _ask(llm, prompt: str, check):
    last_error = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if attempt > 1 and last_error == "no reply from model":
            wait = RETRY_WAIT_SECONDS * (attempt - 1)
            print(f"    waiting {wait}s before retrying...")
            time.sleep(wait)
        # No fallback: keep all generated data from the same (best) model.
        reply = llm.chat(
            [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
            temperature=0.7, timeout=GENERATION_TIMEOUT, use_fallback=False,
        )
        if not reply and "PerDay" in getattr(llm, "last_error", ""):
            raise QuotaExhausted(f"daily quota used up for {settings.LLM_MODEL}")
        if not reply:
            last_error = "no reply from model"
        else:
            try:
                data = _parse_json(reply)
                result = check(data)
                return data if result is None else result
            except (ValueError, json.JSONDecodeError) as e:
                last_error = e
        print(f"    attempt {attempt} failed: {last_error}")
    raise RuntimeError(f"giving up after {MAX_ATTEMPTS} attempts: {last_error}")


def _numbers(text: str) -> set:
    """Numbers of 4+ digits, ignoring thousands separators like 150,000 or 150 000."""
    joined = re.sub(r"(?<=\d)[,\s.'](?=\d{3}\b)", "", text)
    return set(re.findall(r"\d{4,}", joined))


PHONE_RE = re.compile(r"(?:\+?976[\s-]?)?\b(\d{4})[\s-](\d{4})\b")
MIXED_SCRIPT_RE = re.compile(r"\b(?=\w*[A-Za-z])(?=\w*[Ѐ-ӿ])\w+\b")
# Scripts that never belong in Mongolian/English data (Greek, Hebrew, Arabic, Indic, CJK, Hangul).
FOREIGN_SCRIPT_RE = re.compile(r"[Ͱ-Ͽ֐-ۿऀ-෿぀-鿿가-힯]")

# How Mongolians type Cyrillic letters in Latin on their phones.
CYR_TO_LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "j", "з": "z",
    "и": "i", "й": "i", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "ө": "u", "п": "p",
    "р": "r", "с": "s", "т": "t", "у": "u", "ү": "u", "ф": "f", "х": "h", "ц": "ts", "ч": "ch",
    "ш": "sh", "щ": "sh", "ъ": "i", "ы": "ii", "ь": "i", "э": "e", "ю": "yu", "я": "ya",
}


def fix_latin_variants(faqs: list) -> int:
    """Models sometimes slip Cyrillic letters into the Latin-script variants; transliterate them."""
    fixed = 0
    for f in faqs:
        variants = f.get("variants", {}).get("mn_latin", [])
        for i, v in enumerate(variants):
            if re.search(r"[Ѐ-ӿ]", v):
                variants[i] = "".join(
                    (CYR_TO_LAT.get(ch.lower(), ch).capitalize() if ch.isupper() else CYR_TO_LAT.get(ch, ch))
                    for ch in v)
                fixed += 1
    return fixed


def force_phone(obj, phone: str):
    """Replace any phone-looking number with the seed's fake one, so a model
    can't slip in a real-looking (possibly real) number. Year ranges are kept."""
    def fix(m):
        a, b = int(m.group(1)), int(m.group(2))
        return m.group(0) if 1900 <= a <= 2100 and 1900 <= b <= 2100 else phone
    if isinstance(obj, str):
        return PHONE_RE.sub(fix, obj)
    if isinstance(obj, list):
        return [force_phone(x, phone) for x in obj]
    if isinstance(obj, dict):
        return {k: force_phone(v, phone) for k, v in obj.items()}
    return obj


def _strings(obj, path=""):
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, list):
        for i, x in enumerate(obj):
            yield from _strings(x, f"{path}[{i}]")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _strings(v, f"{path}.{k}" if path else k)


def consistency_warnings(biz: dict) -> list:
    known = _numbers(json.dumps(biz["profile"], ensure_ascii=False))
    warnings = []
    for f in biz["faqs"]:
        for lang in ("mn", "en"):
            unknown = _numbers(f["answer"][lang]) - known
            if unknown:
                warnings.append(f"{f['id']} ({lang}): numbers not in profile: {sorted(unknown)}")
    for path, text in _strings({"profile": biz["profile"], "faqs": biz["faqs"]}):
        mixed = MIXED_SCRIPT_RE.findall(text)
        if mixed:
            warnings.append(f"{path}: Latin and Cyrillic letters mixed in one word: {mixed}")
        if ".mn_latin[" in path and re.search(r"[Ѐ-ӿ]", text):
            warnings.append(f"{path}: Cyrillic in a Latin-script variant: {text!r}")
        if FOREIGN_SCRIPT_RE.search(text):
            warnings.append(f"{path}: foreign script characters: {text!r}")
    return warnings


def generate_business(llm, seed: dict) -> dict:
    # Real businesses (fictional: false) pin their public facts under `fixed:`.
    real = seed.get("fictional", True) is False
    fixed = seed.get("fixed", {})
    email = fixed.get("email", f"info@{seed['slug']}.example")
    website = fixed.get("website", f"https://{seed['slug']}.example")
    facts = [f"- Name (mn): {seed['name']['mn']}", f"- Name (en): {seed['name']['en']}",
             f"- Type: {seed['kind']['en']}", f"- Phone: {seed['phone']}",
             f"- Email: {email or 'none (leave empty)'}", f"- Website: {website}"]
    for key in ("address", "hours"):
        if key in fixed:
            facts.append(f"- {key.title()}: {fixed[key]['mn']} / {fixed[key]['en']}")
    invent = ("only what the brief allows; never invent staff names, awards, branches or history"
              if real else "fictional address in a real Ulaanbaatar district with a made-up "
              "building name, opening hours, services/products with prices, policies")
    nature = "real" if real else "fictional"
    prompt = PROFILE_PROMPT.format(
        nature=nature, fixed_facts="\n".join(facts), brief=seed["brief"].strip(), invent=invent,
        phone=seed["phone"], email=email, website=website,
    )
    print("  profile...")
    profile = _ask(llm, prompt, _check_profile)
    profile.update(phone=seed["phone"], email=email, website=website,
                   **{k: fixed[k] for k in ("address", "hours") if k in fixed})

    faqs = []
    for count, focus in FAQ_BATCHES:
        print(f"  {count} FAQs: {focus[:50]}...")
        prompt = FAQ_PROMPT.format(
            nature=nature, kind_en=seed["kind"]["en"], name_en=seed["name"]["en"],
            profile_json=json.dumps(profile, ensure_ascii=False, indent=1),
            count=count, focus=focus, categories=", ".join(CATEGORIES),
            existing=json.dumps([f["question"]["en"] for f in faqs]) if faqs else "none",
        )
        faqs.extend(_ask(llm, prompt, _check_faqs))

    fix_latin_variants(faqs)
    seen = set()
    for i, f in enumerate(faqs):
        if f["id"] in seen:
            f["id"] = f"{f['id']}_{i}"
        seen.add(f["id"])

    return {
        "id": seed["id"], "industry": seed["industry"], "kind": seed["kind"],
        "emoji": seed["emoji"], "name": seed["name"],
        "fictional": not real, "generated_with": settings.LLM_MODEL,
        "profile": force_phone(profile, seed["phone"]),
        "faqs": force_phone(faqs, seed["phone"]),
    }


def cmd_generate(args):
    llm = get_llm()
    seeds = load_seeds()["businesses"]
    if args.only:
        seeds = [s for s in seeds if s["id"] in args.only]
        if not seeds:
            raise SystemExit(f"no seed with id in {args.only}")
    BUSINESS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"model: {settings.LLM_MODEL} @ {settings.LLM_BASE_URL}")

    failed = []
    for seed in seeds:
        path = BUSINESS_DIR / f"{seed['id']}.json"
        if path.exists() and not args.force:
            print(f"- {seed['id']}: exists, skipping (use --force)")
            continue
        print(f"- {seed['id']}: {seed['name']['en']}")
        try:
            biz = generate_business(llm, seed)
        except QuotaExhausted as e:
            print(f"  STOPPED: {e}. Try again after the quota resets or with another model.")
            failed.append(seed["id"])
            break
        except RuntimeError as e:
            print(f"  FAILED: {e}")
            failed.append(seed["id"])
            continue
        path.write_text(json.dumps(biz, ensure_ascii=False, indent=2), encoding="utf-8")
        warnings = consistency_warnings(biz)
        print(f"  saved {path} ({len(biz['profile']['offerings'])} offerings, "
              f"{len(biz['faqs'])} FAQs, {len(warnings)} consistency warnings)")
        for w in warnings:
            print(f"    ! {w}")
    if failed:
        raise SystemExit(f"failed: {', '.join(failed)}")


def cmd_check(args):
    """Re-run the automatic checks, e.g. after editing a JSON file by hand."""
    seeds = {s["id"]: s for s in load_seeds()["businesses"]}
    total = 0
    for path in sorted(BUSINESS_DIR.glob("*.json")):
        biz = json.loads(path.read_text(encoding="utf-8"))
        fixed = {**biz, "profile": force_phone(biz["profile"], seeds[biz["id"]]["phone"]),
                 "faqs": force_phone(biz["faqs"], seeds[biz["id"]]["phone"])}
        phones_changed = fixed != biz
        transliterated = fix_latin_variants(fixed["faqs"])
        if phones_changed or transliterated:
            path.write_text(json.dumps(fixed, ensure_ascii=False, indent=2), encoding="utf-8")
        if phones_changed:
            print(f"- {biz['id']}: replaced phone-like numbers with {seeds[biz['id']]['phone']}")
        if transliterated:
            print(f"- {biz['id']}: converted Cyrillic letters to Latin in {transliterated} Latin-script variants")
        warnings = consistency_warnings(fixed)
        total += len(warnings)
        print(f"- {biz['id']}: {len(fixed['faqs'])} FAQs, {len(warnings)} warnings")
        for w in warnings:
            print(f"    ! {w}")
    print(f"{total} warnings total")


def sync_businesses(store: Store) -> list:
    """Load businesses whose JSON file is new or changed since the last sync.

    Runs when the app starts, so adding a demo business only needs a deploy: hosted
    databases (Neon on Vercel) can't be reached with `load` from a laptop. A business
    already in the database the first time this runs is adopted as is, never reloaded,
    so data loaded by hand earlier is left alone until its file changes."""
    in_db = {b["id"] for b in store.list_businesses()}
    loaded = []
    for path in sorted(BUSINESS_DIR.glob("*.json")):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        key = f"demo_data:{path.stem}"
        known = store.crm_state_get(key)
        if path.stem in in_db and known in (None, digest):
            if known is None:
                store.crm_state_set(key, digest)
            continue
        store.replace_business(json.loads(path.read_text(encoding="utf-8")))
        store.crm_state_set(key, digest)
        loaded.append(path.stem)
    return loaded


def cmd_load(args):
    store = Store(args.db or settings.DB_PATH)
    order = {s["id"]: i for i, s in enumerate(load_seeds()["businesses"])}
    files = sorted(BUSINESS_DIR.glob("*.json"), key=lambda p: order.get(p.stem, len(order)))
    if not files:
        raise SystemExit(f"no files in {BUSINESS_DIR} — run generate first")
    for path in files:
        biz = json.loads(path.read_text(encoding="utf-8"))
        store.replace_business(biz)
        print(f"- {biz['id']}: {len(biz['faqs'])} FAQs loaded")
    print(f"loaded {len(files)} businesses into {store.label}")


def main():
    parser = argparse.ArgumentParser(prog="python -m app.demo_data")
    sub = parser.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate", help="create business JSON files with the LLM")
    g.add_argument("--only", nargs="+", help="business ids to generate")
    g.add_argument("--force", action="store_true", help="overwrite existing files")
    g.set_defaults(func=cmd_generate)
    c = sub.add_parser("check", help="fix fake phones and list warnings in the JSON files")
    c.set_defaults(func=cmd_check)
    ld = sub.add_parser("load", help="load business JSON files into SQLite")
    ld.add_argument("--db", help="database path (default: DB_PATH)")
    ld.set_defaults(func=cmd_load)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
