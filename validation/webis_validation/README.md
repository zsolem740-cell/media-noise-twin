# Webis-Clickbait-17 validáció

Külső validáció a címzaj-mérés AI-pontozójához. **Izolált modul:** nem módosítja a fő mérési állapotot, nem ír a fő adattárba, nem használja fel az eredményét a magyar előszűréshez, és az angol Webis-adatot nem keveri a magyar címekkel.

**Állapot:** az AI nélküli váz kész és szintetikus adaton tesztelt. Valódi korpusszal és valódi AI-pontozóval még nem futott.

## Mit mér
Az AI négy jelet ad egy címre (kíváncsisági rés, túlzás, érzelmi nyomás, formai zaj; 0–2 pont, rövid indoklás, a címből idézett részlet). Az összeg 0–8, a kezdeti, **nem bizonyított** átváltás: `scaled = total / 8`. A kiértékelés az emberi átlaghoz és mediánhoz viszonyít (MSE, RMSE, normált MSE, Spearman, Kendall tau-b, bootstrap-sávval), kilistázza a tévesen zajosnak minősített és az átugrott zajos címeket, a legnagyobb eltéréseket, és bontja `short_title` és annotátor-egyetértés szerint. A `scaled` átváltást a jelentés mintán belüli monoton illesztéssel veti össze (csak diagnosztika).

## Forrás
- Webis Clickbait Corpus 2017, CC BY 4.0, a szerzők megnevezése kötelező (`config.json` → `citation`): https://doi.org/10.5281/zenodo.5530410
- Letöltés **kézzel** a `data/` mappába. A betöltéshez a `instances.jsonl` és a `truth.jsonl` kell; archívumonként a Zenodo-rekord MD5-je és mérete a `config.json`-ban van, a `verify` parancs ellenőrzi.
- A cikkeket tartalmazó WARC-archívumok és a címkézetlen archívum nem kell: az AI csak a címet kaphatja.

## Parancsok (a repó gyökeréből)
```
python -m validation.webis_validation.run verify validation/webis_validation/data/clickbait17-train-170331.zip
python -m validation.webis_validation.run inspect       # mezők, annotátorszám, kizárások, rétegek eloszlása
python -m validation.webis_validation.run sample        # 250 elemű minta → results/sample_meta.json, results/model_inputs.jsonl (csak id + cím)
python -m validation.webis_validation.run evaluate results/scores.jsonl
python -m validation.webis_validation.run smoke         # szintetikus lánc próba-pontozóval (nem AI), a modul mappáiba nem ír
python -m pytest -q validation
```

## Elkülönítés (tesztek őrzik)
- `config.json`: `mode` csak `benchmark_readonly`, a forrás csak `webis-clickbait-17`, a nyelv `en`.
- Olvasás csak a modul `data/`, írás csak a `results/` mappájából/mappájába; a fő `data/`, `public/`, `inbox/`, `config/`, `src/`, `scripts/` mappákból soha.
- A modul nem importál a fő kódból, nincs benne hálózati vagy AI-kliens; a fő adatfájlok nevei csak az `isolation.py`-ban szerepelnek.
- A magyar-specifikus betűt (ő, ű) tartalmazó rekordot a betöltő kizárja.
- A `data/` és a `results/` tartalma nincs a gitben.

## Mit kap az AI
Kizárólag `{"id", "text"}` (`scoring.build_model_input`). Nem kapja meg a cikket, a kiadót, az emberi pontszámot, korábbi AI-pontszámot vagy más szavazók adatát.

## Ellenőrizetlen feltevések (a korpusz első betöltésekor tisztázandók)
- A zip-en belüli fájlnevek (`instances.jsonl`, `truth.jsonl`) és a mezőnevek (`postText`, `truthJudgments`…): a betöltő a `config.json` `field_aliases` szerint keres, és hiány esetén kiírja a ténylegesen talált mezőket. A `postText` lehet szöveg vagy szöveglista.
- A rekordszám archívumonként, és hogy a teszt-archívum teljes címkéivel letölthető-e.
- A normált MSE egyezése a hivatalos `eval.py`-jal.
- A korpusz 2017 óta nyilvános: egy nagy nyelvi modell láthatta tanítás közben. A jelentésben korlátként szerepeljen.

## Még nincs
- AI-pontozó (a modell kiválasztása és a költségkeret jóváhagyásra vár), a valódi korpusz betöltése, a 250 elemű minta valódi futtatása.
