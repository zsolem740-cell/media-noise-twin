#!/usr/bin/env python3
"""Szintetikus hírlista az előnézethez. Minden cím kitalált, minden forrás kitalált (.example domain);
a pontozást a valódi motor számolja (src.core.atm_engine.build_history), de valódi hír, forrás vagy szavazat nem kerül bele.

  python3 preview/make_data.py KIMENET.json"""
import json
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.core import atm_engine as E                      # noqa: E402
from src.utils.config import BASE, load_config            # noqa: E402
from src.utils.time_helper import now_utc, to_iso_utc     # noqa: E402

# (cím, régió, forrás, hány órája)
HEADLINES = [
    ("Ülésezett a megyei közgyűlés Szombathelyen, elfogadták a jövő évi költségvetést", "HU-VA", "vasi-hirmuhely.example", 1),
    ("SOKKOLÓ BOTRÁNY!!! Elképesztő, ami a szombathelyi piacon történt, nem fogod elhinni", "HU-VA", "vasi-pletyka.example", 2),
    ("Lezárják a főút egy szakaszát Körmenden a hétvégén a felújítás miatt", "HU-VA", "vasi-hirmuhely.example", 3),
    ("Új kerékpárút épül Kőszeg és Sárvár között, jövő tavasszal adják át", "HU-VA", "alpokalja-naplo.example", 4),
    ("Ezt látnod kell: így néz ki most a celldömölki vasútállomás!", "HU-VA", "vasi-pletyka.example", 5),
    ("Tájékoztató a hulladékszállítás megváltozott rendjéről Vasváron", "HU-VA", "alpokalja-naplo.example", 6),
    ("Megnyílt a felújított könyvtár Szentgotthárdon, hétfőtől újra várja az olvasókat", "HU-VA", "alpokalja-naplo.example", 7),
    ("Rendkívüli!!! Titokzatos fények az őrségi erdő felett, a helyiek rettegnek", "HU-VA", "vasi-pletyka.example", 9),
    ("Szeptembertől két új buszjárat indul Sárvár és Szombathely között", "HU-VA", "vasi-hirmuhely.example", 11),
    ("A kőszegi iskola diákjai nyerték a megyei matematikaversenyt", "HU-VA", "alpokalja-naplo.example", 13),
    ("Hűvös, borult idő várható a hétvégén, délután eső is eshet", "HU-VA", "idojaras-szolgalat.example", 3),
    ("Országos ülésezett a parlament, megszavazták a költségvetési törvényt", "HU-NAT", "orszagos-kronika.example", 2),
    ("BOTRÁNY! Durva, amit a budapesti metrón láttak az utasok, ezt látnod kell", "HU-NAT", "friss-villam.example", 3),
    ("Megjelent a havi inflációs adat, a fogyasztói árak az előrejelzés körül alakultak", "HU-NAT", "orszagos-kronika.example", 4),
    ("Debrecenben átadták az új sportcsarnokot, az első mérkőzést szombaton rendezik", "HU-NAT", "orszagos-kronika.example", 5),
    ("Elképesztő fordulat!!! Nem fogod elhinni, mi lett a szegedi lottónyertessel", "HU-NAT", "friss-villam.example", 6),
    ("Pécsett folytatódik a belváros felújítása, a forgalmi változásokról térkép készült", "HU-NAT", "orszagos-kronika.example", 7),
    ("Győrben megnyitották az idei karácsonyi vásárt, a programok a hónap végéig tartanak", "HU-NAT", "orszagos-kronika.example", 8),
    ("Tragédia és pánik a miskolci bevásárlóközpontban?! Dermesztő felvételek terjednek", "HU-NAT", "friss-villam.example", 10),
    ("Kecskeméten csökken a lakossági vízdíj a jövő évtől", "HU-NAT", "orszagos-kronika.example", 12),
    ("Veszprém és Székesfehérvár között felújítják a vasúti pályát, módosul a menetrend", "HU-NAT", "orszagos-kronika.example", 14),
    ("Eger: megújult a vár egyik kiállítótere, kedvezményes belépő a hétvégén", "HU-NAT", "orszagos-kronika.example", 15),
    ("Közlekedési baleset Oberwart mellett, a mentők percek alatt a helyszínen voltak", "AT-1", "burgenland-bote.example", 3),
    ("Neues Radwegenetz in Eisenstadt: Gemeinderat beschließt den Ausbau", "AT-1", "burgenland-bote.example", 5),
    ("SCHOCK in Güssing!!! Unglaublich, was Anrainer in der Nacht gesehen haben", "AT-1", "burgenland-klatsch.example", 6),
    ("Wetterdienst: Nebel am Morgen, am Nachmittag Aufheiterung im Burgenland", "AT-1", "idojaras-szolgalat.example", 8),
    ("Mattersburg: Schulstart mit neuen Lehrkräften und erweitertem Angebot", "AT-1", "burgenland-bote.example", 10),
    ("Skandal in Neusiedl: Das müssen Sie sehen, wahnsinn was jetzt bekannt wurde", "AT-1", "burgenland-klatsch.example", 12),
    ("Občina Murska Sobota sprejela proračun za prihodnje leto", "SI-1", "pomurski-glas.example", 4),
    ("Lendava: nova avtobusna povezava med mestom in okoliškimi vasmi", "SI-1", "pomurski-glas.example", 7),
    ("ŠOK v Ljutomeru! Neverjetno, kaj so našli v gozdu, to morate videti", "SI-1", "pomurski-trac.example", 9),
    ("Vreme: oblačno, popoldne možne padavine v Prekmurju", "SI-1", "idojaras-szolgalat.example", 11),
    ("Gornja Radgona obnavlja most čez Muro, promet bo omejen do konca meseca", "SI-1", "pomurski-glas.example", 14),
    ("City council approves next year's transport budget after a long session", "INT", "world-ledger.example", 2),
    ("SHOCKING: You won't believe what this airline did to a family of four!!!", "INT", "daily-blare.example", 3),
    ("Scientists publish new measurements of ocean temperatures across the Atlantic", "INT", "world-ledger.example", 5),
    ("Chaos and outrage as stunning bombshell rocks the football world", "INT", "daily-blare.example", 6),
    ("Central bank holds interest rates steady, citing stable inflation", "INT", "world-ledger.example", 8),
    ("Museum reopens after two years of renovation with a new exhibition on rail travel", "INT", "world-ledger.example", 10),
    ("Terrifying footage: jaw-dropping meltdown at a downtown cafe goes viral!", "INT", "daily-blare.example", 12),
    ("Grid operator reports record solar output on Tuesday afternoon", "INT", "world-ledger.example", 13),
    ("Szombathelyen felavatták az új játszóteret a Szent Márton utcában", "HU-VA", "alpokalja-naplo.example", 16),
    ("Elképesztő!!! SZENZÁCIÓ a sárvári fürdőben, rengetegen kapják ezt a meglepetést", "HU-VA", "vasi-pletyka.example", 17),
    ("A rendőrség tájékoztatása szerint csökkent a lopások száma a megyében", "HU-VA", "alpokalja-naplo.example", 18),
    ("Őriszentpéteren szombaton gazdapiac lesz, helyi termelők kínálják portékáikat", "HU-VA", "alpokalja-naplo.example", 19),
    ("Zalaegerszegen megkezdődött a téli útkarbantartás előkészítése", "HU-NAT", "orszagos-kronika.example", 20),
    ("Nyíregyházán új ingyenes szűrőprogram indul az idősek számára", "HU-NAT", "orszagos-kronika.example", 21),
    ("Riasztó hír!!! Azonnal lépj, mert most érkezett a meglepő üzenet mindenkinek", "HU-NAT", "friss-villam.example", 22),
    ("Békéscsabán átadták a megújult főteret, a környéken változik a parkolás rendje", "HU-NAT", "orszagos-kronika.example", 23),
    ("Szolnokon a héten több helyen is munkavégzés lesz az úthálózaton", "HU-NAT", "orszagos-kronika.example", 24),
    ("Tatabánya: megkezdődött a lakótelepi parkok téli karbantartása", "HU-NAT", "orszagos-kronika.example", 26),
]


def build():
    cfg, _status = load_config(BASE, BASE.parent / "nincs_ilyen_user.json")
    now = now_utc()
    raw = []
    for i, (title, region, domain, hours) in enumerate(HEADLINES):
        raw.append({"id": f"pv{i:03d}", "title": title, "summary": "", "link": f"https://{domain}/hir/{i}",
                    "source": domain.split(".")[0].replace("-", " ").title(), "source_domain": domain, "region": region,
                    "published": to_iso_utc(now - timedelta(hours=hours, minutes=(i * 7) % 50))})
    return E.build_history(raw, [], cfg)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    out = build()
    Path(sys.argv[1]).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"{len(out['items'])} szintetikus hír → {sys.argv[1]}")
