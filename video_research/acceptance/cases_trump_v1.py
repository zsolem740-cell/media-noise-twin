"""Valós, felhasználó által megadott átirat (Trump-vámok videó): kétnyelvű esetkészlet, VERZIÓZOTT és külön lefagyasztott (trump-v1).

Az elvárások forrása a felhasználó által jóváhagyott, lefagyasztott szöveg (expectations_v1.md, SHA-256: lásd FROZEN_EXPECTATIONS_SHA256).
Ez a modul az elvárások gépi leírása; nem módosítható a futás eredménye alapján. Hibás elvárás esetén új verzió (trump-v2) kell új jóváhagyással.
A meglévő `cases.py` (LIVE-G36F-3C-001 lefagyasztott készlete) és a `runner.py` érintetlen.

Ez a modul NEM futásengedély, és nincs bekötve az éles futásvezérlőbe (`live.py`): a hamisító modellel futtatható, a valódi modellhez külön jóváhagyás és bekötés kell.

Az elvárások megfogalmazása szándékosan nem szegmens-, hanem KIFEJEZÉS-alapú: a szegmentálás (bekezdés/sor, 400 karakteres darabolás) a nyelvtől és a tördeléstől függ,
az elvárt tétel viszont a forrásszöveg egy adott helyéhez kötődik. A `anchors` azt adja meg, mely (normalizált) szövegrészeknek kell együtt szerepelniük a megtartott
tétel alátámasztó idézetében, hogy a tétel az adott elvárásra tekinthető. A tartalmi megfelelést (jelentés, hatókör, feltétel) NEM ez dönti el: az emberi megítélés.
"""
from __future__ import annotations

import hashlib

# A lefagyasztott elvárásfájl lenyomata (a futás előtt rögzítve, 2026-11-21). A fájl maga ideiglenes munkakönyvtárban volt; a szövegek lenyomata alább külön is rögzítve.
FROZEN_EXPECTATIONS_SHA256 = "3adfa04c909047741a5dd7d28c0256543444d6009262d225486b58fbeaeef83a"
CASE_SET_VERSION = "trump-v1"

TEXT_A = (
    "In addition to more tariff hikes on China, he plans to levy twenty-five percent tariffs on everything from Canada and Mexico too. "
    "These new tariffs would cost the typical American household an additional one thousand two hundred dollars in 2025. "
    "But if Trump makes good on previous pledges to slap tariffs on imports from every country, American families can expect to spend as much as four thousand dollars more. "
    "Trump has suggested he would use the revenue from tariffs to offset more tax cuts for the rich and big corporations. "
    "But of course, as I said, any revenue raised from tariffs would be coming out of your pocket. "
    "The tariffs you pay could help facilitate this massive transfer of wealth from most Americans to the super-rich. "
    "So when you're paying more for groceries, gas, and housing, know where your money is really going, and know whom-"
)

LINES_B = [
    "A Kínával szembeni további vámemelések mellett 25 százalékos vámot tervez kivetni mindenre.",
    "Kanadából és Mexikóból is. Ezek az új vámok egy átlagos amerikai háztartásnak sokba kerülnének.",
    "további ezerkétszáz dollár 2025-ben. De ha Trump betartja korábbi ígéreteit",
    "ha minden országból vámot vetnek ki az importra, az amerikai családok várhatóan annyit költenek majd,",
    "négyezer dollárral több. Trump azt javasolta, hogy a vámokból származó bevételt arra fordítsa, hogy",
    "ellensúlyozza a gazdagok és nagyvállalatok adócsökkentéseinek növekedését. De természetesen, ahogy mondtam, minden bevétel",
    "A vámokból származó bevétel a te zsebedből jönne ki. A befizetett vámok segíthetnének",
    "ez a hatalmas vagyonátadás a legtöbb amerikaitól a szupergazdagokhoz. Tehát amikor fizetsz",
    "többet élelmiszerre, benzinre és lakhatásra, tudd, hogy mire megy valójában a pénzed, és tudd, hogy kinek...",
]
TEXT_B = "\n".join(LINES_B)

# A fájlból kivett bemeneti szakaszok lenyomata (a lefagyasztáskor számolva): a szövegek véletlen módosítását jelzi.
TEXT_SHA256 = {
    "A": "acd61a58053cf234c10c20671d8e91dd64791d19bb6ff295e05e703619f952a4",
    "B": "2b849b40ec08cd4c826e82b820ca128e18a1494eda8d292c4c31f6b7471a121a",
}

