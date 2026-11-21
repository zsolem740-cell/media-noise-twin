# `LIVE-G36F-3C-001` futás: lezárt nyilvántartás (2026-11-21)

A tulajdonos a futást **lezártnak tekinti**. Új API-hívás ezzel nem engedélyezett. Ez a dokumentum az eredményt, a kiértékelést és a hiányosságokat rögzíti, utólagos módosítás nélkül.

## 1. Az eredeti eredmény megőrzése
- Fájlok (a repóba **nem** kerülnek: `CLAUDE.md` tiltja a `results/` tartalmának commitolását): `video_research/results/LIVE-G36F-3C-001/` — csak olvasható (`chmod 444`), a méret és az időbélyeg a futás végi állapottal egyezik.

| Fájl | Méret | SHA-256 |
|---|---|---|
| `manifest.json` | 1328 B | `d47cf7789d08a349151b696b1ded8d4909be321cceb421978d44234ed36f8116` |
| `raw_model_io.json` | 43075 B | `cc6e4c65a69940edf26b3b54acbfe95e56682e2a6a1bb5c0e6c48aaffa866ddb` |
| `processed_results.json` | 7328 B | `427759ed6f82e14b7413b6e2119ff8e856cce15172ac16afc08c5b6b6271b14d` |

- **Figyelem:** a tároló ideiglenes; a mappa a munkamenet végével elveszhet. A három fájlt (titkot nem tartalmaznak: ellenőrizve) a felhasználónak átadtam; hosszú távú őrzésük a tulajdonos dolga.
- Futási azonosítók: commit `c718146e3cba52f67eacff9b0db2899187c928bd`, modell `gemini-3.6-flash`, konfiguráció `gen-cfg-2`, prompt-verzió `sha256:c01c1672d83a4304`. 7 kérés, 8 882 számolt token, 79,7 s, szolgáltatói hiba nincs, lefagyasztott fájlok nem változtak (`valid_run: true`).
- Az eredeti kiértékelés (a változatlan kiértékelő, a változatlan elvárások szerint): `G_needle` és `D_irrelevant` minden elvárást teljesített; `A_tools`: `missed: szegmens 2 (cost)`, minden más ellenőrzés (tévesen bekerült, idézet, forráskapcsolat, korlátozás) rendben. **Az elvárásokat és a kiértékelő szabályait utólag nem módosítottuk.**

## 2. `A_tools`: két külön szempont
| Szempont | Megállapítás |
|---|---|
| **Tartalmilag szerepelt-e a költség?** | **Igen.** A megtartott tétel magyar állítása: „…egy Gemini API-kulcs, amely a forrás tapasztalata szerint nagyjából havi 5 dollárba kerül.” Az összeg, az időegység és a forrás korlátozása („a forrás tapasztalata szerint”, „nagyjából”; az idézet: „in my case”) megmaradt. |
| **Keletkezett-e külön `cost` típusú strukturált tétel?** | **Nem.** A modell az eszközt és a költséget egyetlen `tool` típusú tételbe vonta össze (ugyanaz az idézet, 2. szegmens). A kézi elvárás külön `cost` tételt várt (`seg=2, kind=cost`), ezért a kiértékelő `missed: szegmens 2 (cost)`-ot jelzett. |
A két megállapítás nem mond ellent egymásnak, és a kiértékelés nem változik. A „külön cost tétel” követelmény a strukturált kimenetre vonatkozik; a tartalmi szerepeltetés külön szempont. Egy mintán (1 eset) ebből általános következtetés nem vonható le.

