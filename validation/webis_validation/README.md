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

## A négy jel
| Kulcs | Jelentés |
|---|---|
| `curiosity_gap` | kíváncsisági rés |
| `exaggeration` | túlzás |
| `emotional_pressure` | érzelmi nyomás |
| `formal_noise` | **a „formatting noise” magyar megfelelője: formai / nyelvi zaj** (NAGYBETŰ, ismételt írásjel, felkiáltójel, listaszám, emoji, hashtag, csali-kettőspont). A kulcs neve szándékosan `formal_noise`, nem `formatting_noise` |

## Mit mér
Az AI mind a négy jelre ad értéket (0–2 pont, rövid indoklás, a címből szó szerint idézett részlet). Az összeg 0–8, a kezdeti, **nem bizonyított** átváltás: `scaled = total / 8`. A kiértékelés négy, egymástól külön szakaszt ad:

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
python -m validation.webis_validation.run gemini-dryrun # a 20 címes Gemini smoke test kéréseinek előállítása és ellenőrzése, hálózat és kulcs nélkül
python -m pytest -q validation
```
A két adatfájl a zip-ből a `data/` mappa gyökerébe csomagolandó ki (`instances.jsonl`, `truth.jsonl`).

## Gemini smoke test (20 cím)
Csak a csővezeték ellenőrzése, nem mérési eredmény; **az ingyenes Gemini API-szinten** fut, a 20 címhez.

**Döntések:** a negyedik jel `formal_noise` marad; az elsődleges modell a Gemini 3.5 Flash-Lite vagy a 3.1 Flash-Lite, a modelllistában elérhető változat (a pontos név a lista után dől el). Ha csak a Gemini 3.6 Flash vagy a 3.8 Flash érhető el (ezek ingyenes napi kerete becslés szerint kb. 20 kérés), a futás **nem indul el egy napon**: a kód `NeedUserDecision` hibával megáll, és a felhasználó dönt.

**Állapot:** a kód és a tesztek elkészültek hálózat nélkül (`gemini_request.py`, `gemini_smoke.py`). A modulban **nincs hálózati kód**: a futtató (`run_smoke`) a kérések elküldését egy kívülről kapott átviteli függvényre bízza, a parancssor csak a száraz próbát (`gemini-dryrun`) indítja. Valódi hívás, kulcs és a `generativelanguage.googleapis.com` elérése jóváhagyásra vár; a száraz próbát előbb a felhasználó nézi meg.

**Mit kap a modell:** egy kérés egy cím, és a kérés pontosan három kulcsot tartalmaz: `systemInstruction` (rögzített utasítás), `contents` (egyetlen `user` elem, benne a rögzített sablon és a `postText`) és `generationConfig` (JSON-kimenet, séma, `temperature` 0, `maxOutputTokens`). Nincs `tools`, nincs keresési grounding, nincs azonosító, cikkmező, forrásnév, emberi pontszám, `truthClass` vagy korábbi AI-pontszám, és magyar-specifikus betűt tartalmazó cím nem mehet ki. A kimenő kérést a `check_request` ellenőrzi, és a száraz próba fájlját újraolvasva független ellenőrzés is lefut.

**A `postText` változatlanul megy a modellhez** (döntés, 2026-11-13):
- A szöveget nem tisztítjuk, nem vágjuk és nem alakítjuk át. Az `RT @fiók:` előtagot **nem távolítjuk el**: az eredeti Twitter-poszt része, és az annotátorok is ezt értékelték.
- A csonka linket (például `http://t` a szöveg végén) **nem tisztítjuk**: az eredeti Webis-adat része.
- A forrásnév **nem külön mezőként**, hanem csak a poszt szövegében szerepelhet (például egy `RT @CNNPolitics:` előtagban). A kérés rögzített részében és mezőiben forrásnév, kiadó vagy `source` mező nincs; a kimenő kérés ellenőrzése ezt elutasítja.
- A `safetySettings` mezőt **nem adjuk hozzá**, a biztonsági beállítás nem lazítható; a kimenő kérés ellenőrzése elutasítja, ha megjelenik. A biztonsági blokkot külön `blocked` kategóriaként kezeljük, **nem próbáljuk újra**, és nem számít 0 pontnak.