QUESTION = "Ki fizeti az új vámokat, és mekkora költséget állít a beszélő az amerikai háztartásokra, milyen feltételekkel?"


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- Elvárt tételek (E1–E5, L1). `anchors`: nyelvenként a normalizált (kisbetű, írásjel nélküli) kifejezések, amelyeknek MIND szerepelniük kell az alátámasztó idézetek együttes szövegében.
# `condition_hu`: a lefagyasztott szöveg szerinti megőrzendő feltétel/határ (az emberi értékeléshez; a gép nem ebből dönt).
EXPECTED = [
    dict(id="E1", what_hu="25%-os vám a Kanadából és Mexikóból érkező árukra, és további emelés Kínára",
         condition_hu="Terv, nem életbe lépett. Hatókör: a Kanada és Mexikó felől érkező áruk, nem minden ország.",
         anchors={"en": ["twenty five percent tariffs", "canada and mexico"], "hu": ["25 százalékos vámot", "kanadából és mexikóból"]}),
    dict(id="E2", what_hu="a tipikus amerikai háztartásnak plusz 1200 dollár",
         condition_hu="Feltételes (would / kerülnének), 2025-re, az E1 vámjaira.",
         anchors={"en": ["one thousand two hundred dollars"], "hu": ["ezerkétszáz dollár"]}),
    dict(id="E3", what_hu="akár 4000 dollár, ha minden országra vámot vetnek ki",
         condition_hu="Kettős feltétel: korábbi ígéretek beváltása és felső határ (as much as). Külön marad az E2-től.",
         anchors={"en": ["four thousand dollars"], "hu": ["négyezer dollár"]}),
    dict(id="E4", what_hu="a vám költségét az amerikaiak viselik",
         condition_hu="A beszélő állítása, forrás nélkül.",
         anchors={"en": ["coming out of your pocket"], "hu": ["a te zsebedből jönne ki"]}),
    dict(id="E5", what_hu="Trump a vámbevételt adócsökkentések ellentételezésére javasolta/jelezte (gazdagok, nagyvállalatok)",
         condition_hu="Szándék, nem döntés (has suggested / javasolta).",
         anchors={"en": ["use the revenue from tariffs"], "hu": ["vámokból származó bevételt arra fordítsa"]}),
]
# L1: nyom ellenőrzésre: honnan van az 1200 és a 4000 dolláros becslés. Teljesül, ha van olyan LEAD besorolású tétel, amelynek alátámasztó idézete az E2 vagy az E3 kifejezéseit tartalmazza,
# és van ellenőrzési kérdése. (Lehet maga az E2/E3 tétel is.) A rögzített elvárás az E1–E5 vödrét nem írja elő: keep és lead is elfogadott, a kihagyás (szűrési napló) hiány.
LEAD_L1 = dict(id="L1", what_hu="honnan van az 1200 és a 4000 dolláros becslés (ki, milyen módszerrel számolta)",
               condition_hu="A szöveg forrást nem nevez meg. Ellenőrzési kérdés: ki és milyen módszerrel számolta.", anchors_any=["E2", "E3"])

# Zaj: csak felismerési segéd a „zaj önálló találatként" jelöléséhez (nem tartalmi ítélet). Normalizált kifejezések.
NOISE = {
    "en": ["massive transfer of wealth", "super rich", "where your money is really going", "know whom"],
    "hu": ["hatalmas vagyonátadás", "szupergazdag", "mire megy valójában", "tudd hogy kinek", "segíthetnének", "minden bevétel"],
}


def _case(cid: str, title: str, lang: str, lines: list[str]) -> dict:
    return dict(id=cid, title=title, question=QUESTION, lang=lang, fmt="text", segments=lines, version=CASE_SET_VERSION, expected=EXPECTED, lead=LEAD_L1, noise=NOISE[lang],
                timestamps_null=True)


CASES = [
    _case("TRUMP_A_en", "Trump-vámok: az angol átirat (a felhasználó által megadott szöveg)", "en", [TEXT_A]),
    _case("TRUMP_B_hu", "Trump-vámok: a magyar átirat (a felhasználó szerint az alkalmazás fordítása; a kapcsolat nem igazolt)", "hu", LINES_B),
]
