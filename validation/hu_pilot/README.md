# Magyar emberi címkék pilotja (50 cím)

A pilot célja a **megvalósíthatóság** ellenőrzése (vak mód, szavazónkénti tárolás, magyar megjelenés, háromfokú skála érthetősége, kappa mérése, a Gemini és a Groq kimenetének összevethetősége), **nem** a pontosság mérése.
A modul csak a hírmentést olvassa (`data/metrics/atm_history.json`, módosítás nélkül), kizárólag a `results/` mappába ír (git nem követi), modellt és hálózatot nem használ.
A Webis-modultól (`validation/webis_validation`) független; nem importál belőle, és a v1/v2/v3 promptokhoz nem nyúl.

## Felépítés
- 50 cím: **20 horgony** (kalibrációs kör) + **30 mérési** (15 véletlen + 15 formai jegyekkel dúsított: `!`, NAGYBETŰS szó, `?`, idézőjel). A kettőspont szándékosan nem dúsító jegy (a mentés magyar címeinek ~36%-ában van).
- Szűrés: nem hivatalos/riasztás tétel, 25–160 karakter, a felület nyelvfelismerése a forrás-domain nélkül is magyarnak mondja, nincs pontos vagy közel-duplikátum (Jaccard ≥ 0,7), egy forrásból összesen legfeljebb 5 cím.
- A pilot-feed fájlok semlegesek: nincs szabály- vagy AI-pontszám, valódi forrás, hely, link. A cím és az azonosító változatlan. Az alkalmazás működéséhez a hírmentés `model` mezője (szabály- és súlykonfiguráció, nincs benne hír) szó szerint bekerül, a többi felső szintű mező (summary, insights, notified, config, research) szerkezethű, de nullázott. Egy üres `model` hibát okoz az appban (helyi füstpróba találta meg).

## Szerepek és menet
Szavazók: A, B (elsődleges pár), C (harmadik szavazat az eltéréseknél), D (tartalék). A koordinátor nem látja előre a mérési címeket.
1. `select` → `results/`: `pilot_stage1_anchors.json`, `pilot_stage2_measured.json`, `anchor_preview.txt` (csak a horgonyok), `selection.json`. A horgonyokat a koordinátor jóváhagyja; felülírás: `results/anchors_override.json` (azonosítók listája), majd a kiválasztás törlése és újrafuttatása.
2. Horgonykör: a szavazók vakon, külön címkéznek a stage1 feeddel; a megbeszélés előtti egyezés csak tájékoztató.
3. Kalibrációs megbeszélés (a koordinátor feljegyzése, nem szavazat).
4. Mérési kör: a stage2 feeddel, vakon, külön.
5. `analyze` → kappa (lineárisan súlyozott és sima), egyezés, Krippendorff-alfa, kapu. `adjudication` → `pilot_stage3_adjudication.json` az eltérő mérési címekkel a harmadik szavazathoz.
6. `freeze`: csak akkor, ha a kapu **átment** (súlyozott κ ≥ 0,5) vagy **eldönthetetlen** (a pontbecslés < 0,5, de a 95%-os bootstrap-intervallum felső határa ≥ 0,5). A lezárási jegyzék a modellfuttatás feltétele.
7. Referencia: a mérési címek szavazatainak átlaga (`human_reference.csv`, 0–2).

## Modellfuttató (mérési futás, kódban kész, de nincs belőle parancssori futtatás)
`modelrun.run_measurement` egy szolgáltatóra, egy cím egy kérésben, **hamis vagy kívülről kapott átvitellel** fut; a modulban hálózati kód és kulcs-olvasás nincs. A parancssorban csak `model-dryrun gemini|groq` van (a 50 kérés előállítása és ellenőrzése, kulcs és hálózat nélkül).
- **Közös prompt és séma:** a prompt az eddigi Gemini-ág alap-szabályszövege szó szerint (hash `c634bdcc…`), a séma ugyanaz a négy jel span/reason/score szerkezettel, 0–2 pont; a Groq ugyanezt `json_schema` alakban kapja (azonos mezők és pontozás). A Gemini-kérés hash-e egyezik a meglévő Gemini-ágéval. A v1–v3 Groq-promptokhoz nem nyúl.
- **Kapu:** csak érvényes lezárási jegyzékkel (`freeze_manifest.json`) és a lezárt címlistával indul; a referencia és az exportok megváltozása a kaput újra elzárja.
- **Failover:** mérési futáson nincs váltás (a modul egyetlen átvitelt ismer, a konfigurációban a failover nem kapcsolható be). A Groq csak akkor fut, ha önállóan, elsődlegesként választod.
- **Napi kvóta kimerülése:** a futás megáll, a kész címek megmaradnak, a nem küldöttek függőben maradnak; a folytatás ideje a visszaállás + 5 perc (Gemini: éjfél `America/Los_Angeles`, Groq: 00:00 UTC; felhasználói megadás, hivatalos forrásból nem ellenőrzött). A folytatás kézi vagy időzített, az első kérés próba, kvótanaponként legfeljebb 3 próba, a kész címeket nem küldi újra.
- **Percenkénti 429, időtúllépés, 5xx, üres/érvénytelen/csonka JSON, blokkolás:** nem vált és nem állít le napra; újrapróba ugyanazon, hiba esetén rögzítés. Számlázási vagy hitelesítési hibánál megáll.
- **Naplózás:** `results/model_runs/<futás>/` alatt `log.jsonl` (minden kérésnél szolgáltató, kért és visszaadott modell, kulcs-azonosító NÉV, kimenetel, tokenek), `quota_stops.jsonl`, `scores.jsonl`, `results.csv` (`provider`, `model` oszlop), `summary.json` (`failover_allowed: false`, `providers_used`). Kulcs sehol nincs.

## Adatkezelés
A szavazói exportok valódi tesztelői adatok: nem kerülnek a repóba. A külső API-nak csak a címszöveg mehet.

## Helyi füstpróba (v47.10 ág, fejtetlen böngésző, 390 px)
A horgony-feeddel, két szavazóval (A, B) lefutott: vak mód (nincs pontszám, forrás, AI-szöveg a felületen), a szavazónkénti tárolás (A és B külön látja a 20 címet, a kihagyás és a visszavonás helyes), megmaradás újratöltés után, a „Minden szavazó mentésének másolása”, a magyar megjelenés (ő, ű, „ ”, vízszintes túlcsordulás nincs). A kapott export a Python-elemzőn átmegy; az alkalmazás saját kappája (csak Nyugodt/Hangos, a „Közepes”-t figyelmen kívül hagyja) egyezik a független kétosztályos számítással. A háromosztályos súlyozott kappát csak ez a modul számolja.
Ismert apróságok: a gyorsszavazó fejléce a termelési számlálókat mutatja („Értékelő sor 0/300 · clickbait 0/40”); a szavazat-rekord az app belső tanulójának értékeit (`S`, `sAi`) is tárolja (nem látszanak). Nem tesztelt: szervizmunkás (service worker) https alatt, valódi telefon, hosting.
