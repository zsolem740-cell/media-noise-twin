# SYN-BLIND-001 — előkészítési terv (1. lépés, a rekord előtt)

**Állapot:** helyi előkészítés. Ez NEM piaci adat, NEM kereskedelmi modell, és NEM mérés: a mérési kapu zárva marad. A szimulátor egy szintetikus funkcionális ellenőrzés, nem validált kereskedési modell; az itt leírt történet sem állít semmit valódi piacról.

## 1. Cél és határ
Egy teljesen szintetikus, előre rögzíthető 120 napi sávos történet (`SYN-BLIND-001`) ELŐÁLLÍTÁSA és független ELLENŐRZÉSE. Ez a kör csak az adatkezelési rész: a stratégia és a teljes történeten végzett visszajátszás NEM része (lásd a 7. pontot). Nincs stratégiafutás, benchmark, G1–G5, páros stratégiafutás, futtatóépítés vagy előzetes rekord. Nincs valódi adat, külső API, modellbetanítás, optimalizálás vagy éles művelet. A meglévő `trading_model/data.py` változatlan; a kimenet vele kompatibilis.

## 2. Fájlok (e kör hat fájlja)
| Fájl | Szerep |
|---|---|
| `trading_model/scenarios/__init__.py` | csomagjelölő |
| `trading_model/scenarios/syn_blind_001.py` | generátor + parancssor (importáláskor nem generál, nem ír, nem ellenőriz) |
| `trading_model/scenarios/syn_blind_001_check.py` | FÜGGETLEN ellenőr (CONTRACT, FORMULA, SERIALIZATION, HASH külön) |
| `trading_model/tests/test_syn_blind_001_generator.py`, `test_syn_blind_001_check.py` | tesztek |
| `trading_model/docs/SYN_BLIND_001_TERV.md` | ez a dokumentum |

Az új modulok és tesztek NEM importálják a `trading_model.simulator` modult, és nincs dinamikus importálás vagy ezt kijátszó közvetett út (szerkezeti őr, nem védelmi homokozó). A `check_series` ebben a körben nem fut és nincs átmásolva. A szakaszcímkék (`STAGES`) csak a generátor belső, értékelői leírásai: nem kerülnek a kimeneti adatmezők közé.

## 3. A történet (rögzített képletek, nincs véletlenszám)
Sávok: `k = 1..120`, `timestamp = 2026-01-01T00:00:00Z + k nap` (a sáv VÉGE), `available_at = timestamp`, `volume = 1000000`, kezdő nyitás 100,00; az árak 2 tizedesesek.

- nyitás: `k=1` → 100,00; különben az előző zárás, kivéve a 56. sávot (rés, lásd lent);
- zárás = `kerekít_fél-páros(nyitás * (1 + elmozdulás))`, ahol `elmozdulás = alap + zaj·jelző`;
- zaj: `((7k mod 11) − 5) · 0,0004` (egész számos, egy 11 sávos periódus összege 0);
- magas = `plafon(max(nyitás, zárás) · (1 + fel_kanóc))`, `fel_kanóc = (((3k) mod 7) + 1) · 0,0005`;
- alacsony = `padló(min(nyitás, zárás) · (1 − le_kanóc))`, `le_kanóc = (((5k) mod 7) + 1) · 0,0005`.

| Szakasz | Sávok | Alap-elmozdulás | Zaj |
|---|---|---|---|
| 1 nyugodt indulás | 1–20 | 0 | van |
| 2 lassú emelkedés | 21–45 | +0,0030 | van |
| 3a hamis kitörés fel | 46–48 | +0,0250 | nincs |
| 3b visszaesés | 49–55 | −0,0110 | nincs |
| 4 hirtelen esés | 56–60 | −0,0100, −0,0100, −0,0050, −0,0050, −0,0050; a 56. sáv nyitása az előző zárás −12%-a (rés) | nincs |
| 5 oldalazás | 61–85 | +0,0080 ha `k mod 3 = 0`, különben −0,0040 | van |
| 6 felépülés | 86–105 | +0,0050 | van |
| 6 lecsengés | 106–120 | 0 | van |

Alternatív folytatás (`alt`): az 1–50. sáv azonos az alap változattal, az 51–120. sávban `alap = +0,0040`, rés nincs, zaj van. A kettő együtt a páros jövőpróba majdani alapja; az 1. lépés csak előállítja és ellenőrzi őket.