**Kimenet:** a modell jelenként `span`, `reason`, `score` mezőt ad (a sorrend: előbb az idézet, utána a pont). **Az összpontot (0–8) és a 0–1-es skálát (`total / 8`, kezdeti, nem bizonyított feltevés) a kód számolja**, a modell kimenetében ezek nem szerepelnek; ha mégis megjelennek, a kimenet érvénytelen. A `span` szó szerint szerepel a címben (0 pontnál üres), a `reason` legfeljebb 15 szó.

**Hibakezelés:** érvénytelen JSON vagy szabálysértés egy újrapróbával, utána `errors.jsonl` (javítás nélkül); `MAX_TOKENS` érvénytelen, nem próbáljuk újra; időtúllépés (60 s) és 5xx legfeljebb 2 újrapróba 2 és 8 másodperces várakozással; percenkénti 429 a jelzett `retryDelay` után; **napi 429 azonnali leállás**; biztonsági blokk külön `blocked` kategória (nem 0 pont, nincs újrapróba, a beállítás nem lazítható); 400, 401, 403, 404 leállás. Kérések között legalább 13 másodperc, összesen legfeljebb 25 kérés (az újrapróbákkal együtt), a kész címek újrafuttatáskor nem mennek ki újra. Átmenő feltétel: legalább 18 érvényes pontszám a 20-ból, leállás nélkül.

**Fájlok** (`results/smoke_gemini/`, a gitben nincsenek): `selected_inputs.jsonl` (`id`, `postText`), `requests_dryrun.jsonl` (`index`, `id`, `body_sha256`, `body`), `dryrun_check.json` (a száraz próba ellenőrzése, a rétegek), futtatás után `raw_responses.jsonl`, `scores.jsonl`, `errors.jsonl`, `smoke_report.json`.

**A száraz próba után a sorrend** (mindegyik külön jóváhagyással, a száraz próbát a felhasználó már átnézte és elfogadta):
1. a `generativelanguage.googleapis.com` engedélyezése és a kulcs biztonságos mentése;
2. csak olvasó modelllista-lekérés (`GET /v1beta/models`), a modell kiválasztásához és a gondolkodási beállítás eldöntéséhez;
3. a 20 valódi hívás.

**Kapu:** a smoke test után sem indul el a 250 elemű validáció és a 3000 magyar cím; ehhez külön jóváhagyás kell. A futtató fix 20 címre szól, nagyobb futtatáshoz nincs kód.

## Elkülönítés (tesztek őrzik)
- `config.json`: `mode` csak `benchmark_readonly`, a forrás csak `webis-clickbait-17`, a nyelv `en`.
- Olvasás csak a modul `data/`, írás csak a `results/` mappájából/mappájába; a fő `data/`, `public/`, `inbox/`, `config/`, `src/`, `scripts/` mappákból soha.
- A modul nem importál a fő kódból, nincs benne hálózati vagy AI-kliens; a fő adatfájlok nevei és a fő Gemini-folyamat titka (`GEMINI_API_KEY`) nem szerepel benne.
- A magyar-specifikus betűt (ő, ű) tartalmazó rekordot a betöltő kizárja.

## Mit kap az AI
Kizárólag az azonosítót és a `postText` szövegét (`scoring.build_model_input`): a `model_inputs.jsonl` minden sora `{"id": "…", "postText": "…"}`, ahol a `postText` az eredeti egyelemű lista eleme, szövegként. Nem kapja meg a cikket (`targetTitle`, `targetDescription`, `targetParagraphs`…), a kiadót, az emberi pontszámot, a `truthClass`-t, korábbi AI-pontszámot vagy más szavazók adatát.

