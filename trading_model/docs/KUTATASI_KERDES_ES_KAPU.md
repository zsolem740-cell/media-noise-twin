# Kutatási kérdés és kapu: a PROTOKOLL RÖGZÍTVE (2026-11-19), a költség, a viszonyítás és a küszöb NYITOTT

**Állapot: `protocol_frozen`.** A protokoll-paramétereket a felhasználó a munkamenetben kifejezetten jóváhagyta, és a `trading_model/gate_config.json` rögzíti őket. A költségmodell, a viszonyítási alapok és a kapu számszerű küszöbe (a döntési szabállyal együtt) **még nincs rögzítve**, ezért **a mérés nem indulhat** (`gate.measurement_ready` hamisat ad).

- Rögzített tartalom SHA-256 (kanonikus JSON): `f7fd5ecd22b8430a086e7ce6698070974e2eaed6c48a672253c414c526de4e29`
- A hash-t a `gate_config.json` tartalmából a `gate.config_hash` számolja; a teszt és ez a dokumentum is rögzíti. A rögzített tartalom bármilyen csendes módosítása elbuktatja a tesztet.

## Kutatási kérdés
Egy **előre, a mérés előtt megadott** jelgenerátor-szabály egy **zárt, időben a tanítás után álló** teszttartományon, **költségekkel és csúszással** megáll-e a rögzített kapun, úgy, hogy a hangolás a teszttartományt nem látta?

Ez megvalósíthatósági kérdés, nem hozamígéret: a Média-Zaj pilotja is azt vizsgálta, hogy a módszer működik-e, nem azt, hogy mennyire pontos.

## Nem cél
Hozam- vagy nyereségígéret, befektetési tanács, éles kereskedés, a piac „előrejelzése", és bármi, ami szintetikus adaton mérne teljesítményt.

## Rögzített protokoll-paraméterek
| Paraméter | Rögzített érték | Jelentés |
|---|---|---|
| Adatfelosztás (`split_percent`) | tanító 60 / validációs 20 / zárt teszt 20 (százalék) | időrendi, egybefüggő szakaszok ebben a sorrendben; a zárt teszt a legkésőbbi |
| Embargó (`embargo`) | `at_least_max_lookback_bars` | a szakaszhatároknál legalább a leghosszabb visszatekintés (sávok) hosszával kihagyott sávok |
| Mérőszámok (`metrics`) | `net_result_after_costs`, `max_drawdown`, `trade_count` | nettó eredmény költségek után, legnagyobb visszaesés, ügyletszám |
| Bootstrap (`bootstrap`) | 2000 újramintavétel, alap konfidenciaszint 95% | a mérőszámok bizonytalanságát jelzi, mint a Média-Zaj pilotban |
| Minimális ügyletszám (`min_trades`) | 30 | a zárt teszten ennél kevesebb ügyletnél a kapu `nem_szamolhato` |
| Többszörös tesztelés (`multiple_testing`) | `bonferroni_by_trials`; a próbák naplózása kötelező; a próbák száma nem csökkenhet | a konfidenciaszint a naplózott változatok számával szigorodik (lásd lent) |
| Kapu-állapotok (`states`) | `atment`, `nem_ment_at`, `eldonthetetlen`, `nem_szamolhato` | a kapu négy lehetséges kimenete |
| Szabályok (`rules`) | a zárt teszt egyszer nyitható; csendes módosítás tilos; nincs jövőbe látás | mind igaz |

**A többszörös tesztelés képlete:** a bootstrap-intervallum szintje `1 − 0,05 / n_trials`, ahol az `n_trials` a naplózott stratégiaváltozatok és paraméterkombinációk száma (legalább 1). Az `n_trials` értékét a zárt teszt megnyitása előtt rögzíteni kell, és utólag nem csökkenthető.

## NYITOTT: még nincs rögzítve (`pending`)
| Tétel | Állapot |
|---|---|
| Költség- és csúszásmodell (`cost_model`) | **nincs rögzítve**; piacfüggő, a konkrét piac kiválasztásakor, az első mentett adat előtt rögzítendő |
| Viszonyítási alapok (`benchmarks`) | **nincs rögzítve**; ugyanekkor |
| Számszerű küszöb és **döntési szabály** (`thresholds`) | **nincs rögzítve**; az, hogy mikor `atment`, `nem_ment_at`, illetve `eldonthetetlen` (a pontbecslés és az intervallum határai a küszöbhöz képest), a küszöbbel együtt rögzítendő. A Média-Zaj mintája (pontbecslés a küszöb alatt, de az intervallum felső határa eléri: eldönthetetlen) javaslat, nem rögzített |

**Mérési zár:** a `gate.measurement_ready` csak akkor ad igazat, ha az állapot `frozen`, és a három nyitott tétel mind rögzített. Ma `(False, ['cost_model', 'benchmarks', 'thresholds'])`.

## A rögzítés következményei: NYITOTT, megoldandó kérdések (nincsenek a konfigurációban, jóváhagyva nincsenek)
- **A bootstrap felbontása korlátozza a próbák számát. NYITOTT KÉRDÉS: a felhasználó az 50 próbás korlátot (2026-11-19) kifejezetten NEM erősítette meg, a dokumentum és a commit ezt nem jóváhagyottként rögzíti.** 2000 újramintavételnél a Bonferroni-szigorítás nagyjából 50 próbáig ad értelmezhető intervallum-határt (a szint `1 − 0,05 / n`, a farok így `B · 0,05 / (2n)` újramintavétel, és ez legalább 1 kell legyen). 50 fölött vagy a kapu `nem_szamolhato`, vagy az újramintavétel számát kell emelni. Ez **nem** része a rögzítésnek, a konfigurációban nincs, és a kapumotor megírása előtt döntést igényel.
- **A mérési kapu zárva marad** (`measurement_ready` hamis), amíg a költségmodell, a viszonyítási alapok, a küszöb és a döntési szabály nincs rögzítve; a mentés ezeket és a nyitott módszertani kérdéseket nem hagyja jóvá.
- A felosztás **pontos indexképlete** (kerekítés a sávszám nem osztható arányainál) a kapumotor megírásakor rögzítendő; a százalékok és az embargó-szabály rögzítettek.

## Módosítás a rögzítés után
Csendes módosítás nincs. Egy változtatás csak a felhasználó **kifejezett jóváhagyásával** történhet, és együtt jár: (1) bejegyzés a `gate_config.json` `changes` listájába (dátum, mi változott, ki hagyta jóvá, az **első mérés előtt** történt-e), (2) a hash frissítése ebben a dokumentumban és a tesztben, (3) a jelentésben és a kapu kimenetében jelölt, utólagos változtatásként. (A Média-Zajban a kapu `min_voters` értékét utólag, az eredmények ismeretében módosították; ez volt a minta arra, hogy az ilyet jelezni kell.)

## Rögzítés a mérés előtt (a hátralévő lépések)
1. A konkrét piac kiválasztása.
2. A költség- és csúszásmodell, a viszonyítási alapok, a küszöb és a döntési szabály jóváhagyása és rögzítése (`status` → `frozen`).
3. Lezárási jegyzék (`results/` alatt, git nem követi): az adatfájlok SHA-256 értéke, a felosztás határai, az `n_trials`, a mag és a konfiguráció hash-e.
4. A backtest-motor csak érvényes lezárási jegyzékkel és `measurement_ready` igaz értékkel indulhat; a zárt teszt megnyitása egyszer történhet, és a jegyzék rögzíti.
