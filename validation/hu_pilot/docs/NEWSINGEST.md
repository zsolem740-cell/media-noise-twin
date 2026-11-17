# Hírgyűjtés, offline feldolgozó

`validation/hu_pilot/newsingest.py` egy könyvtárnyi mentett bemeneti fájlból (capture JSON) TSV-t, JSONL-hiánylistát és eredetjegyzéket készít.
**Csak helyi fájlokat olvas.** Nem hív hálózatot, szolgáltatót vagy kulcsot, és nem kapcsolódik Firecrawlhoz, RSS-hez, Perplexityhez vagy Composióhoz: a bemenet egy semleges formátum, amelyet bárki előállíthat. Nem része a pilot kiválasztásának, a promptoknak (v1, v2, v3) és a modellfuttatásnak; nem súlyoz és nem címkéz.

```
python -m validation.hu_pilot.newsingest --input-dir MAPPA [--out-dir MAPPA]
```
Kimenet (alapból `validation/hu_pilot/results/newsingest/`, a git nem követi; ide kívülre írni a modul megtagadja). Minden futás mind a négy fájlt felülírja.

| fájl | tartalom |
|---|---|
| `news.tsv` | a megtartott rekordok, a `COLUMNS` oszlopaival |
| `problems.jsonl` | a problémák, soronként egy; hibamentes futásnál nulla bájtos fájl |
| `provenance.jsonl` | soronként egy megtartott rekord eredete: `url`, `input_file`, `record_index` |
| `manifest.json` | a bemeneti fájlok SHA-256 értéke és mérete, a kimenetek SHA-256 értéke, darabszámok; nincs benne futási idő vagy abszolút útvonal |

Kilépési kód: `0` lefutott és nincs fájlszintű hiba (a rekordszintű problémák a `problems.jsonl`-ben vannak); `1` legalább egy bemeneti fájl sérült vagy hibás szerkezetű volt (**nem teljes siker**); `2` hibás használat, nem létező bemeneti könyvtár, az eredménymappán kívüli kimenet, vagy egymásba ágyazott bemeneti és kimeneti könyvtár.

## Bemenet
A bemeneti könyvtár összes `*.json` fájlja, rekurzívan (kisbetűs kiterjesztés). A fájl neve a bemeneti könyvtárhoz képesti **relatív POSIX-út** (`input_file`); ezt a modul a ténylegesen beolvasott fájlból képezi, a fájl tartalmában szereplő bármilyen `input_file` jellegű állítást figyelmen kívül hagy. A könyvtáron kívülre mutató szimbolikus hivatkozást nem olvassa (`invalid_file`).

```json
{"schema": 1, "synthetic": true, "capture_id": "...", "source": "...", "fetched_at": "2026-01-15T10:00:00Z",
 "records": [{"url": "...", "title": "...", "published_at": "...", "source": "...", "fetched_at": "...",
              "title_source": "rss", "date_source": "rss", "status": "ok"}],
 "links": ["https://..."]}
```
- **Szerkezet:** a fájl JSON objektum; `schema` pontosan az egész szám `1` (a `1.0`, `"1"`, `true` nem jó); `synthetic` logikai; `records` és/vagy `links` lista, legalább az egyik. Ismétlődő kulcs, `NaN`/`Infinity`, nem UTF-8 bájt vagy BOM: `invalid_json`. Bármely szerkezeti hiba: `invalid_structure`. Mindkét esetben **fájlszintű hiba**, a fájlból nem lesz sor.
- Megengedett felső szintű kulcsok: `schema`, `synthetic`, `capture_id`, `_note`, `source`, `fetched_at`, `records`, `links`. Más kulcs: `unknown_field` (a fájl feldolgozódik).
- `synthetic: true` a kitalált, nem éles mintát jelzi; a jegyzék `contains_synthetic` mezője ezt tükrözi. A repó mintái (`tests/fixtures/newsingest/`) mind szintetikusak, kitalált címekkel és a fenntartott `.example` tartományokkal.
- `source` és `fetched_at` a fájl szintjén alapérték: egy rekord a sajátjával felülírhatja. Cím és dátum nem örököl alapértéket. Üres vagy hiányzó rekordszintű érték esetén az alapérték érvényes; érvénytelen rekordszintű érték esetén az alapérték **nem** lép a helyére (a kimeneti mező üres, a hiba bejegyezve).
- **Rekord:** a `records` elemei objektumok (különben `invalid_record`); a `links` elemei URL-szövegek (különben `invalid_record`). Egy `links` elem olyan rekord, amelynek csak URL-je van. Ismeretlen rekordkulcs: `unknown_field` (a mező neve a `field` értéke).

