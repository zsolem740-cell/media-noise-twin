"""HTML tisztítás és kattintásvadász jelek számlálása (HU/DE/SL)."""
import html
import re

from bs4 import BeautifulSoup

# Szó eleji (prefix) egyezés; kerüljük a gyakori szavak töveit (pl. 'sokk' -> 'sokkal').
CLICKBAIT = [
    # HU
    "sokkoló", "döbbenet", "elképesztő", "brutális", "megdöbbentő", "vérfagyasztó",
    "tragédia", "borzalmas", "szörnyű", "botrány", "pánik", "rendkívüli", "riasztó",
    "nem fogod elhinni", "ezt látnod kell", "most érkezett", "azonnal", "titok", "durva",
    # DE
    "schock", "skandal", "unfassbar", "wahnsinn", "dramatisch", "horror", "sensation",
    "das müssen sie sehen", "panik", "brutal",
    # SL
    "šok", "škandal", "neverjetno", "grozljivo", "senzacija", "panika", "pretresljivo",
    # EN
    "shock", "outrage", "slams", "slammed", "bombshell", "meltdown", "chaos", "horrif",
    "terrifying", "terrified", "stunning", "unbelievable", "you won't believe", "jaw-dropping",
    "scandal", "furious", "nightmare", "devastat", "brutal", "panic",
]
_CB_RE = [re.compile(r"(?<!\w)" + re.escape(k)) for k in CLICKBAIT]
_BASE_N = len(CLICKBAIT)
_WS = re.compile(r"\s+")
_WORD = re.compile(r"[^\W\d_]{3,}", re.UNICODE)


def strip_html(raw: str | None) -> str:
    if not raw:
        return ""
    text = BeautifulSoup(raw, "html.parser").get_text(" ", strip=True)
    return _WS.sub(" ", html.unescape(text)).strip()


def strip_source_suffix(title: str, source: str | None) -> str:
    """A Google News cím végéről leveszi a ' - Forrás' utótagot."""
    if source and title.endswith(" - " + source):
        return title[: -(len(source) + 3)].strip()
    return title


def clickbait_hits(text: str) -> int:
    low = text.lower()
    return sum(1 for rx in _CB_RE if rx.search(low))


def exclamation_count(text: str) -> int:
    return text.count("!")


def caps_ratio(text: str) -> float:
    """A min. 3 betűs szavak közül a csupa nagybetűsek aránya."""
    words = _WORD.findall(text)
    if not words:
        return 0.0
    return sum(1 for w in words if w.isupper()) / len(words)


def norm_title(title: str) -> str:
    """Összehasonlításhoz: kisbetű, betűk és számjegyek, egy szóköz (a számok különböző híreket jelölhetnek)."""
    return " ".join(re.findall(r"[^\W_]+", title.lower()))


def set_extra_keywords(extra: list[str]) -> None:
    """Saját kulcsszavak (config/user.json: clickbait_add); ismételt hívásnál lecseréli az előzőt."""
    del CLICKBAIT[_BASE_N:]
    del _CB_RE[_BASE_N:]
    for k in extra:
        k = str(k).strip().lower()
        if k and k not in CLICKBAIT:
            CLICKBAIT.append(k)
            _CB_RE.append(re.compile(r"(?<!\w)" + re.escape(k)))