A „közel oldalazó, enyhén negatív alapmozgás” és a többi történetleírás közelítő szöveges kép, NEM elfogadási feltétel: a rögzített képlet és a megfigyelt adat eltérését a jelentés megnevezi, az adatot a leíráshoz nem igazítjuk. A rés (56. sáv) a stratégia nézetéből nem látható előre; a nézet csak lezárt sávokat tartalmaz.

## 4. Kerekítés és Decimal
A generátor SAJÁT rögzített `Decimal` kontextust használ (prec 34, fél-páros, Inexact csapda: minden nem pontos művelet hiba). Az egyetlen kerekítés az explicit `quantize(0,01)` külön, csapdamentes helyi kontextusban: ez ADAT-ELŐÁLLÍTÁSI kerekítés, elkülönítve a szimulátor kerekítés nélküli elszámolási szerződésétől. A magas/alacsony ár irányított kerekítésű (plafon/padló), így a sáv mindig összefüggő (`low ≤ min(open, close)`, `high ≥ max(open, close)`).

## 5. Szerializálás és hash
Kanonikus ASCII JSON: kulcsok rendezve, szóköz nélkül, az ár a Decimal pontos tizedes szövege (2 tizedes), `volume` egész. A SHA-256 a kimeneti bájtokra számolódik. A kimenet mellé `<fájl>.sha256` kerül a `sha256sum -c` formátumában: `<64 kisbetűs hexa>␠␠<fájlnév>\n`.

## 6. Megvalósított tulajdonságok
**Generátor (`syn_blind_001.py`)**
- Importáláskor nem generál, nem ír, nem ellenőriz (szerkezeti teszt őrzi, a generátoron és az ellenőrön is).
- A szakaszcímkék (`STAGES`) nem kerülnek az adatmezők közé (teszt: szándékosan beszúrt címkével a detektor elbukik).
- Kimeneti útvonal: feloldva (szimbolikus linkeken át) ellenőrzi; a tároló munkafáján belülit megtagadja.
- **Támogatott határ:** PRIVÁT, nem ellenséges kimeneti könyvtár. Védelmet azonos felhasználó kódjának egyidejű útvonalcseréje ellen nem állítunk.
- **Kiírási protokoll (B változat):** (1) előzetes létezés-ellenőrzés: az ütköző, már létező végleges fájl érintetlen marad és jelentve van; (2) EGYEDI, véletlen nevű ideiglenes fájlok kizáró létrehozása (`O_CREAT|O_EXCL`), a fájlleírók a takarítás végéig NYITVA maradnak és minden kilépési ágon bezáródnak (kivéve a 8. szakaszban nevesített `os.open`–nyilvántartás közti ablakot); (3) ellenőrzés a SAJÁT inode-ból (H2, bájt, hash); (4) KÖZZÉTÉTELI SORREND: ELŐBB a sidecar, UTOLJÁRA az adatfájl, `os.link`-kel (létező célra, törött szimbolikus linkre is `FileExistsError`: nem ír felül), mindegyik után azonosság-ellenőrzés (`fstat(fd)` = `lstat(végleges)`) és tartalom-ellenőrzés a leírón; az adatfájl közzététele UTÁN MINDKÉT végleges név újraellenőrzése, és csak ezután minősül a kimenet teljesnek (0); (5) az ideiglenes nevek törlése, csak ha a fájlleíróval összevetve a miénk. **Ez közzétételi sorrend, NEM atomi páros közzététel.**
- **Nincs visszagörgetés.** A közzétett végleges fájlt a kód SOHA nem törli, nem írja felül, nem csonkítja és nem nevezi át (a törlést kizárólag az ideiglenes nevekre szolgáló `_remove_tmp` végzi; szerkezeti őr és futásidejű hibainjektálás is ezt ellenőrzi). Ez kifejezetten felváltja a korábbi „nincs részleges kimenet” követelményt: **hiányos kimenet maradhat, de jelentenünk kell, és soha nem tekinthető befagyasztottnak.**
- Idegen vagy lecserélt fájlt (végleges vagy ideiglenes néven) nem törlünk; a közzététel utáni azonosság-eltérés hibával leáll, az idegen tartalom megmarad, az érintett útvonalak jelentve vannak, és a kimenet nem sikeres/befagyasztott.
- Az eredeti kivétel megmarad; a takarítás hibája nem fedi el (a `leftovers`-be kerül). `KeyboardInterrupt`/`SystemExit` a legjobb erőfeszítésű takarítás után továbbterjed; az ismert közzétett kimenet a kivétel jegyzetében (és a CLI-ben a hibakimeneten) szerepel.
- **CLI kilépési kódok (`--out`):** `0` teljes, ellenőrzött kimenet és sikeres takarítás — **csak ez jogosult későbbi rekord-jóváhagyásra**; `2` sikertelen, a hívásnak nem tulajdonítható kimenet vagy maradék (a már létező ütköző fájlok érintetlenek, és kifejezetten jelentve vannak; kivétel a 8. szakasz szűk `os.open`–nyilvántartás ablaka, ahol a 2-es kód nem garantálja, hogy nem maradt `.tmp`); `3` hiányos közzététel, idegen csere a VÉGLEGES néven vagy bizonytalan végleges állapot (felsorolva), valamint olyan sikertelen kiírás, amelynek ideiglenes maradéka megmaradt; `4` a végleges fájlpár teljes és ellenőrzött, de ideiglenes maradék van — ide tartozik az idegen vagy lecserélt IDEIGLENES név is, ha a végleges pár a sikeres közzététel után teljes és ellenőrzött maradt (a pár ekkor érvényes, de a kimenet nem jogosult rekord-jóváhagyásra). A hash-sor (`<hash>  <útvonal>`) csak a `0`-s kódnál kerül a standard kimenetre; `4`-nél, valamint teljes kiírás melletti hibás `--hash-check`/`--check-file` (kód `1`) esetén csak tájékoztatóként a hibakimenetre (teszt: `test_check_flag_failure_*`, `test_hash_line_goes_to_stdout_only_with_exit_0`).

