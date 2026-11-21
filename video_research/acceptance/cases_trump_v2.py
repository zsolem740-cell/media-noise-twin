"""Valós átirat, YouTube-szöveggel: a trump-v2 esetkészlet (VERZIÓZOTT; a trump-v1 készlet és kiértékelője érintetlen).

Forrás: a "The Truth About Trump's Tariffs" (YouTube, video_id AfVGUiet39E, 2025-02-18) KÉZI angol feliratsávjának (en-US) utolsó szakasza, 4:09-től a végéig. Ez szó szerint
megegyezik a Robert Reich-féle Short ("Who Pays For Trump's Tariffs?", VQlVj-X-xFs, 2025-03-04) beszélt szövegével (a Short a hosszú videó végéből vágott klip; a képet nem hasonlítottuk össze).
Lekérés: 2026-11-21, a Firecrawl 'youtube-com' szolgáltatóval; a szegmensidők a hosszú videó abszolút másodpercei. A szöveg uploader-szerkesztett felirat, NEM automatikus (ASR) felirat.
Az importáló szerinti eredet: `user_provided_transcript` (az importáló csak ezt ismeri; a valódi eredet fent).

ÁLLAPOT: JÓVÁHAGYOTT ELVÁRÁSOK, lefagyasztva. A felhasználó 2026-11-21-én jóváhagyta az expectations_v2_DRAFT.md 4. átdolgozását (SHA-256 2b45…1158, lásd EXPECTATIONS_DRAFT_SHA256 és a
frozen/expectations_trump_v2.md bájtazonos másolatot), a dokumentált megvalósítási korlátokkal együtt. Ez az elvárások tartalmi jóváhagyása; NEM a kód független ellenőrzése és NEM egy modellfutás sikere.
A hard_ok nem jelent tartalmi megfelelést, az emberi felülvizsgálat követelménye érvényben marad. Élesen futtatni külön futásjóváhagyás (azonosító, modell, kérés-, token- és időkeret) és külön
engedélyezett bekötés nélkül nem szabad.
Ez a modul NEM futásengedély, és nincs bekötve az éles futásvezérlőbe (`live.py`).

A v1-hez képest: egyetlen eset (YouTube kézi szöveg); az idézet-kifejezések a számok YouTube-féle írásmódjára ($1,200, $4,000, 25%); a forrásban valódi időbélyegek vannak
(a kiértékelő ellenőrzi őket); nincs levágott vég és nincs fejléc; az L1 szigorúbb (lásd eval_trump_v2).
"""
from __future__ import annotations

import hashlib

CASE_SET_VERSION = "trump-v2"
APPROVAL_STATUS = "approved_frozen"
EXPECTATIONS_DRAFT_SHA256 = "2b4596962b7c30465deec0f5ce1bb690667bdc1fc5cc605ab5527e5e03c01158"        # a jóváhagyott 4. átdolgozás lenyomata (a mező neve történeti; a dokumentum már jóváhagyott)
SOURCE = {"platform": "youtube", "video_id": "AfVGUiet39E", "track": "manual en-US", "passage": "4:09 - end", "retrieved": "2026-11-21",
          "short_video_id": "VQlVj-X-xFs", "relation_to_short": "verbatim text match; not image-verified"}

# (start_ms a hosszú videóban, duration_ms, szöveg) - a kézi felirat szegmensei szó szerint
SEGMENTS = [
    (249082, 2460, "In addition to more tariff hikes on China,"),
    (251542, 6632, "he plans to levy 25% tariffs on everything from Canada and Mexico too."),
    (258174, 8425, "These new tariffs would cost the typical American household an additional $1,200 in 2025."),
    (266599, 2336, "But if Trump makes good on previous pledges"),
    (268935, 2502, "to slap tariffs on imports from every country,"),
    (271437, 5548, "American families can expect to spend as much as $4,000 more."),
    (276985, 3837, "Trump has suggested he would use the revenue from tariffs"),
    (280822, 4504, "to “offset” more tax cuts for the rich and big corporations."),
    (285326, 3921, "But of course, as I said, any revenue raised from tariffs"),
    (289247, 1835, "would be coming out of your pocket."),
    (291082, 4171, "The tariffs you pay could help facilitate this massive"),
    (295253, 4212, "transfer of wealth from most Americans to the super rich."),
    (299465, 4588, "So when you’re paying more for groceries, gas, and housing,"),
    (304053, 6131, "know where your money is really going and know whom to blame."),
]
LINES = [t for _s, _d, t in SEGMENTS]
STARTS_S = [s / 1000.0 for s, _d, _t in SEGMENTS]
TEXT = "\n".join(LINES)
TEXT_SHA256 = "fc8c8a03deb79e8ce8bbd29993559ead6253a09f94119d77a06ab8ca2d87abe5"   # a bemeneti szöveg lenyomata a szegmensek "\n"-nel összefűzve; a teszt hasonlítja (véletlen módosítás jelzése)