## Korlátok
- **A korpusz 2017 óta nyilvános**, ezért egy nagy nyelvi modell láthatta tanítás közben. Az eredmény emiatt kedvezőbb lehet, mint egy ismeretlen adaton; a jelentésben ezt fel kell tüntetni.
- Az archívum 2459 posztja a teljes korpusz (38 517 poszt) kis részét adja; a 250 elemű minta tájékoztató erejű, a bootstrap-sávok szélesek lesznek.
- Ellenőrizetlen: hogy a `clickbait17-test-170720.zip` tartalmaz-e címkéket, és hogy a nagyobb tanító archívum tartalmazza-e a kis archívum rekordjait.

## Még nincs
- Valódi Gemini-hívás: a modelllista lekérdezése, a kulcs és a hozzáférés jóváhagyásra vár, a száraz próbát előbb meg kell nézni.
- A 250 elemű minta értékelése AI-pontszámokkal, és a 3000 magyar cím.

## Groq-ág (openai/gpt-oss-120b), a Gemini mellett

Külön ág a meglévő Gemini-címkézés mellett; a Gemini-fájlokat (`gemini_request.py`, `gemini_smoke.py`, `results/smoke_gemini/`) nem módosítja, nem olvassa az eredményeit, és nem keveri a sajátjait azokkal.

- **Szabályok:** a rendszerutasítás szó szerint a Gemini-é (`gemini_request.SYSTEM_INSTRUCTION`, hash `c634bdcc…da20f`) plusz egy csomagolást leíró bekezdés. Ugyanaz a négy jel (`curiosity_gap`, `exaggeration`, `emotional_pressure`, `formal_noise`), jelenként span/reason/score. Az összeget és a `scaled` értéket a kód számolja.
- **Csomagolás:** 5 cím egy kérésben, helyi azonosítókkal (`t1`…`t5`); a korpusz-azonosító nem megy ki, a kód képezi vissza. A meglévő Gemini-ág egy címet küld kérésenként, ezért a csomagolás különbség is: a modellek összehasonlításánál zavaró tényező.
- **Kulcs:** csak a `GROQ_API_KEY` környezeti változóból, csak `groq_transport.py`-ban (az egyetlen fájl, amely hálózatot és környezetet érint; csak `https://api.groq.com`). Nem kerül kódba, naplóba, kimenetbe. Egy kulcs; nincs tartalék kulcs, nincs fizetős váltás.
- **Kimenet:** `results/groq/groq_results.csv` (cím szerint, státusszal és hibaokkal), `groq_log.jsonl` (kérésenként: csomag, próbálkozás, HTTP-státusz, kimenetel, tokenek, hibák), `groq_summary.json` (kérések száma, tokenek, sikeres/sikertelen csomagok és címek). Létező fájlt nem ír felül.
- **Hibák:** 429 percenkénti korlát (várakozás, legfeljebb 2 újrapróba; 120 s-nál hosszabb várakozásnál megáll), 429 napi korlát (megáll), időtúllépés és 5xx (legfeljebb 2 újrapróba), üres válasz, érvénytelen/csonkolt JSON, hiányzó vagy ismeretlen/duplikált címazonosító (csak a hiányzó címeket küldi újra, egyszer), végzetes hiba (megáll). Kérésplafon: 12.
- **Parancsok:** `groq-dryrun` (hálózat és kulcs nélkül, 4 csomag), `groq-run --go` (valódi futás; kell a kulcs és az `api.groq.com` engedélyezése).
- **Nem ellenőrzött:** a `strict` sémakényszer és a `reasoning_effort` működése a gpt-oss-120b-n harmadik féltől származó információ; a helyi ellenőrzés ezért szigorú, és a kimenetet sosem fogadja el a szolgáltató sémaellenőrzése alapján.