**Független ellenőr (`syn_blind_001_check.py`)**
- Négy külön eredmény: CONTRACT, FORMULA, SERIALIZATION, HASH; mindegyik `rendben` / `hiba` / `nem értékelhető`. A `nem értékelhető` (nincs rögzített hash, olvashatatlan fájl, értelmezhetetlen JSON, hibás sidecar) sem sikernek, sem lefuttatott hibának nem számít. Kilépési kód: `0` mind rendben, `1` van hiba, `2` nincs hiba, de van nem értékelhető.
- Diagnózis: változat, sávindex (egységesen 1-alapú, a CONTRACT sorokban is), mező, kapott és várt érték. Eltérő sávszámnál időbélyeg szerint párosít: a hiányzó, a többlet és az ismétlődő sávot sávindexszel/pozícióval azonosítja, és nem ad lavinát az elcsúszott sávokra. Levágott kimenetnél közli az összes hiba számát és a kihagyottakét.
- Kezeletlen kivétel nincs: hibás mezőtípus (`bars` nem lista), hiányzó fájl, túlmély JSON, nem ASCII bájt, `hiba` vagy `nem értékelhető` állapot. Csak SZABÁLYOS fájlt olvas (FIFO, eszköz, könyvtár: `nem értékelhető`, nem blokkol), legfeljebb 1 MiB-ot (a sidecar 4 KiB-ot); nagyobb bemenet `nem értékelhető`.
- A hibás állományt nem javítja és nem módosítja (teszt: tartalom és módosítási idő változatlan).
- **A HASH jelentése:** FÁJL–SIDECAR BÁJTAZONOSSÁG. A sidecar fájlnévmezőjét is ellenőrzi az ellenőrzött fájl nevével. NEM mond semmit arról, melyik forgatókönyvhöz (base/alt) tartozik a fájl: azt a FORMULA mondja meg a KIVÁLASZTOTT változat képleteivel (az `alt` fájl a saját sidecarjával `--variant base` mellett HASH-rendben, de FORMULA-hibás). A hash nem „előre rögzített” érték: rögzítésről külön döntés kell. Futásban nem használt, „független várt hash” fogalom nincs; az `expected_bytes` csak a különbségi teszt referencia-előállítása.