## 3. Engedélyezési hiány (külön rögzítve)
- A futást jóváhagyó üzenetben a **kvóta- és használati adatok** („a `gemini-3.6-flash` kvóta- és használati adatai”) és az **óránkénti bot projektre vonatkozó válasza** **kitöltetlen sablonszövegként** szerepelt, tényleges értékek nélkül.
- Ezek **a futás előtt nem voltak igazolva**, és ezt utólag sem állítjuk. A futás az írásos tulajdonosi igazolásra („az ingyenes projektbesorolást és a számlázási kapcsolat hiányát ellenőriztem”), az egyértelmű futásjóváhagyásra és a korábbi szabályjóváhagyásra épült; az igazoló kapcsolókat ennek alapján adtam át.
- Következmény: nem ismert, hány kérés maradt aznapra, és hogy a próba fogyasztotta-e az óránkénti bot keretét (közös projekt/modell esetén). A futás közben 429 nem jelentkezett.
- **Szabály új futásra:** sablonhelyőrző (szögletes zárójeles kitöltetlen mező, „[értékek…]”, „[ugyanazt/nem…]”) **nem fogadható el tényleges adatként**. A futás előtt minden adatmezőnek tényleges értéket vagy kifejezett „nem látható / nem tudom megállapítani” kijelentést kell tartalmaznia; az utóbbi esetben a hiányt a futás előtt külön mérlegeljük és rögzítjük. Kitöltetlen sablon esetén az ügynök nem indít hívást, hanem kérdez.

## 4. A „számolt tokenek összesen” képződése (kód + a mentett nyers adat)
Kód (`acceptance/live.py`, `BudgetedTransport._call`):
```python
p, c, th, tot = (int(u.get(k) or 0) for k in ("promptTokenCount", "candidatesTokenCount", "thoughtsTokenCount", "totalTokenCount"))
used = max(tot, p + c + th)
self.b.prompt, self.b.completion, self.b.thoughts, self.b.tokens = (... + p, ... + c, ... + th, ... + used)
```
- A kérésenkénti számolt érték `max(totalTokenCount, prompt + candidates + thoughts)`: **maximum, nem összeg**, ezért a gondolkodási token nem kerülhet még egyszer hozzáadásra a szolgáltatói `totalTokenCount` mellett.
- A Google dokumentációja szerint `totalTokenCount` = prompt + eszköz-prompt + gondolat + jelölt; `candidatesTokenCount` csak a jelölteket tartalmazza, a gondolat külön mező.
- A mentett nyers válaszokból újraszámolva mind a 7 kérésre: `totalTokenCount − prompt − candidates = thoughts`, vagyis a szolgáltatói total **már tartalmazza** a gondolkodást; `toolUsePromptTokenCount` nem szerepelt. Összeg: szolgáltatói total-ok = **8 882** = vezérlő számolt összege = prompt 5 899 + candidates 825 + thoughts 2 158. Ha a gondolkodást a total mellé még egyszer hozzáadtuk volna, 11 040 jött volna ki: ez **nem történt**.
- Offline teszt: `test_thoughts_are_not_counted_twice_next_to_the_provider_total` (összeg-total, hiányzó total, hiányzó gondolkodási mező esetek).
- Korlát (változatlan): ez a szolgáltató által jelentett használat; a szolgáltató oldali elszámolás és az időtúllépett kérések használata nem ismert.

## 5. A következő értékelés bemenete: a meglévő átiratimport-formátumok
A felhasználó által biztosított valódi átiratok a meglévő `video_research/importer.py` (`POST /api/jobs/import`, ill. `import_job()`) formátumaiban adhatók át; újat nem fejlesztünk.

| `format` | Elfogadott bemenet | Időbélyeg |
|---|---|---|
| `text` | egyszerű szöveg; bekezdés/sor = szegmens, 400 karakternél hosszabb sor mondathatáron darabolva | **mindig null** |
| `srt` | szabványos SRT: sorszám (elhagyható), `HH:MM:SS,mmm --> HH:MM:SS,mmm` (az óra elhagyható; pont is elfogadott), többsoros szöveg; a `<…>` jelölések törlődnek | a fájlból; az érvénytelen vég null; hibás időbélyeg → hiba |
| `vtt` | WebVTT: kötelező `WEBVTT` fejléc, `NOTE`/`STYLE`/`REGION` blokkok kihagyva, cue-azonosító és beállítások (pl. `align:start`) figyelmen kívül, `<v Név>…</v>` jelölések törlődnek | a fájlból |

