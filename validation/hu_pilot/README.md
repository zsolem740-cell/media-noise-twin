# Magyar emberi címkék pilotja (50 cím)

A pilot célja a **megvalósíthatóság** ellenőrzése (vak mód, szavazónkénti tárolás, magyar megjelenés, háromfokú skála érthetősége, kappa mérése, a Gemini és a Groq kimenetének összevethetősége), **nem** a pontosság mérése.
A modul csak a hírmentést olvassa (`data/metrics/atm_history.json`, módosítás nélkül), kizárólag a `results/` mappába ír (git nem követi), modellt és hálózatot nem használ.
A Webis-modultól (`validation/webis_validation`) független; nem importál belőle, és a v1/v2/v3 promptokhoz nem nyúl.

## Felépítés
- 50 cím: **20 horgony** (kalibrációs kör) + **30 mérési** (15 véletlen + 15 formai jegyekkel dúsított: `!`, NAGYBETŰS szó, `?`, idézőjel). A kettőspont szándékosan nem dúsító jegy (a mentés magyar címeinek ~36%-ában van).
- Szűrés: nem hivatalos/riasztás tétel, 25–160 karakter, a felület nyelvfelismerése a forrás-domain nélkül is magyarnak mondja, nincs pontos vagy közel-duplikátum (Jaccard ≥ 0,7), egy forrásból összesen legfeljebb 5 cím.
- A pilot-feed fájlok semlegesek: nincs szabály- vagy AI-pontszám, valódi forrás, hely, link. A cím és az azonosító változatlan.

## Szerepek és menet
Szavazók: A, B (elsődleges pár), C (harmadik szavazat az eltéréseknél), D (tartalék). A koordinátor nem látja előre a mérési címeket.
1. `select` → `results/`: `pilot_stage1_anchors.json`, `pilot_stage2_measured.json`, `anchor_preview.txt` (csak a horgonyok), `selection.json`. A horgonyokat a koordinátor jóváhagyja; felülírás: `results/anchors_override.json` (azonosítók listája), majd a kiválasztás törlése és újrafuttatása.
2. Horgonykör: a szavazók vakon, külön címkéznek a stage1 feeddel; a megbeszélés előtti egyezés csak tájékoztató.
3. Kalibrációs megbeszélés (a koordinátor feljegyzése, nem szavazat).
4. Mérési kör: a stage2 feeddel, vakon, külön.
5. `analyze` → kappa (lineárisan súlyozott és sima), egyezés, Krippendorff-alfa, kapu. `adjudication` → `pilot_stage3_adjudication.json` az eltérő mérési címekkel a harmadik szavazathoz.
6. `freeze`: csak akkor, ha a kapu **átment** (súlyozott κ ≥ 0,5) vagy **eldönthetetlen** (a pontbecslés < 0,5, de a 95%-os bootstrap-intervallum felső határa ≥ 0,5). A lezárási jegyzék a modellfuttatás feltétele.
7. Referencia: a mérési címek szavazatainak átlaga (`human_reference.csv`, 0–2).

## Modellrész (még nincs kódolva)
A Gemini és a Groq futtatása csak `freeze.require_freeze` sikere után indulhat. Mindkettő ugyanazt kapja: az alap-szabályszöveg szó szerint, egy cím egy kérésben, a négy jel 0–2 ponttal, ugyanaz a séma. Ez külön, jóváhagyandó lépés.

## Adatkezelés
A szavazói exportok valódi tesztelői adatok: nem kerülnek a repóba. A külső API-nak csak a címszöveg mehet.