## 7. Ténylegesen elvégzett ellenőrzések
**Automatizált tesztek** (`not live_api` készlet, valódi közös hálózati zárral): a két tesztfájl. Köztük futásidejű hibainjektálással: az idegen tartalom megmaradása (végleges és ideiglenes néven, közzététel előtt és után), a visszagörgetés tilalma, a sidecar-első sorrend, a takarítási hibák, a megszakítás a közzététel után, a fájlleírók lezárása minden kilépési ágon, a 0/2/3/4 kilépési kódok és a hash-sor szabálya; az ellenőr negatív esetei (ár, időbélyeg, `available_at`, hiányzó/többlet/ismétlődő sáv, téves változat, hibás hash, hibás sidecar, hibás mezőtípus, hiányzó fájl, túlmély JSON); a kerekítés kézi esetei; és a hat fájl név szerinti szerkezeti őre (nincs szimulátor-import, nincs dinamikus importálás).
**Mutációs kísérlet** (a tárolón kívül, kézzel futtatva; NEM automatizált teszt): azt vizsgálja, hogy a tesztek elbuknak-e, ha egy védelmet kiveszünk. Hatókör: kizárólag a generátor (`syn_blind_001.py`) mutánsai, kizárólag a generátor tesztfájlján futtatva; az ellenőr (`syn_blind_001_check.py`) és tesztjei nincsenek mutáció-tesztelve. A harness az alapállapot zöld voltát futtatás előtt ellenőrzi és megáll, ha nem; mutánsonként külön kezeli: a csere pontosan egyszeri alkalmazását és a fordíthatóságot, a pytest kilépési kódját (1 = teszt-bukás), a bukó tesztek nevét (JUnit), a gyűjtési/import hibákat, az időtúllépést és az infrastruktúra-hibát. Elkapottnak csak az számít, ha legalább egy teszt ténylegesen elbukott és nem volt gyűjtési hiba; azt, hogy a CÉLZOTT teszt bukott-e, a harness nem ellenőrzi (a bukó tesztnevek kézzel nézhetők). **Végső eredmény: 31 mutánsból 29 elkapott, 2 él (M29, M30).** Az alapállapot zöld volt (82 teszt); a végső futás naplója szerint nem volt gyűjtési hiba, időtúllépés vagy infrastruktúra-hiba (a nyers napló a tárolón kívül van, SHA-256 előtagja `65da93d3…`). **Bizonyítéknak csak ez az egy, végső futás számít.** A korábbi futások nem bizonyítékok és nem hivatkozható eredmények: a 11 mutánsos futás és a nem kategorizáló harnesszel készült 26 mutánsos futások (köztük az első, amelynek alapállapota piros volt, ezért érvénytelen), valamint egy köztes 28/31-es futás, amelyet egy véletlenül kiesett teszt torzított. (E felsorolás a munkamenet közlésén alapul, nem mentett naplón; ezért nem hivatkozunk rájuk bizonyítékként.) **„Elkapott” azt jelenti, hogy legalább egy teszt elbukott, nem feltétlenül a célzott teszt.** Az élő mutánsok elemzése a 8. szakaszban van.
**Külön parancsokkal végzett, NEM automatizált ellenőrzések** (az előkészítési jelentés részei): base/alt generálása és `sha256sum -c`; a H1/H2 és az ellenőr parancssori futtatása a generált fájlokon; a Python 3.12.3 és 3.13 közötti bájtazonosság (`cmp`) — ez csak a generálásra vonatkozik; a teljes tesztkészlet Python 3.12 alatt NEM igazolt (ott nincs `pytest`). Ezek a parancsok és eredményeik nem tesztek, és nem helyettesítik a tesztfutást.
**A kerekítésről:** a kézi esetek (`0,125`, `0,025`, `100,005` stb.) megkülönböztetik a fél-páros és a fél-felfelé módot, és a teszt azt is ellenőrzi, hogy a történet nyitás/zárás kerekítése fél-páros, a magas/alacsony plafon/padló. A rögzített történet számítása maga nem tartalmaz pontos fél-cent esetet (külön, egyszeri kísérlettel megállapítva, nem tesztelve): a kerekítési mód választása a kimeneten nem látszik. A képleteket ez nem érinti.