Egyéb paraméterek: `question` (kutatási kérdés), `language` (`hu` vagy `en`), `title` (opcionális), `video_url` (opcionális YouTube/TikTok-link; **nem** igazolt átirat–videó egyezés), `known_information` (opcionális). Eredet: `user_provided_transcript`. Korlát: 1 átirat / import-feladat; a hatásos hosszkorlát 200 000 karakter (`max_transcript_chars`).
**Nem támogatott:** docx/json/TTML/ASS és egyéb formátum, beszélőcímkék, több videó egy feladatban. **A parser nem szűri** a duplikált sorokat (a YouTube automatikus VTT-jeiben ilyenek előfordulhatnak).
**Fontos korlát a következő értékeléshez:** a valódi-modell értékelő (`acceptance/runner.py --live`) az eseteket a lefagyasztott `acceptance/cases.py`-ból olvassa (szegmenslistából épít SRT-t/szöveget); fájlból olvasó esetbetöltő nincs. Valódi átiratos értékeléshez új, verziózott, külön lefagyasztott esetkészlet kell; ezt most nem fejlesztjük.

## 6. Utólagos tartalmi egybevetés: mi kerül havi 5 dollárba? (2026-11-21, emberi/kódolvasásos, modellhívás nélkül)
Az eredeti eredmény fájljai nem módosultak (a SHA-256 értékek változatlanok); ez kiegészítés, nem javítás.

| | Szöveg |
|---|---|
| Eredeti angol forrásmondat (a kérésben elküldve, 2. szegmens) | „You also need the AutoDroid app, **which is free**, plus **a Gemini API key, and that costs about five dollars a month in my case**.” |
| A modell magyar állítása (nyers kimenet = feldolgozott tétel) | „Szükséges az **ingyenes AutoDroid alkalmazás**, valamint egy **Gemini API-kulcs, amely a forrás tapasztalata szerint nagyjából havi 5 dollárba kerül**.” |

**Megállapítás: a magyar állítás helyesen nevezi meg, minek van költsége.**
- A „which is free” az AutoDroid alkalmazásra vonatkozik: az állításban „ingyenes AutoDroid alkalmazás” → helyes, a költség nem az alkalmazáshoz kerül.
- A „that costs about five dollars a month” legtermészetesebb olvasata a közvetlenül előtte álló „Gemini API key”-re vonatkozik; az állítás a költséget a Gemini API-kulcshoz rendeli („amely … kerül”) → helyes. Az „about” → „nagyjából”, az „a month” → „havi”, a „five dollars” → „5 dollár” (az eredeti nem mondja ki, hogy USD).
- **Maradék pontatlanságok / korlátok (nem hibák, de rögzítendők):**
  1. A forrásmondat szóhasználata („that” = a kulcs) lazán fogalmaz; a költség valószínűleg a Gemini API **használatának/előfizetésének** díja, nem a kulcs mint tárgy ára. A magyar állítás a forrás szerkezetét követi („kulcs … kerül”), és nem dönti el ezt. Az eredeti szöveg sem mond többet, tehát nincs elveszett vagy hozzátett információ.
  2. Az „in my case” → „a forrás tapasztalata szerint”: a „forrás” a videó beszélője, és a személyes jelleg megmarad, de a „tapasztalata” enyhén mást sugall (tapasztalat) mint a „saját esetében” (az ő használati körülményei). Kisebb jelentésárnyalat-eltolódás, az állítás nem erősebb a forrásnál.
- **Az értékelő szabályának korlátja (nem módosítva):** a kézi elvárás szócsoportja a költségnél `[havi/hónap] ÉS [saját/szerző]`. A tényleges állításban a „saját/szerző” szavak nincsenek benne („a forrás tapasztalata szerint” szerepel), ezért ha a modell külön `cost` tételt adott volna ezzel a megfogalmazással, a lexikális szabály a korlátozás elvesztését jelezte volna, noha jelentésben megmaradt. A szócsoportos ellenőrzés tehát lexikális, nem szemantikai; ezt a következő elvárások rögzítésekor figyelembe kell venni (több szinonima, vagy emberi ítélet).
