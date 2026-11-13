# Webis-Clickbait-17 validáció

Külső validáció a címzaj-mérés AI-pontozójához. **Izolált modul:** nem módosítja a fő mérési állapotot, nem ír a fő adattárba, nem használja fel az eredményét a magyar előszűréshez, és az angol Webis-adatot nem keveri a magyar címekkel.

**Állapot:** a váz kész, szintetikus adaton tesztelt, és a valódi korpusz kis archívumán betöltésig ellenőrzött (a betöltő hiba nélkül beolvasta). AI-pontozóval még nem futott.

## Forrás és licenc
- Webis Clickbait Corpus 2017 (Webis-Clickbait-17), hivatalos letöltés a Zenodo-rekordról: https://zenodo.org/records/5530410 (DOI 10.5281/zenodo.5530410).
- Licenc: **Creative Commons Attribution 4.0 International** (`cc-by-4.0`). Újrafelhasználás a szerzők megnevezésével engedett. Hivatkozás: Potthast, Gollub, Wiegmann, Stein, Hagen, Komlossy, Schuster, Fernandez (2018): *Crowdsourcing a Large Corpus of Clickbait on Twitter*, COLING 2018.
- Az adatséma hivatalos leírása: a Clickbait Challenge tárolójában a `clickbait17-dataset-schema.txt`, a kiértékelő a `eval.py` (https://github.com/clickbait-challenge/clickbait-challenge.github.io).
- Letöltés **kézzel** a `data/` mappába. A `data/` és a `results/` tartalma nincs a gitben.

## A korpusz ellenőrzött állapota
Ellenőrizve: 2026-11-13, a letöltött archívumon és a hivatalos sémaleíráson.

| Tény | Érték |
|---|---|
| Letöltött fájl | `clickbait17-train-170331.zip` |
| Méret | 147 797 714 bájt (kb. 148 MB) |
| MD5 | `738075eaf9c4d3af9c16808f5d16ce00` (egyezik a Zenodo-rekorddal; a `verify` parancs ellenőrzi) |
| Az archívum tartalma | egy `clickbait17-train-170331/` mappa 1627 fájllal; a két adatfájl az `instances.jsonl` (12,5 MB) és a `truth.jsonl` (419 KB), a többi médiaanyag |
| Rekordok | **2459** poszt, mindegyikhez van `truth` sor |
| Egyedi címek | **2380**: 79 rekord szövege (kis- és nagybetű, szóköz különbségét nem számítva) egy korábbi azonosítójú rekordéval azonos, ezeket a betöltő kizárja. Üres szöveg, hiányzó vagy skálán kívüli ítélet nincs |
| Annotátorok | **minden rekordhoz pontosan öt** (2459 / 2459) |
| Pontszámok | az ítéletek értéke 0, 1/3, 2/3 vagy 1; a fájlban `0.0`, `0.33333334`, `0.6666667`, `1.0`. A `truthMean` ezért az 1/15 többszörösei közül 16 különböző értéket vehet fel |
| Átlag, medián | a fájl tartalmazza (`truthMean`, `truthMedian`, `truthMode`); az ítéletekből újraszámolva 0 eltérés, a legnagyobb különbség 3,2·10⁻⁸ |
| `postText` | **az elsődleges AI-bemenet.** Minden rekordban pontosan egy elemű szöveglista, egyik sem üres; a linkek el vannak távolítva. 3–28 szó, a medián 13; 4 szónál rövidebb csak 4 van |
| `targetTitle` | a cikk címe, **külön, későbbi mérés** (a cím és a cikk eltérése). Az AI a jelen validációban nem kapja meg |
| `truthClass` | `clickbait` / `no-clickbait`: a **többségi annotátori ítélet**, azaz akkor `clickbait`, ha több annotátor választotta a „jelentősen” és az „erősen” szintet, mint az alsó kettőt. Mind a 2459 rekordban egyezik ezzel a szabállyal |
| Osztályeloszlás | az egész archívum: 762 `clickbait` (31,0%), 1697 `no-clickbait`; a tisztított 2380-ban 725 és 1655 |

**A 250 elemű validációhoz a 148 MB-os archívum elég.** A tisztított 2380 rekord rétegenként 798 / 903 / 537 / 142 elemet ad az 0–0,25 / 0,25–0,5 / 0,5–0,75 / 0,75–1 átlagsávokban, így a 75 / 50 / 50 / 75 célszám pótlás nélkül teljesül. A nagyobb `clickbait17-train-170630.zip` (937 MB) nem szükséges; a cikkeket tartalmazó webarchívumok (kb. 20 GB darabonként) és a címkézetlen archívum nem kell.

## Mit mér
Az AI négy jelet ad egy címre (kíváncsisági rés, túlzás, érzelmi nyomás, formai zaj; 0–2 pont, rövid indoklás, a címből idézett részlet). Az összeg 0–8, a kezdeti, **nem bizonyított** átváltás: `scaled = total / 8`. A kiértékelés négy, egymástól külön szakaszt ad:

1. **`regression_vs_truthMean`:** regresszió az emberi átlagra (MSE, RMSE, a hivatalos `eval.py` szerinti normált MSE, Spearman, Kendall tau-b, bootstrap-sáv). Ez a Clickbait Challenge elsődleges célja.
2. **`supplementary_vs_truthMedian`:** ugyanezek a mutatók a mediánra, kiegészítésként.
3. **`classification_vs_truthClass`:** osztályozás a fájlbeli `truthClass` ellen (pontosság, precízió, fedés, F1, ROC AUC, a tévesen zajosnak minősített és az átugrott zajos címek). Az AI-pontszám binárisítása: `scaled >= 0,5` (a hivatalos `eval.py` is 0,5 alatt 0-t, egyébként 1-et ad).
4. **`binarized_mean_threshold`:** ugyanez, de az igazság a `truthMean >= 0,5`. **Ez nem azonos a `truthClass`-szal**, ezért külön szakasz.

Mellette: `truthClass_vs_mean_threshold_disagreement` (a vizsgált mintában hány rekordnál tér el a két igazság), a legnagyobb eltérések, jelenkénti Spearman, a `total / 8` átváltás mintán belüli monoton illesztéssel való összevetése (csak diagnosztika), bontás `short_title` és annotátor-egyetértés szerint.

## A `truthClass` és az átlagküszöb eltérése
Az egész érvényes archívumon (2459 rekord) **150 rekordnál** (6,1%) tér el a `truthClass` a `truthMean >= 0,5` szabálytól:
- 101 rekord `clickbait`, de az átlaga 0,5 alatt van (0,4: 28 rekord, 0,467: 73 rekord), mert három annotátor választott felső szintet és kettő alsót;
- 49 rekord `no-clickbait`, de az átlaga 0,5 vagy fölötte van (0,533: 45 rekord, 0,6: 4 rekord), mert három annotátor választott alsó szintet.

A tisztított 2380 rekordban ez **144** (95 és 49); a 79 kizárt ismétlődő rekordból 6 tartozott az első csoportba. A `truthClass` és a többségi szabály között nincs eltérés. A betöltő (`inspect`) mindkét számot kiírja (`class_check_all_valid_rows`, `class_vs_mean_threshold`).

## Parancsok (a repó gyökeréből)
```
python -m validation.webis_validation.run verify validation/webis_validation/data/clickbait17-train-170331.zip
python -m validation.webis_validation.run inspect       # mezők, annotátorszám, kizárások, osztályellenőrzés, rétegek eloszlása
python -m validation.webis_validation.run sample        # 250 elemű minta → results/sample_meta.json, results/model_inputs.jsonl (soronként csak {"id", "postText"}; a gitben nincs)
python -m validation.webis_validation.run evaluate results/scores.jsonl
python -m validation.webis_validation.run smoke         # szintetikus lánc próba-pontozóval (nem AI), a modul mappáiba nem ír
python -m pytest -q validation
```
A két adatfájl a zip-ből a `data/` mappa gyökerébe csomagolandó ki (`instances.jsonl`, `truth.jsonl`).

## Elkülönítés (tesztek őrzik)
- `config.json`: `mode` csak `benchmark_readonly`, a forrás csak `webis-clickbait-17`, a nyelv `en`.
- Olvasás csak a modul `data/`, írás csak a `results/` mappájából/mappájába; a fő `data/`, `public/`, `inbox/`, `config/`, `src/`, `scripts/` mappákból soha.
- A modul nem importál a fő kódból, nincs benne hálózati vagy AI-kliens; a fő adatfájlok nevei csak az `isolation.py`-ban szerepelnek.
- A magyar-specifikus betűt (ő, ű) tartalmazó rekordot a betöltő kizárja.

## Mit kap az AI
Kizárólag az azonosítót és a `postText` szövegét (`scoring.build_model_input`): a `model_inputs.jsonl` minden sora `{"id": "…", "postText": "…"}`, ahol a `postText` az eredeti egyelemű lista eleme, szövegként. Nem kapja meg a cikket (`targetTitle`, `targetDescription`, `targetParagraphs`…), a kiadót, az emberi pontszámot, a `truthClass`-t, korábbi AI-pontszámot vagy más szavazók adatát.

## Korlátok
- **A korpusz 2017 óta nyilvános**, ezért egy nagy nyelvi modell láthatta tanítás közben. Az eredmény emiatt kedvezőbb lehet, mint egy ismeretlen adaton; a jelentésben ezt fel kell tüntetni.
- Az archívum 2459 posztja a teljes korpusz (38 517 poszt) kis részét adja; a 250 elemű minta tájékoztató erejű, a bootstrap-sávok szélesek lesznek.
- Ellenőrizetlen: hogy a `clickbait17-test-170720.zip` tartalmaz-e címkéket, és hogy a nagyobb tanító archívum tartalmazza-e a kis archívum rekordjait.

## Még nincs
- AI-pontozó (a modell kiválasztása és a költségkeret jóváhagyásra vár) és külső AI-hívás.
- A 250 elemű minta értékelése AI-pontszámokkal.