## Sorrend és `record_index`
Feldolgozási sorrend: a fájlok az `input_file` kódpont szerinti sorrendjében; egy fájlon belül először a `records`, majd a `links` elemei sorszám szerint. A `record_index` ennek a `records + links` összefűzésnek a nulláról induló indexe: a `links` indexei a `records` után **folytatódnak**, nem indulnak újra, így egy fájlon belül minden elem indexe egyedi. Fájlszintű bejegyzésnél `null`.

## URL-elfogadás és azonosság
Az URL elfogadási szabálya (`check_url`): szöveg; legfeljebb 2048 karakter; nincs benne szóköz-jellegű vagy vezérlő karakter, **a szélén sem** (nem vágjuk meg, nem cserélünk tabulátort vagy sortörést: az ilyen URL hibás); `http://` vagy `https://` séma; nem üres hoszt (betű, szám, pont, kötőjel; nem kezdődhet és nem végződhet ponttal vagy kötőjellel; nincs `..`); nincs felhasználónév (`@`); a port, ha van, 1-65535. Nem üres szöveg önmagában nem elég.
Hibás URL-ű rekord nem kerül a `news.tsv`-be; a `problems.jsonl`-ben az `url` az eredeti, javítatlan érték (`invalid_url` esetén), vagy `null` (`missing`, `invalid_type`).

**URL-azonosság:** két URL pontosan akkor azonos, ha a szövegük karakterre megegyezik. Nincs kisbetűsítés, záró `/` levágás, paraméter- vagy töredéktörlés, százalékkód-egységesítés: az `https://x/a` és az `https://x/a/` két külön rekord. (Ismert korlát: ugyanarra az oldalra mutató, eltérően írt URL-ek külön sor lesznek.)
**Deduplikálás:** az első találat nyer a fenti feldolgozási sorrendben. A későbbi azonos URL-ű rekord teljes egészében kimarad (a tartalmát akkor sem használjuk, ha több adat van benne), és egy `duplicate_url` bejegyzést kap (`field`: `url`, a kihagyott rekord `input_file` és `record_index` értékével).

## Mezők és ellenőrzésük (`news.tsv`)
Oszlopok, ebben a sorrendben: `url`, `title`, `published_at`, `source`, `title_source`, `date_source`, `fetched_at`, `status`. A sorok feldolgozási sorrendben állnak. Minden érték szöveg; hiányzó érték üres szöveg.

- **Típus:** a mezők JSON-típusát ellenőrizzük; rossz típus (szám, lista, objektum, logikai) `invalid_type`, **nem alakítjuk szöveggé**, a kimeneti mező üres.
- **`title`, `source`:** `null`, `""` és a csak szóközökből álló érték hiányzónak számít (`missing`; `source` esetén ez nem hiba, az alapérték lép érvénybe). A tabulátor, a `\r`, `\n` és a többi sortörő karakter (`\x0b`, `\x0c`, `\x1c`-`\x1e`, `\x85`, U+2028, U+2029) **egy-egy szóközzé** válik (nem sűrítjük), a szélek levágva. Egyéb vezérlőkarakter: `control_character`. Hossz: cím legfeljebb 500, forrás legfeljebb 200 karakter (`too_long`). Unicode-normalizálás nincs; az ékezetek és idézőjelek változatlanok. A hiányzó címet nem pótoljuk, az URL-ből (szlugból) sosem képzünk címet.
- **`published_at`, `fetched_at`:** elfogadott alak: `ÉÉÉÉ-HH-NN` (csak `published_at`) vagy `ÉÉÉÉ-HH-NNTÓÓ:PP:MM[.tört]` kötelező időzónával: `Z` vagy `±ÓÓ:PP`, nagy `T` és `Z`; létező naptári nap és időpont. Az érték változatlanul marad (nincs UTC-re váltás, nincs levágás). Zóna nélküli időpont: `missing_timezone`. Más hiba: `invalid_date`. `null` és csak szóköz: `missing`. Az URL-ben látható dátumot **nem** használjuk publikálási időnek. A `fetched_at` kizárólag a bemenetben rögzített lekérési idő (a rekordé vagy a fájl alapértéke); hiányában üres, soha nem a futás ideje.
- **`status`:** a validáció eredménye, a bemenet `status` mezőjét nem vesszük át. `ok`, ha a `title` és a `published_at` is érvényes és nincs a rekordnak a `title`, `published_at`, `source`, `fetched_at`, `title_source` vagy `date_source` mezőjére bejegyzett problémája; egyébként `incomplete`. A bemenet `status` állítása: nem szöveg `invalid_type`; a készleten kívüli érték `unknown_value`; a kiszámítottól eltérő érvényes érték `status_mismatch` (a kimeneten mindig a kiszámított áll).

