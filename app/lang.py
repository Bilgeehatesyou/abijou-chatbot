"""Which language a message is in: Mongolian, English or Korean.

Hangul -> Korean, Cyrillic -> Mongolian, Mongolian typed in Latin letters ->
Mongolian, other Latin text -> English. Short words like "ok" or "hi" don't
tell us anything, so the conversation keeps its language.
"""
import re
from typing import Optional

LANGS = ("mn", "en", "ko")
DEFAULT_LANG = "mn"

AMBIGUOUS_LATIN = {"hi", "hello", "hey", "ok", "okay", "k", "thanks", "thx", "bye",
                   "yes", "no", "yep", "lol", "pls", "please", "sorry", "wow", "rejuran",
                   "neobeam", "gold", "ptt", "excel", "botox", "ldm", "pico", "laser"}

# Common words when Mongolian is typed in Latin letters.
LATIN_MN = {
    "sain", "sn", "bainuu", "bnuu", "bnu", "baina", "bna", "bn", "uu", "yu", "ve", "we",
    "hed", "hediin", "hediig", "haana", "hezee", "hen", "une", "vne", "unetei", "tulbur",
    "tolbor", "tsag", "tsagt", "tsagiin", "bolno", "bolomj", "bolohuu", "zahialga",
    "zahialah", "zahialj", "hayag", "bairshil", "utas", "dugaar", "medeelel", "avah",
    "awah", "avmaar", "heregtei", "baigaa", "bga", "bgaa", "bdag", "baidag", "yaj",
    "yaaj", "tanai", "tanaid", "manai", "ta", "bid", "emneleg", "emch", "emchilgee",
    "hyamdral", "hymdral", "ajilladag", "ajillah", "odor", "udur", "margaash",
    "unuudur", "onoodor", "bayarlalaa", "bayrlalaa", "zaa", "tegvel", "tegwel",
    "yamar", "batga", "batgatai", "arisnii", "arisand", "ulailt", "ulaan", "tolbo", "sevh",
    "nuur", "nuuriin", "hatsar", "lazer", "lazeer", "uvduh", "solongos", "solongost",
    "salbar", "salbart", "mongol", "hungulult", "jiremsen", "urevsel", "heden", "udaa",
}


def detect_lang(text: str) -> Optional[str]:
    """'mn', 'en', 'ko', or None when the text doesn't tell us."""
    if re.search(r"[가-힣ᄀ-ᇿ㄰-㆏]", text):
        return "ko"
    if re.search(r"[Ѐ-ӿ]", text):
        return "mn"
    words = re.findall(r"[a-zA-Z]+", text.lower())
    if not words:
        return None
    if any(w in LATIN_MN for w in words):
        return "mn"
    if all(w in AMBIGUOUS_LATIN for w in words):
        return None
    return "en"
