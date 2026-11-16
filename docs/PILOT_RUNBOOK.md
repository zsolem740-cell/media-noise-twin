# Pilot futtatási kézikönyv (magyar címkék pilotja)

Összefoglaló a teljes pilot menetéről. A részletek forrása:
- telepítés: `validation/hu_pilot/docs/DEPLOY_CLOUDFLARE.md`
- szavazók: `validation/hu_pilot/docs/RATER_GUIDE.md`
- modul: `validation/hu_pilot/README.md`

Korlátok: lásd `CLAUDE.md` (nincs élő API-hívás, nincs 250 címes futás, nincs súlyozás, a v1/v2/v3 prompt nem módosul, a `results/` nem kerül a repóba).

## 1. Cloudflare Pages telepítés (Direct Upload)
1. Workers & Pages → új Pages projekt → Direct Upload (nem Git-összekötés).
2. Projektnév: semleges, nehezen kitalálható (pl. `mz-pilot-` + véletlen betűk).
3. Töltsd fel az `mz_pilot_stage1.zip`-et, telepítsd Production környezetbe.
4. Feltöltés előtt hasonlítsd össze a zip SHA-256 értékét a `stageN_manifest.json`-nal.
5. Csak a projekt fő URL-jét (`<projektnév>.pages.dev`) használjátok; az előnézeti URL másik origin, ott elvesznek a szavazatok.
6. Ellenőrzés: fejlécben `v47.10`; `atm_history.json` → `Cache-Control: no-store`; a lap → `X-Robots-Tag: noindex`.
7. Ne adj meg API-kulcsot, ne köss Git-et.

A pilot zipjeit a `validation/hu_pilot/packaging.py` készíti (ez teszi bele a `_headers` fájlt). A `scripts/kitchen_dispatch.py` csomagolója csak olyan mappán fut, amelyben már ott van az `index.html`, `_headers`, `manifest.json` és `sw.js`; a `public/` mappán `_headers` hiányában megáll (ez szándékos védelem). Kiadás előtti minőségkapu: `python scripts/kitchen_dispatch.py --web-dir <mappa> --dry-run`.

## 2. Horgonykör (20 cím)
1. `select` → `results/`: `pilot_stage1_anchors.json`, `pilot_stage2_measured.json`, `anchor_preview.txt`, `selection.json`.
2. A koordinátor jóváhagyja a horgonyokat (felülírás: `results/anchors_override.json`).
3. A szavazók (A, B; C harmadik szavazat; D tartalék) vakon, külön szavaznak a stage1 feeddel.
4. Utána kalibrációs megbeszélés (koordinátori feljegyzés, nem szavazat). A megbeszélés előtti egyezés csak tájékoztató.

## 3. A 2. szakasz feltöltése (30 mérési cím)
1. Csak a horgonykör és a megbeszélés után.
2. `mz_pilot_stage2.zip` új Production telepítésként **ugyanabba a projektbe** (ugyanaz az origin, a szavazatok megmaradnak).
3. A szavazók frissítik az oldalt; az app kihagyja a már szavazott címeket.
4. Visszaállás: az előző zip újrafeltöltése.
5. 3. szakasz: `analyze` → `adjudication` után az `mz_pilot_stage3.zip` csak az eltérő címekkel.

## 4. Szavazói útmutató (röviden)
- Öntanuló AI panel → Szavazó: saját betű (A/B/C/D), saját telefon.
- „Vak szavazás” és „Forrás neve szavazás előtt” beállításhoz nem nyúlunk; felhő-mentés nincs.
- Gyorsszavazás (csak magyar hírek): **Nyugodt / Közepes / Hangos**; Kihagy csak ha nem ítélhető meg; Vissza az utolsó visszavonása.
- Csak a cím szövege számít; egyedül szavazz, ne keresd meg a cikket.
- Addig, amíg megjelenik: „Elfogyott a magyar hír, ami még nem kapott szavazatot”.

## 5. Mentés és privát beküldés
1. Bármilyen böngészőtörlés előtt: Öntanuló AI → Mentés és helyreállítás → **Teljes mentés másolása**.
2. A kimásolt szöveget **privátban** a koordinátornak (nem csoportba), az adott szakasz után.
3. Közös telefon esetén: **Minden szavazó mentésének másolása**.
4. A koordinátor a beérkezett exportokat a `results/` mappába teszi (git nem követi), majd repón kívülre ment:
   `python scripts/kitchen_dispatch.py --backup-only` (először `--dry-run`-nal).
5. A pilot után a Cloudflare projekt/telepítések törölhetők; szavazói adat ott nincs.

## Napi ellenőrzés (offline)
```
python scripts/code_guard.py
python -m src.magyar_pilot.maintenance
python scripts/kitchen_dispatch.py --backup-only --dry-run
python scripts/context_snapshot.py --max-file-bytes 20000
```
A snapshot a `data/`, `mentesek/` és `results/` mappát nem olvassa, a titkokat a csonkolás előtt maszkolja, és `--max-chars 120000` esetén `context_snapshot_part1.txt`, `_part2.txt`… részekre bontja (a fájlokat a `.gitignore` kizárja).

## Újrakiválasztás (ha a `results/` elveszett)
A `results/` nincs gitben, ezért elveszhet. A horgonykör közben már leszavazott lehet, ezért a horgonyokat nem a feedből, hanem a leszavazott exportokból kell rögzíteni:
`python -m validation.hu_pilot.run select --anchors-from EXPORT...` (mind a 20 címnek azonosan szerepelnie kell az exportokban).
A mérési és a külföldi címek az aktuális feedből jönnek, a horgonyokat és közel-duplikátumaikat kizárva; a `selection.json` `reselection` mezője rögzíti ezt. Ez csak addig tisztességes, amíg a mérési címeket senki nem látta és a modell nem futott. Ne töröld a `results/` mappát (`git clean` nélkül dolgozz a munkafán).