### Mezőeredet (`title_source`, `date_source`)
Rögzített értékkészlet mindkettőre: `rss`, `page`, `manual`, `unknown`, `missing`. A bemenet eredet-állítása **állítás, nem igazolt tény**: a modul nem tudja ellenőrizni.
- Van érvényes érték, nincs állítás: `unknown` (nem adunk igazolt eredetet ismeretlen eredetű mezőnek).
- Van érték és az állítás `rss`/`page`/`manual`/`unknown`: az állítás.
- Nincs érvényes érték: a kimenet `missing`.
- **Ellentmondás** (`source_contradiction`, `field`: `title_source` vagy `date_source`): érték van, de az állítás `missing` (a kimenet `unknown`); vagy érték nincs (hiányzó, nem hibás), de az állítás nem `missing` (a kimenet `missing`).
- A készleten kívüli állítás `unknown_value`, a nem szöveg `invalid_type`: az állítást figyelmen kívül hagyjuk, de a hibát jelentjük; a kimeneti érték a fenti szabály szerint `unknown` vagy `missing`, soha nem az ismeretlen állítás.

## Hiánylista (`problems.jsonl`)
Soronként egy JSON objektum, **egy sor egy probléma**; egy rekordhoz több sor tartozhat. Kulcsok, ebben a sorrendben: `url`, `field`, `reason`, `source`, `input_file`, `record_index`. Ismeretlen értékhez JSON `null` tartozik, kitalált helyettesítő érték nincs.
- `url`: a rekord URL-je; `null`, ha nincs vagy nem szöveg; az eredeti, javítatlan szöveg `invalid_url` esetén. Fájlszintű bejegyzésnél `null`.
- `field`: a mező neve (`url`, `title`, `published_at`, `source`, `fetched_at`, `title_source`, `date_source`, `status`), ismeretlen kulcsnál annak neve; `null`, ha a probléma az egész rekordra vagy fájlra vonatkozik.
- `reason`, rögzített értékkészlet: `missing`, `invalid_type`, `invalid_url`, `invalid_date`, `missing_timezone`, `control_character`, `too_long`, `unknown_value`, `source_contradiction`, `status_mismatch`, `unknown_field`, `duplicate_url`, `invalid_record`, `invalid_json`, `invalid_structure`, `invalid_file`. Az utolsó három fájlszintű.
- `source`: a rekord érvényes forrásneve (a rekordé vagy a fájl alapértéke), `null`, ha nincs.
- `input_file`, `record_index`: lásd fent.
- Sorrend: `input_file`, `record_index` (a fájlszintű `null` előre), a mező sorrendje az oszlopokéval megegyezően (ismeretlen kulcsok utánuk), majd `reason`.
- A hiányzó cím és a hiányzó dátum is bejegyzés (`missing`), a rekord ettől még megmarad a `news.tsv`-ben. Hiányzó `source` és `fetched_at` megengedett, nem hiba.
- A sorokban a sortörőként kezelt karakterek (U+2028, U+2029, U+0085) `\u` escape-pel szerepelnek, így egy rekord egy fizikai sor.

## Kimeneti formátum
- **TSV:** `csv.DictWriter`, UTF-8 (BOM nélkül), `newline=""`, elválasztó tabulátor, sorvég `\n`, idézőjel `"`, idézés `QUOTE_MINIMAL` (a `csv` modul dönt; az idézőjel megkettőzve). Az oszlopok ellenőrzése: a fejléc pontosan a fenti nyolc oszlop. Egy rekord egy fizikai sor, mert a szöveges mezők tabulátora és sortörései szóközzé váltak; az URL-eket nem módosítjuk.
- **JSONL:** UTF-8, `\n` sorvég, az ékezetek megmaradnak. Üres hiánylista: nulla bájtos fájl, amely a korábbi tartalmat felülírja.
- **Determinizmus:** azonos bemeneti könyvtár tartalmából a négy fájl bájtra azonos, akkor is, ha a könyvtár máshol van; nincs benne futási idő, véletlen azonosító vagy abszolút útvonal.

## Hálózatmentesség
A modul nem importál hálózati vagy folyamatkezelő modult (a pilot meglévő tesztje is őrzi). A pilot tesztjeit a közös, automatikusan alkalmazott hálózati zár védi (`tests/conftest.py`, a pilot `conftest.py` importálja). Ez **Python-szintű védelem** (a `socket.socket.connect` hívás szűrése), **nem operációs rendszer szintű hálózati elszigetelés**: nem fog meg minden utat (pl. névfeloldás, UDP, más folyamat).

## Amit az első változat nem tud
- Nem olvas közvetlenül Firecrawl-, RSS-, Perplexity- vagy Composio-választ; ehhez külön, később jóváhagyott átalakító kell, amely a fenti formátumot állítja elő.
- Nem ellenőrzi a publikálási idő hihetőségét (pl. jövőbeli vagy nagyon régi év), csak a formátumát és a naptári érvényességét.
- A hosszan eltérően írt, de ugyanarra az oldalra mutató URL-eket nem vonja össze.
