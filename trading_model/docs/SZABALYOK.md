# A kereskedelmi modell szabálykönyve

Modulszintű szabályok. A repó `CLAUDE.md`-je is érvényes (nincs éles szolgáltatóhívás, a `results/` nem kerül a repóba, a PR és a merge csak a felhasználó esetenkénti jóváhagyásával). Ez a fájl **nem módosítja** a `CLAUDE.md`-t és az Őr szabályzatát; a javasolt kiegészítések a végén vannak, jóváhagyásra várnak.

## Szigorú tiltások
1. **Nincs éles megbízás, valódi pénz, bróker- vagy tőzsdei kapcsolat.** Papírkereskedés is csak hamis átvitellel, naplózva, külön lépésben.
2. **Nincs hálózati kód** a modulban. Ha később kell, egyetlen külön `live/` csomagban lehet, külön jóváhagyással; a többi modul hálózatmentes marad (teszt őrzi).
3. **Nincs kulcs, jelszó vagy hitelesítő** a kódban, a naplóban, a kimenetben vagy a fixture-ben.
4. **Nincs költség és fizetős szolgáltatás** jóváhagyás nélkül; nincs harmadik szolgáltató bevonása.
5. **Nincs jövőbe látás.** Egy döntés csak olyan adatot használhat, amelynek `available_at` ideje a döntés ideje előtt vagy azzal egyidős.
6. **A zárt teszttartomány egyszer nyitható.** A hangolás, a paraméterválasztás és a stratégiaváltozatok szűrése nem láthatja; a megnyitás tényét a lezárási jegyzék rögzíti.
7. **Nincs befektetési tanács, hozamígéret vagy „teljesítmény"-állítás** a kimenetben, és szintetikus adaton elért eredmény nem olvasható teljesítménynek.

## A kapu és a rögzítés
- A kutatási kérdést, az adatfelosztást, a költség- és csúszásmodellt, a mérőszámokat és a kapu küszöbeit **az első mérés előtt** kell rögzíteni (lezárási jegyzék, hash-ekkel).
- A rögzítés után **csendes módosítás nincs.** Utólagos változtatás csak a felhasználó kifejezett jóváhagyásával, a jelentésben és a kapu kimenetében jelölve. (A Média-Zajban a kapu `min_voters` értékét 2026-11-17-én 4-ről 2-re állították, az eredmények ismeretében; ezt utólagos változtatásként kellett jelezni. A kereskedelmi modellben ez a leggyakoribb önbecsapási forrás, ezért itt szigorúbb.)
- **Többszörös tesztelés:** minden kipróbált stratégiaváltozatot és paraméterkombinációt naplózni kell; a kapu a próbák számát figyelembe veszi (a módját a rögzítéskor kell megadni).
- A kapu kimenete három állapot lehet, a Média-Zaj mintájára: átment, nem ment át, eldönthetetlen; és külön `nem_szamolhato`, ha az adat nem elég (pl. túl kevés ügylet).

## Naplózás
Minden futásnál rögzíteni kell: az adatfájl azonosítóját és SHA-256 értékét, a konfiguráció hash-ét, a magot (seed), a próbált változatok számát, a kimenetelt. Kulcs sehol nem szerepelhet.

## Adat
- Szintetikus adat jelölt (`synthetic: true`, `SYN-` szimbólum), és nem keveredhet a mentett, valódi adattal.
- A bemenetet a modul nem módosítja; a hibás adatot nem javítja és nem hagyja ki csendben.
- Nyers adat és generált kimenet nem commitolható.

## Ellenőrzés és ennek korlátai
A szabályokat ma **tesztek** őrzik (hálózatmentesség, a közös hálózati zár, az adatszerződés). A repó Őre (`scripts/policy_guard.py`) ezeket a modulszintű szabályokat **nem ismeri**; az Őr szabályzatának bővítése külön, jóváhagyott lépés.

## Javasolt kiegészítések a `CLAUDE.md`-hez (NEM bevezetve, jóváhagyásra várnak)
- Kódhelyek: a kereskedelmi modell kódja a `trading_model/`, tesztjei a `trading_model/tests/`, eredményei a `trading_model/results/` (git nem követi).
- Szigorú tiltás: éles megbízás, valódi pénz és bróker- vagy tőzsdei kapcsolat tilos.
- A `pytest.ini` `testpaths` bővítése a `trading_model/tests` mappával.
- Az Őr (`config/guard_policy.json`) bővítése a modul tiltásaival.
