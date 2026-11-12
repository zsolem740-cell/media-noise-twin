# Mobilos előnézet

A Média-Zaj telefonos felületének új terve, az éles alkalmazástól elkülönítve. **Nem része az éles oldalnak**: a `preview/` mappát a workflow nem teszi közzé, a `public/` mappa változatlan.

## Összeállítás
```
python3 preview/build.py _preview --local     # helyi próbához (teljes HTML), majd: cd _preview && python3 -m http.server 8766
python3 preview/build.py _preview             # közzétételhez (az index.html csak tartalom, a keretet a közzététel adja)
```
Az előnézet az éles alkalmazás tényleges kódját használja. Az `app.js` és minden modul bájtra azonos a `public/` fájljaival (a pontozás, az AI, a kappa, az AUC és a tárolás is), három fájl kivételével, amelyeket a build kiír és a `tests/test_preview_build.py` ellenőriz:
- `js/modules/uiRenderer.js`: a mobilos megjelenítő (`preview/uiRenderer.js`). Ha a `public/` megfelelője változik, a build megáll, és át kell nézni.
- `js/modules/globe.js`, `globe3d.js`: ugyanaz a kód két ponton kibővítve, hogy vak módban a pontok egyszínűek és egyforma méretűek legyenek.

## Elkülönítés
- **Szintetikus adat:** a hírek kitaláltak, a forrásaik `.example` domainek; a pontozást a valódi motor számolja (`preview/make_data.py`). Valódi hír, forrás vagy szavazat nem kerül bele.
- **Külön eredet:** a közzétett előnézet külön címen fut, így a böngésző tárolója (IndexedDB, localStorage) sem közös az éles alkalmazással. A `guard.js` a `github.io` eredeten és a `/media-noise-twin/` útvonalon meg sem indul.
- Az előnézetben leadott szavazatok csak az adott böngészőben, az előnézet saját tárolójában vannak.

## Vak mód
Vak módban (alapállapot) a nem szavazott kártyán, a gyorsszavazóban, a Térkép fülön és a glóbusz felugró sávjában nincs pontszám, értékelő szín, AI-érték vagy magyarázat. A zaj szerinti rendezés és az ATM-korlát nem érhető el és nem hat; ha már be volt állítva, a vak módra váltás visszaállítja. A „Miért?” gomb (felirata: „megmutatja a számokat”) a korábbi viselkedés szerint feltárja a kártyát, és az utána leadott szavazat nem vak.