## 8. Fennmaradó korlátok
**Fájlbiztonság (a kiírás)**
- **Mit garantál a kód (a saját viselkedésére):** végleges nevet soha nem töröl, ír felül, csonkít vagy nevez át; idegen vagy lecserélt fájlt nem töröl; a hiányos, idegen vagy bizonytalan állapotot jelenti (3-as kód), és csak a 0-s kilépési kód jogosult rekord-jóváhagyásra.
- **Mit NEM garantál:** nincs védelem azonos felhasználó kódja ellen, amely a kimeneti könyvtárban szándékosan, egyidejűleg cseréli az útvonalakat; ilyen kód amúgy is törölhet vagy átírhat mindent, amit mi. Nem atomi a páros közzététel: a két végleges fájl között megszakadhat a folyamat.
- **Fennmaradó verseny az ideiglenes nevek takarításánál:** az `lstat`/azonosság-ellenőrzés és az `unlink` között egy másik folyamat lecserélheti az ideiglenes nevet (a POSIX nem ismer feltételes törlést); a nyitott fájlleíró az inode-újrahasznosítást kizárja, ezt a rést nem. Következmény legfeljebb egy véletlen nevű, rejtett ideiglenes név törlése; végleges nevet ez nem érint. Az ideiglenes csere a link ELŐTT az `os.link` útvonal alapú természete miatt idegen tartalmat tehet a végleges névre: ezt az utólagos azonosság-ellenőrzés észleli és jelenti, megelőzni nem tudja (fd-alapú `linkat`/`O_TMPFILE` Linux-specifikus, nem része).
- **Hard-link:** a célfájlrendszernek támogatnia kell az `os.link`-et (környezeti feltétel). Más tulajdonságú tartalék írási mód nincs; támogatás hiányában a kiírás hibával leáll.
- **Tartósság:** nincs `fsync` sem a fájlon, sem a könyvtáron; áramkimaradás után a végleges fájl üres vagy csonka lehet. A felülírásmentesség és a tartósság két külön tulajdonság; csak az előbbi állított.
- **Szűk, körülhatárolt ablak:** az `os.open` visszatérése és a `tmps.append` között (`_create_exclusive`) egy aszinkron jelzés (`KeyboardInterrupt`) vagy `MemoryError` egy nyitott fájlleírót és egy 0 bájtos, rejtett `.…tmp` fájlt hagyhat vissza, amely NINCS jelentve. Következmény: `MemoryError` esetén `GenerationError` jön üres maradéklistával, a CLI 2-es kódot és a „nem hagyott maga után fájlt” üzenetet adja, ami e szűk esetben téves; `KeyboardInterrupt`/`SystemExit` jegyzet és jelentés nélkül terjed tovább. A végleges neveket ez nem érinti, idegen fájlt nem töröl, és az eredeti kivétel megmarad. A kód nem számít több dobó műveletre az ablakban. Ez elfogadott, dokumentált korlát (privát, nem ellenséges könyvtár), nem a takarítási szerződés teljesítése.
- A sikerági takarítás közbeni megszakítást a kód jelenti (kivétel-jegyzet, CLI-hibakimenet); a HIBAÁGI jelentés vagy takarítás közbeni újabb megszakítás után nincs jelentés a maradékról (az eredeti kivétel csak a `__context__`-ben marad).
- A belső `try` vége és a `return` közötti ablak (az fd-záró `finally` ciklus, a `Written` létrehozása): ide eső megszakítás jelentés nélkül terjed tovább; a végleges pár ekkor teljes és takarított, a folyamat nem 0-val ér véget (kezeletlen kivétel), és a le nem zárt leírók a folyamat végén záródnak.
- A teljes pár ellenőrzése pillanatnyi: a 0-s kód előtti újraellenőrzés után bekövetkező cserétől nem véd.
- 4-es esetben az ideiglenes név a végleges inode hard-linkje: az ideiglenes úton át történő módosítás a végleges fájlt is változtatja, amit a `4` nem vizsgál.
- A fájlmód `0o666 & ~umask` (a mód ellenőrzése nincs; privát könyvtár feltételezés). Az `os.pread` rövid olvasása hamis eltérést (fail-closed) adna.
- Lezárt kimenet (BrokenPipe) a hash-sor kiírásakor kezeletlen kivétel (a kimeneti pár ekkor teljes).
- A `mkdir` után bekövetkező hibánál az újonnan létrehozott könyvtár megmarad.
- Üres vagy relatív `--out` kifejezett hiba nélkül a munkakönyvtárhoz oldódik; az üres `--out ""` csendben kimarad. Az `argparse` hibakódja (2) ütközik a CLI „2 = nem hagyott fájlt” jelentésével. A `--hash-check`/`--check-file` hibakódját (1) a sikertelen vagy maradékos `--out` kódja (2/3/4) felülírja; sikeres `--out` mellett H1/H2 hiba esetén a kód 1 (soha nem 0).
- Kis-/nagybetűre érzéketlen fájlrendszeren a munkafa-ellenőrzés hamis negatívot adhat (Linuxon nincs). A `resolve_out_dir` és a kiírás között szimbolikus link-csere (TOCTOU) elvileg lehetséges.
- A generátor `--check-file` hibás útvonalnál nyomkövetést adhat; a `--hash-check` hiányzó művelet esetén is lefut a hibaüzenet előtt.
**Nyitott teszt-gyengeségek és felülvizsgálati megállapítások (nem javítva ebben a körben)**
*Mutációs kísérlet, végső eredmény: 31 mutáns, 29 elkapott, 2 él.* A két élő mutáns az „ellenőrzési hiba nem adhat 0-s kilépési kódot” követelmény ágait érinti: az M29 a `_fd_holds` mindhárom hívóhelyét (a sidecar közzététel előtti ellenőrzése, a közzététel utáni tartalom-ellenőrzés, a pár végi újraellenőrzés), az M30 a pár végi újraellenőrzés `unknown` ágát. A besorolás a kód olvasásából levezetett; reprodukáló futás nem készült.
- **M29 — a `_fd_holds` elnyeli az `OSError`-t.**
  - Mutáció: `return os.pread(tmp.fd, len(content) + 1, 0) == content` helyett `try: return os.pread(...) == content` és `except OSError: return True`.
  - Viselkedési hatás: az `os.pread` hibája (pl. I/O-hiba) „a tartalom egyezik”-ként értékelődik a három `_fd_holds` hívásnál: a sidecar ideiglenes fájlának közzététel előtti ellenőrzése, a közzététel utáni tartalom-ellenőrzés és a pár végi újraellenőrzés. Az eredeti kód a hibát `GenerationError`-ba csomagolja, és nem ad 0-t. Az adatfájl ideiglenes példányának első ellenőrzése közvetlen `os.pread` (nem `_fd_holds`), azt a mutáns nem érinti. A sidecar ideiglenes fájlját kizárólag a `_fd_holds` olvassa, így rá a hiba észrevétlen maradhatna, és a kimenet 0-t kaphatna ellenőrizetlen sidecar-tartalommal.
  - Miért él: egyetlen teszt sem injektál `os.pread` hibát. A tesztek az `os.link`, `os.unlink`, `os.open`, `os.write`, `os.fstat` és `os.lstat` hibáit injektálják.
  - Besorolás: **valódi teszthiány** (nem ekvivalens, nem hatástalan mutáns). Megalapozottság: a kódból levezetett, nem futtatott.