def text_sha256(text: str = TEXT) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _ts(ms: int) -> str:
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms_ = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms_:03d}"


def to_srt_real() -> str:
    """SRT a forrás VALÓDI időbélyegeivel (nem a futtató szintetikus 6 s-os rácsával)."""
    return "\n\n".join(f"{i}\n{_ts(s)} --> {_ts(s + d)}\n{t}" for i, (s, d, t) in enumerate(SEGMENTS, 1)) + "\n"


QUESTION = "Ki fizeti az új vámokat, és mekkora költséget állít a beszélő az amerikai háztartásokra, milyen feltételekkel?"

# normalizált (kisbetű, írásjel nélküli; a '$1,200' -> '1 200', a '25%' -> '25') kifejezések; mindnek szerepelnie kell az alátámasztó idézetek együttes szövegében
EXPECTED = [
    dict(id="E1", what_hu="25%-os vám a Kanadából és Mexikóból érkező árukra, és további emelés Kínára",
         condition_hu="Terv, nem életbe lépett. Hatókör: a Kanada és Mexikó felől érkező áruk, nem minden ország.",
         anchors={"en": ["25 tariffs on everything from canada and mexico"]}),
    dict(id="E2", what_hu="a tipikus amerikai háztartásnak plusz 1200 dollár",
         condition_hu="Feltételes ('would cost'), 2025-re, az E1 vámjaira.",
         anchors={"en": ["additional 1 200 in 2025"]}),
    dict(id="E3", what_hu="akár 4000 dollár, ha minden országra vámot vetnek ki",
         condition_hu="Kettős feltétel: korábbi ígéretek beváltása és felső határ ('as much as'). Külön marad az E2-től; a 2025 nem vihető át ide (az E3 idézetében nincs).",
         anchors={"en": ["as much as 4 000 more"]}),
    dict(id="E4", what_hu="a vám költségét az amerikaiak viselik",
         condition_hu="A beszélő állítása; a hosszú videóban szemléltető példa támasztja alá, forrás nélkül.",
         anchors={"en": ["coming out of your pocket"]}),
    dict(id="E5", what_hu="Trump a vámbevételt adócsökkentések ellentételezésére javasolta/jelezte (gazdagok, nagyvállalatok)",
         condition_hu="Szándék, nem döntés ('has suggested'); az 'offset' a forrásban idézőjelben áll.",
         anchors={"en": ["use the revenue from tariffs"]}),
]
LEAD_L1 = dict(id="L1", what_hu="honnan van az 1200 és a 4000 dolláros becslés (ki, milyen módszerrel számolta)",
               condition_hu="A szöveg (és a videó leírása) forrást nem nevez meg. A nyom a MODELLTŐL kell jöjjön (megnevezett hiányzó ellenőrzéssel és kérdéssel); "
                            "a rendszer által automatikusan képzett minősítő-nyom (a következő 'But…' mondat miatt) nem elég.",
               anchors_any=["E2", "E3"])
NOISE = {"en": ["massive transfer of wealth", "super rich", "where your money is really going", "know whom to blame"]}


def _case() -> dict:
    return dict(id="TRUMP_C_yt_manual", title="Trump-vámok: YouTube kézi angol felirat (a Short szövege, 4:09-től a hosszú videó végéig)", question=QUESTION, lang="en", fmt="srt",
                segments=LINES, srt=to_srt_real(), starts_s=STARTS_S, version=CASE_SET_VERSION, expected=EXPECTED, lead=LEAD_L1, noise=NOISE["en"], source=SOURCE,
                timestamps_null=False)


CASES = [_case()]
