# Árfolyam-adatszerződés

A `trading_model/data.py` egy mentett idősor-fájlt (capture JSON) ellenőriz. **Csak helyi fájlt olvas**, hálózatot, szolgáltatót és kulcsot nem használ, a bemenetet nem módosítja.
Nem javít és nem találgat: egyetlen blokkoló hiba esetén az idősor **nem használható** (nincs csendes kizárás, kerekítés vagy típusátalakítás), és a hibákat strukturált bejegyzések mondják meg.

## Formátum
```json
{"schema": 1, "synthetic": true, "symbol": "SYN-A", "timeframe": "1d", "capture_id": "...",
 "bars": [{"timestamp": "2026-01-03T00:00:00Z", "open": 100.0, "high": 102.0, "low": 99.9, "close": 101.3, "volume": 770636,
           "available_at": "2026-01-03T00:00:00Z"}]}
```
- **Szerkezet:** JSON objektum; `schema` pontosan az egész `1`; `synthetic` logikai (kötelező: a szintetikus és a valódi adat nem keveredhet); `symbol` (betű, szám, `.`, `_`, `-`, legfeljebb 32 karakter); `timeframe` a rögzített készlet egyike; `bars` nem üres lista. Ismétlődő kulcs, `NaN`/`Infinity`, nem UTF-8 bájt vagy BOM: `invalid_json`; bármely szerkezeti hiba: `invalid_structure`. Mindkettő fájlszintű hiba, az idősor nem használható.
- Megengedett felső szintű kulcsok: `schema`, `synthetic`, `symbol`, `timeframe`, `bars`, `capture_id`, `_note`. Más kulcs: `unknown_field` (nem blokkoló).
- **`timeframe`** rögzített készlete: `1m`, `5m`, `15m`, `1h`, `4h`, `1d`.

## Sáv (`bars` elem)
Kötelező mezők, ebben a rangsorban: `timestamp`, `open`, `high`, `low`, `close`, `volume`, `available_at`. Ismeretlen kulcs: `unknown_field` (nem blokkoló).
- **`timestamp`: a sáv VÉGE**, nem az eleje. Alak: `ÉÉÉÉ-HH-NNTÓÓ:PP:MM[.tört]` kötelező időzónával (`Z` vagy `±ÓÓ:PP`), nagy `T` és `Z`; az érték UTC-re váltva kerül a modellbe. Zóna nélküli időpont: `missing_timezone`; más hiba: `invalid_time`; `null`: `missing`; nem szöveg: `invalid_type`.
- **`available_at`:** mikor vált a sáv adata ténylegesen ismertté. **Nem lehet korábbi a `timestamp`-nél** (különben `lookahead`: olyan adatot állítana ismertnek, ami még nem létezett). Késleltetett adatnál később is lehet. Ez a jövőbe látás elleni alapvédelem: a döntés csak olyan sávot használhat, amelynek `available_at` ideje nem későbbi a döntés idejénél.
- **`open`, `high`, `low`, `close`:** szám (egész vagy lebegőpontos; logikai és szöveg nem), véges, **> 0**. Szöveg nem alakul számmá.
- **`volume`:** szám, véges, **>= 0**.
- **OHLC-összhang:** `high >= max(open, close, low)` és `low <= min(open, close, high)`; ellenkező esetben `ohlc_inconsistent` (a `high` vagy a `low` mezőn).
- Nem objektum elem a `bars`-ban: `invalid_record`.

## Sorrend
Az időbélyegek **szigorúan növekednek**. Azonos pillanat (más időzónás írásmóddal is): `duplicate_timestamp`; visszalépés: `not_increasing` (a későbbi sávon). A hiányzó sávokat (rések) a modul **nem ellenőrzi** és nem tölti ki.

## Problémabejegyzés
Egy bejegyzés egy probléma; kulcsok, ebben a sorrendben: `field`, `reason`, `symbol`, `input_file`, `bar_index`. Ismeretlen értékhez `null` tartozik. A `bar_index` a `bars` lista nulla alapú indexe (fájlszintű hibánál `null`).
`reason` rögzített értékkészlete: `missing`, `invalid_type`, `invalid_value`, `invalid_time`, `missing_timezone`, `ohlc_inconsistent`, `lookahead`, `duplicate_timestamp`, `not_increasing`, `unknown_field`, `invalid_record`, `invalid_json`, `invalid_structure`. Blokkoló mind, az `unknown_field` kivételével.

## Szintetikus adat
A `trading_model/synthetic.py` fix magból (seed) determinisztikus idősort állít elő: geometriai bolyongás, a nyitó az előző zárás, a magas/alacsony a nyitó és a záró köré épül. Minden kimenet `synthetic: true` jelölésű és `SYN-` előtagú szimbólumú. **Nem valódi piaci adat, és nem is akar annak látszani;** csak az eszköz próbájára való, eredménye nem teljesítmény.

## Amit az adatszerződés nem tud
- Nem ellenőrzi a réseket, a tőzsdei naptárat, a nyitvatartást.
- Nem kezeli a tőkeesemények (osztalék, felosztás) korrekcióját, a devizát és az árfolyam-pontosságot (lebegőpontos számok, nincs decimális ábrázolás).
- Nem ellenőrzi az adat forrását és hitelességét: a `synthetic: false` jelölés a bemenet állítása.