- **M30 — az `unknown` állapot átmegy a pár végi újraellenőrzésen.**
  - Mutáció: `if state != "ours" or not _fd_holds(tmp, content):` helyett `if state in ("absent", "foreign") or not _fd_holds(tmp, content):`.
  - Viselkedési hatás: ha a végleges név állapota csak a pár végi újraellenőrzéskor nem állapítható meg (`lstat` vagy `fstat` hiba), az eredeti kód `GenerationError`-t dob (3-as kód, bizonytalan állapot); a mutáns átengedi, és a kimenet 0-t kaphat.
  - Miért él: a közzététel közbeni, hivatkozásonkénti ellenőrzés (`state != "ours"`) a tartós `unknown` hibát már korábban elkapja, és a meglévő `unknown`-tesztek tartós hibát injektálnak; egyetlen teszt sem kapcsolja be a hibát csak a pár végi újraellenőrzés előtt.
  - Besorolás: tartós hibára ekvivalens (azt a korábbi ellenőrzés fedi), késői vagy átmeneti hibára **valódi teszthiány**; védelmi mélységi sor. Megalapozottság: a kódból levezetett, nem futtatott. **Bizonytalan:** hogy egy átmeneti `lstat`/`fstat` hiba a gyakorlatban mennyire elérhető.
  - Mindkét élő mutáns az „ellenőrzési hiba nem adhat 0-s kilépési kódot” követelményt érinti. A kód a statikus felülvizsgálatok szerint teljesíti, de ez a két ág nincs teszttel védve.
- **N-B (alacsony).** A `syn_blind_001.py` modul-docstringjének 3-as kód leírása nem említi a sikertelen kiírást ideiglenes maradékkal vagy idegen ideiglenes névvel, pedig a kód ezekre is 3-at ad (e dokumentum 6. szakasza teljes). Hatás: csak a docstringből tájékozódó olvasó várhatna mást; a viselkedést nem érinti.
- **N-C (alacsony).** Ha a `--hash-check`/`--check-file` hibás (1), a kiírás teljes, de ideiglenes maradék van, a kód 4-et ad; a 4-es hibakimenet nem említi a H1/H2 hibát (az a standard kimeneten van). Hatás: pontatlan diagnózis; a követelmény (csak a 0 jogosult rekord-jóváhagyásra) teljesül. A kombináció nincs tesztelve.
- **N-D (alacsony).** Az új tesztek a kimeneti útvonalat a `tmp_path / fájlnév` szövegével hasonlítják össze, a kód viszont a `resolve_out_dir` (feloldott útvonal) eredményét írja ki. Ha a `tmp_path` szimbolikus linken át érhető el, ezek a tesztek hamis hibával elbuknának; Linuxon a pytest `tmp_path` feloldott. Hatás: hordozhatóság; hamis átmenő eredményt nem okoz.
- A `--check-file` + `--out` kombináció csak a kimeneti hash-sor szempontjából tesztelt; a H2 hiba utáni többi precedencia-eset nem.
- A `test_the_held_descriptor_pins_the_inode…` és az `old_ino != new_ino` állítások a kernel viselkedését mérik; a „fd nyitva marad” tulajdonságot a `fstat(fd)`-t használó „bizonytalan” tesztek védik.
- Az ellenőr tesztjeinek egy része (negatív esetek) csak az állapotot vagy csak a diagnosztikát állítja, nem mindkettőt.
- A sikerági megszakításnál a jegyzet a teljes, ellenőrzött párt is „hiányos, nem befagyasztott”-ként jelzi (konzervatív).

**Ellenőr**
- A CONTRACT ellenőrzés a fájlt az útvonalról külön olvassa be (nem ugyanazokból a bájtokból), így két olvasás között változó fájlnál a négy eredmény eltérő tartalomra vonatkozhat.
- Eltérő sávszámnál az időbélyeg szerinti párosítás a sorrendet nem vizsgálja (a megfordított, 119 elemű fájlt csak a CONTRACT `not_increasing` jelzi).
- A „nem értelmezhető” szót a három ellenőrzés kissé eltérően alkalmazza (pl. nem ASCII `_note`: CONTRACT rendben, FORMULA nem értékelhető, SERIALIZATION hiba; ötezer jegyű `volume`: a FORMULA üzenete pontatlan).
- A szimbolikus linkként megadott fájlnál a sidecar nevét a link nevével veti össze, a tartalom a célé.
**Közös gondolati réteg és horgonyok**
- A független ellenőr és a generátor közös gondolati rétege (1-alapú sávindex, `T0 + k nap`, a kanócok a kerekített árból) az ellenőrrel nem fogható; egyedül a kézi horgonyok (1., 55–56. sáv) védenek. További horgonyok és beégetett hash-referencia nincs (a hash-eket ebben a körben nem emeljük aranyreferenciává).
- A `repr`-körbefordulás-ellenőrzés két tizedes, 2^53 alatti árnál nem bukhat el: védelmi réteg, nem aktív kapu.
- A `STAGES` csak dokumentáció, a `bar_spec` határaihoz nincs kötve.
- Python ≥ 3.11 ajánlott az `add_note` miatt (a kód `hasattr`-védett); a repóban nincs `requires-python` kikötés.

## 9. Mit NEM állít ez a lépés
Nem választ piacot, valódi költségmodellt, benchmarkot, küszöböt, „próba”-definíciót, bootstrap-típust vagy blokkhosszt, és az 50 próbás korlátot sem erősíti meg; ezek külön, kifejezett jóváhagyást igénylő statisztikai döntések. A K1–K3 naplózási kategóriák csak a rögzítésre vonatkoznak. A generált base/alt hash-ek az előkészítési jelentés értékei, nem jóváhagyott előzetes rekord; a mérési kapu zárva marad. A stratégia és a teljes történeten végzett visszajátszás későbbi, külön engedélyezett lépés; a két korábban létrejött stratégiafájl nem tartozik ehhez a csomaghoz.
