# Minimális szintetikus szimulátor: specifikáció

**Állapot:** a 9. pont hét választását a felhasználó 2026-11-19-én jóváhagyta, **kizárólag a szintetikus szimulátor feltevéseiként**. Ez **nem piaci végrehajtási modell**, és nem engedély valódi adatos értékelésre. A mérési kapu zárva marad. Solaris- és Média-Zaj-integráció nincs.
Megvalósítás: `trading_model/simulator.py`, tesztek: `trading_model/tests/test_simulator.py`.

**Felülvizsgálat utáni javítások (2026-11-19):** a független kódfelülvizsgálat nyomán a stratégia Decimal-kontextusa elkülönül a motorétól (`strategy_error`), a `simulate` a belépési ponton a teljes adatszerződést kikényszeríti (`input_contract`), a paraméterfeldolgozás független a hívó kontextusától és ábrázolási korlátot kapott, a paraméter-előellenőrzés határa pontosítva lett (6. pont), a negatív számláló indoklása javítva (5. pont), és a stratégia megbízható callback-jellege kimondva (1. pont). A szabályok jelentése (szigorú `>`, előtag-szabály, nyitóár-teljesítés) nem változott.

**Cél:** kizárólag a működés ellenőrzése szintetikus adaton. Nem kereskedési előny bizonyítása. A kimenete nem kapu-bemenet, és nem optimalizálható.

## 0. Keretek
- Egy eszköz, csak long/flat, piaci megbízás, tőkeáttétel nélkül. Nincs MOC, limit, stop, megbízás-visszavonás, same-bar teljesítés, rövid pozíció.
- Csak `synthetic: true` és `SYN-` jelölésű idősor. A `simulate` a belépési ponton a **teljes bemeneti adatszerződést** kikényszeríti a közvetlenül létrehozott `Series` esetén is (7. pont), nem csak a `load_series` útján érkezőnél. Hibás bemenet: egységes, dokumentált `SimulationError` (`input_contract`, `input_not_synthetic`, `input_symbol`, `input_overlap`), nem nyers `IndexError` vagy `KeyError`.
- **A szigorú `>` teljesítési szabály és az előtag-szabály (hatékony elérhetőség) szimulációs feltevés, nem elfogadott piaci végrehajtási modell.** A „nyitón teljesül" sem piaci állítás, csak a szimuláció kerete.
- Minden paraméter kötelező, nincs rejtett alapérték.
- Determinisztikus. Nincs hálózat, szolgáltató, kulcs. A véletlen csak a generátor `seed`-je.

## 1. A stratégia és a motor szerepe
- A stratégia egy tiszta függvény: `stratégia(nézet) → "LONG" | "FLAT" | None`. A `None` jelentése „nincs váltás".
- A **nézet** a döntés pillanatában látható sávok **változtathatatlan sorozata** (nyitó, csúcs, mélypont, záró, forgalom, időbélyeg). A stratégia **nem kap** teljesítési árat, számlaállapotot (készpénz, pozíció, függő megbízás), megbízás-információt, döntési időt vagy jövőbeli adatot.
- A cél és a tényleges/vetített állapot összevetése, a megbízás létrehozása és minden számolás a **motor** feladata.
- Más visszatérési érték: blokkoló hiba (`strategy_target`). A cél pontosan `str` típusú (`LONG` vagy `FLAT`) kell legyen: egy `str`-alosztály, amelynek az egyenlőség-vizsgálata felülírt, nem fogadható el.
- **A stratégia megbízható, folyamaton belüli visszahívás (callback).** A nézet korlátozása (változtathatatlan sávok, nincs ár, számla vagy megbízás) **API-szerződés, nem biztonsági sandbox**: a stratégia ugyanabban a Python-folyamatban fut, és szándékosan rosszindulatú kód elérheti a motor belső állapotát (pl. a `ViewBar` `__dict__`-jét, a hívási keretek lokális változóit). Folyamatizolációt a szimulátor nem épít. A „nem kap" állítás tehát a jóhiszemű stratégiára vonatkozik.
- **A stratégia saját Decimal-kontextusban fut**, a motorétól és a hívóétól függetlenül: `prec=28`, `ROUND_HALF_EVEN`, csapdák: `InvalidOperation`, `DivisionByZero`, `Overflow` (nincs `Inexact` csapda). A stratégia kontextus-módosítása (precizitás, csapdák, `setcontext`) nem változtathatja meg a motor számítását, és a kilépéskor a motor kontextusa áll vissza.
- **A stratégia bármely kivétele `strategy_error`** (a részlet a kivétel típusa, az eredeti kivétel láncolva). Egy stratégia aritmetikai hibája tehát nem minősül a motor saját pontossági hibájának (`decimal_precision`).

## 2. Idő és események
**Jelölés.** `t_i` az `i`. sáv vége (`timestamp`), `dur` a `timeframe` hossza, `o_i = t_i − dur` a sáv nyitása, a sáv a `[o_i, t_i)` intervallum. Az `o_i − t_{i−1}` szünet: 0 folytonos, > 0 kereskedési szünet, **< 0 átfedés: blokkoló hiba** (`input_overlap`). A szünet és a hiányzó sáv nem különböztethető meg, szünetként kezelendő.

**Hatékony elérhetőség.** `A*_i = max(available_at_1..available_at_i)`. Egy sáv csak akkor látszik, ha minden korábbi is.

**Eseményfajták** (időbélyegenként fajtánként legfeljebb egy):
- `CLOSE(T)`: az a sáv, amely `T`-ben zárul. Értékelés `close` referenciaárral, a nyitási teljesítés **előtti** állományra.
- `OPEN(T)`: az a sáv, amely `T`-ben nyílik. Az itt esedékes megbízás teljesítése vagy elutasítása a sáv `open` árán.
- `OPEN_MARK(T)`: csak ha az `OPEN(T)`-ben **teljesítés** (`FILLED`) volt. Értékelés `open_ref` jelöléssel, az **aktuális nyitó** referenciaárral, a teljesítés **utáni** állományra.
- `DECISION(D)`: minden különböző `A*` értéknél, az `A*` időpontban. A nézet az összes sáv, amelynek `A*_i ≤ D`.

**Azonos időbélyeg sorrendje (kötelező):** `CLOSE` → `OPEN` → `OPEN_MARK` → `DECISION`. A döntés látja a `T`-ben történt teljesítés eredményét a vetített állapotban. A `T`-ben keletkezett megbízás `T`-n nem teljesülhet.

**Futás vége.** Az utolsó nyitás `o_n < t_n`, ezért minden teljesítés az utolsó sávzárás előtt történik, és a **záró érték az utolsó `CLOSE`**. Ha egy sáv csak az utolsó sávzárás után válik elérhetővé, a döntési esemény ekkor is létrejön az `A*` időpontban. A belőle keletkező megbízás nem teljesülhet, ezért **a létrehozásakor azonnal lejár**. Nincs külön lejáratási esemény, így döntés és lejárat sorrendje nem lehet meghatározatlan.

**Legkorábbi teljesítés.** A `D` időpontban létrehozott megbízás a legkisebb `j` sáv `o_j` nyitóján teljesül, amelyre **`o_j > D` szigorúan**. Ezt a `j*` sávot a létrehozáskor rögzíti a megbízás, és nem változik. Folytonos sávoknál a megbízás a következő nyitóra vár (`o_{i+2}`): szándékosan konzervatív. Kereskedési szünetnél a következő nyitón teljesül. Késleltetett adatnál a döntés ideje `A*`, ezért a teljesítés tovább tolódik.

## 3. Megbízás és életciklus
- **Vetített állapot:** pozíció + a függő megbízás hatása (függő `BUY` → `LONG`, függő `SELL` → `FLAT`, nincs függő → a pozíció szerint).
- **Azonos cél** a vetített állapottal (vagy `None`): **nem keletkezik új megbízás**, nincs probléma-jelzés.
- **Eltérő cél, nincs függő megbízás:** új megbízás (`BUY` ha `LONG`, `SELL` ha `FLAT`).
- **Ellentétes cél függő megbízás mellett:** a megbízás-visszavonás nincs a keretben, ezért a függő megbízás **változatlanul marad**, az újat a rendszer `REJECTED(opposite_while_pending)` állapotban rögzíti a probléma-listában.
- Egyszerre legfeljebb egy függő megbízás.
- **Állapotok:** `PENDING` → `FILLED` | `REJECTED(ok)` | `EXPIRED(end_of_data)`.
- **Létrehozáskor** nincs `j*` (nincs `o_j > D` sáv): a megbízás azonnal `EXPIRED(end_of_data)`, hatás nélkül.
- **Teljesítéskor elutasítás:** `insufficient_cash` (vétel, `q` = 0), `fee_exceeds_cash` (eladás, `készpénz + N − díj < 0`; a pozíció változatlan). Minden elutasítás a probléma-listába kerül (azonosító, ok, ár, készpénz).
- **Elutasítás után nincs automatikus újrapróba és nincs csendes méretcsökkentés.** Az elutasított vagy lejárt megbízás lezárt, nem blokkol. Egy **későbbi döntési eseményen** az ismételt cél **új megbízást** hozhat létre, ha eltér az akkori vetített állapottól (elutasítás után a vetített állapot változatlan, tehát az ismételt cél eltér, és új megbízás keletkezik). Ha azonos a vetített állapottal, nem keletkezik.
- **Megbízás szándéka** (azonosító, irány, `D`, cél, `j*`) a létrehozáskor rögzül, és nem függ a jövőbeli áraktól. A teljesítés ára és mennyisége a teljesítéskor számolódik.

## 4. Elszámolás
- **Vétel:** `p = open·(1+s)`, `N = q·p`, `díj = r·N + f`, a készpénz csökken `N + díj`-jal.
- **Eladás:** `p = open·(1−s)`, `N = q·p`, `díj = r·N + f`, a készpénz nő `N − díj`-jal.
- `s`, `r`, `f`: szintetikus tesztértékek, nem piaci becslések, nem bizonyíték.

## 5. Számábrázolás és méretezés
**Konverzió.** A JSON-ból érkező szám: `float` esetén `Decimal(repr(x))` (nem `Decimal(x)`), `int` esetén `Decimal(x)`. Paraméter csak `str`, `int` vagy `Decimal` lehet, a `float` és a `bool` `param_type` hiba. A paraméterek feldolgozása a motor saját kontextusában történik (nem a hívó globális kontextusában), így a hívó csapdabeállításai nem változtatják meg az eredményt.

**Helyi kontextus** (a globális kontextus nem változik): `decimal.Context(prec=60, rounding=ROUND_HALF_EVEN, traps=[InvalidOperation, DivisionByZero, Overflow, Inexact], Emin=−999999, Emax=999999)`. Az `Inexact` csapda miatt **semmilyen műveletet nem kerekít a rendszer**: ha egy művelet nem pontos, blokkoló hiba (`decimal_precision`). A kiírás szöveg (`format(d, 'f')`), nem `float`.

**Vételi mennyiség** (nincs osztás, csak a lefelé vágó egész osztás `//`):
- Ha `készpénz − f ≤ 0`: `q = 0`. Ez az ág explicit védelem az olvashatóságért, **viselkedésileg egyenértékű** az elhagyásával: negatív számlálónál a `Decimal` `//` a nulla felé csonkít (pl. `−5 // 3 = −1`), így a `q` ekkor nem pozitív, tehát kisebb `u`-nál, és a vétel úgyis `insufficient_cash`. Az ág elhagyása nem változtat semmilyen eredményen (a tesztek ezt egyenértékű mutánsként igazolják, nem hibaként kezelik).
- Különben `k = (készpénz − f) // (p·(1+r)·u)`, `q = k·u`.
- Ha `q < u`: `REJECTED(insufficient_cash)`.

**Ellenőrzés a képlet után (kötelező, minden vételnél):** `terhelés = q·p + (r·q·p + f)`; ha `terhelés > készpénz`, a futás belső hibával (`sizing_violation`) leáll, nem csökkenti csendben a mennyiséget. A tesztben ezen felül `terhelés(q + u) > készpénz` (maximalitás).

## 6. Paraméterek érvényességi tartománya és az előzetes ellenőrzés határa
**Indulás előtt ellenőrzött** (bármely hiba blokkoló, a futás el sem indul, a stratégia egyszer sem hívódik): **típus**, **tartomány** és **az elfogadott ábrázolási korlát**. Hibakódok: `param_missing`, `param_unknown`, `param_type`, `param_range`.
- Pontosan az öt paraméter szerepel: `initial_cash`, `unit`, `fee_rate`, `fixed_fee`, `slippage`.
- Kulcsok (determinisztikus sorrend): először a nem `str` típusú kulcs (`param_unknown`, a részletben a típus neve), majd az ismeretlen `str` kulcs (a névsor szerinti első), majd a hiányzó. A kulcsok sorrendje a beszúrási sorrendtől nem függ, vegyes típusú kulcsokra sem keletkezik nyers kivétel.
- Típus: `str` (csak ASCII, szélén szóköz és `_` nélkül), `int` vagy `Decimal`; `float`, `bool`, más: `param_type`. Nem decimális szöveg: `param_type`.
- Végesség: `NaN` és a végtelen: `param_range`.
- **Ábrázolási korlát** (`param_range`): legfeljebb 20 értékes jegy, és a kiigazított kitevő abszolút értéke legfeljebb 30. A nulla (a negatív nulla és a nagy kitevőjű nulla is) pozitív, egyszerű nullává alakul.
- Tartomány: `initial_cash` > 0, `unit` > 0, `fee_rate` ≥ 0, `fixed_fee` ≥ 0, **0 ≤ `slippage` < 1**.
- Határesetek, amelyek érvényesek: `s = 0`, `r = 0`, `f = 0`.

**Amit az előzetes ellenőrzés NEM ígér.** Nem zárja ki előre a későbbi aritmetikai hibákat. A határon belüli paraméterekkel is keletkezhet **adatfüggő** pontossági hiba futás közben (`decimal_precision`): például 20 jegyű paraméterek és 17 jegyű árak szorzata nem fér a 60 jegyű kontextusba, és az `Inexact` csapda miatt a művelet nem kerekít, hanem blokkoló hibát ad. Az ábrázolási korlát célja, hogy a nyilvánvalóan szélsőséges értékek indulás előtt elbukjanak, nem az, hogy minden későbbi művelet pontos legyen. Ilyen hibánál nincs részeredmény.

## 7. Bemeneti adatszerződés a belépési ponton
A `simulate` a futás előtt, a közvetlenül létrehozott `Series`-re is ellenőrzi (a `data.check_bar` sáv-ellenőrzésével): `Series` típus, logikai `synthetic`, a szimbólum szabálya, ismert `timeframe`, nem üres sávsorozat, `Bar` típusú, időzónás időpontú sávok, véges pozitív árak, érvényes OHLC-összefüggés, `available_at ≥ timestamp`, szigorúan növekvő időbélyegek. Hiba: `input_contract` (mező: a hiba helye, pl. `bars[2].open`; részlet: az ok). Ezt követi a `synthetic: true` (`input_not_synthetic`), a `SYN-` előtag (`input_symbol`) és az átfedésmentesség (`input_overlap`). A `load_series` útján érkező idősor ezeken változatlanul átmegy.

## 7/b. Azonosságok (minden futásra, tesztelendő)
- **A. Készpénz-főkönyv:** `Δkészpénz = −σ·q·open − csúszás − díj`, `σ` = +1 vétel, −1 eladás, `csúszás = q·open·s`.
- **B. Pozíció:** `q_t = Σ vételi q − Σ eladási q`, `q_t ≥ 0`, `u` többszöröse.
- **C. Érték:** `V = készpénz + q·ref`, ahol `ref` a `close` (CLOSE) vagy az aktuális `open` (OPEN_MARK). A készpénz sosem negatív.
- **D. Zárt futás:** ha a végén `q = 0`: `V_vég − V_0 = −Σ σ·q·open − Σ csúszás − Σ díj`.

## 8. Kézzel levezetett példák
Mindegyiknél `timeframe` = 1d, folytonos napi sávok, `initial_cash` = 1000,00, `u` = 1. Az „`k`. nap" = `2026-01-0kT00:00:00Z`. A `k`. sáv zárása a `k`. nap, nyitása a (`k−1`). nap. `available_at = timestamp`, ha mást nem írok. A sávok `open/close` alakban.

**A. Idő, nulla költség (`s = r = f = 0`).** Sávok: 1: 100/102; 2: 104/103; 3: 105/106; 4: 108/107; 5: 110/109. Stratégia: LONG az 1. sáv után, FLAT a 3. sáv után.
- Döntés az 1. napon: `o_2` = 1. nap ✗, `o_3` = 2. nap ✓ → `j* = 3`. Döntés a 3. napon: `o_4` = 3. nap ✗, `o_5` = 4. nap ✓ → `j* = 5`.
- Vétel a 2. napon, 105-ön: `q = 9`, készpénz 55. Eladás a 4. napon, 110-en: 990, készpénz **1045**.
- Értékelések: 1. nap CLOSE **1000**; 2. nap CLOSE (a teljesítés előtt) **1000**; 2. nap OPEN_MARK (ref 105) 55 + 945 = **1000**; 3. nap CLOSE 55 + 9·106 = **1009**; 4. nap CLOSE (az eladás előtt, close 107) 55 + 963 = **1018**; 4. nap OPEN_MARK (ref 110) **1045**; 5. nap CLOSE **1045**. Záró érték **1045**.

**B. Kereskedési szünet, átfedés nélküli sávok.**

| Sáv | Nyitás (`o`) | Zárás (`t`) | open/close |
|---|---|---|---|
| 1 | 2025-12-31T00:00Z | 2026-01-01T00:00Z | 100/102 |
| 2 | 2026-01-01T00:00Z | 2026-01-02T00:00Z | 104/103 |
| 3 | 2026-01-03T00:00Z | 2026-01-04T00:00Z | 105/106 |

Intervallumok: [12-31, 01-01), [01-01, 01-02), [01-03, 01-04): nincs átfedés, a 2. és 3. sáv között 1 nap szünet.
- Stratégia: LONG a 2. sáv után, `D` = 2026-01-02. `o_3` = 01-03 > `D` → `j* = 3`, teljesítés **01-03-án a 105-ös nyitón**, nincs többletkésés. `q` = 9, készpénz 55.
- Értékelések: 01-01 CLOSE **1000**; 01-02 CLOSE **1000**; 01-03 OPEN_MARK (ref 105) **1000**; 01-04 CLOSE 55 + 9·106 = **1009**.

**C. Késleltetett adat (nulla költség).** Sávok 1–8, `open_k = 99 + k`, `close_k = open_k + 1`. A 3. sáv `available_at` = 5. nap 12:00.
- `A*`: 1. nap, 2. nap, **5,5. nap** (3., 4., 5. sáv), 6. nap, 7., 8. nap. Döntés csak ezeken van.
- A stratégia (LONG, amikor a nézetben van a 3. sáv) az 5,5. napon dönt, a nézet az 1–5. sáv. `o_6` = 5. nap ✗, `o_7` = 6. nap ✓ → `j* = 7`, teljesítés a 6. napon, 106-on: `q = 9`, készpénz **46**.
- Értékelések: 6. nap CLOSE (a teljesítés előtt) **1000**; 6. nap OPEN_MARK (ref 106) **1000**; 7. nap CLOSE **1009**; 8. nap CLOSE **1018**. Záró érték **1018**.

**D. Árrés, vételi és eladási költség.** `s` = 0,01, `r` = 0,001, `f` = 1,00. Sávok 1–7: 1: 99/100; 2: 100/101; 3: **120**/125; 4: 126/128; 5: 129/131; 6: 130/129; 7: 128/127. Stratégia: LONG az 1. sáv után, FLAT a 4. sáv után.
- **Vétel** (`j* = 3`, 2. nap): `open` = 120, `p = 121,20`. `q = 8` (terhelés 971,5696; `q = 9`: 1092,8908 ✗). `N = 969,60`, `díj = 1,9696`, készpénz **28,4304**.
- **Eladás** (a döntés a 4. napon, `j* = 6`, 5. nap): `open` = 130, `p = 128,70`, `N = 1029,60`, `díj = 2,0296`, készpénz **1056,0008**.
- Értékelések: 1. nap CLOSE **1000**; 2. nap CLOSE **1000**; 2. nap OPEN_MARK (ref 120) **988,4304**; 3. nap CLOSE **1028,4304**; 4. nap CLOSE **1052,4304**; 5. nap CLOSE (az eladás előtt) **1076,4304**; 5. nap OPEN_MARK (ref 130) **1056,0008**; 6. és 7. nap CLOSE **1056,0008**.
- **Azonosságok.** A: vételnél −(960 + 9,60 + 1,9696) = −971,5696. D: `V_vég − V_0 = 56,0008 = 8·(130 − 120) − 3,9992 (díj) − 20,00 (csúszás)`.

**E. Nem teljesülő vétel.**
- *E1:* készpénz 100,00, nyitó 150, nulla költség: `q = 0` → `REJECTED(insufficient_cash)`, készpénz 100, pozíció 0, nincs `OPEN_MARK`.
- *E2:* készpénz 100,50, `f` = 1,00, `s = r = 0`, nyitó 100: `k = 99,50 // 100 = 0` → elutasítva.
- *E3 (ismételt cél elutasítás után):* mint E1, de a stratégia minden döntéskor LONG: az 1. döntés utáni megbízás elutasítva; a következő döntési eseményen a vetített állapot FLAT, a cél LONG → **új megbízás** keletkezik (és szintén elutasítódik). Automatikus újrapróba nincs: új megbízás csak döntési eseményen jön létre.

**F. Nincs jövőbeli nyitó.** 4 folytonos sáv, LONG a 3. sáv után (`D` = 3. nap): nincs `o_j > D` sáv → a megbízás a létrehozásakor `EXPIRED(end_of_data)`. Készpénz 1000, pozíció 0, záró érték (4. nap CLOSE) **1000**.

**G. Sáv az utolsó sávzárás után válik elérhetővé.** 5 folytonos sáv (zárás az 1–5. napon). A 2. sáv `available_at` = 7. nap.
- `A*`: 1. nap, majd a 2–5. sáv mind a **7. napon**. Döntési események: 1. nap, 7. nap. CLOSE a 1–5. napon (mind **1000**).
- A stratégia (LONG, amikor a nézetben van a 2. sáv) a 7. napon dönt, a nézet az 1–5. sáv. Nincs `o_j > 7. nap` → azonnal `EXPIRED(end_of_data)`. Záró érték (5. nap CLOSE): **1000**.

**H. Eladás nulla nettó bevétellel (határeset).** `initial_cash` = 110, `f` = 10, `s = r = 0`, `u` = 1. Sávok 1–6 (open/close): 1–4: 10/10; 5: 5/5; 6: 1/1. Stratégia: LONG az 1. sáv után, FLAT a 4. sáv után.
- Vétel a 2. napon, 10-en: `k = (110 − 10) // 10 = 10`, `N = 100`, `díj = 10`, terhelés 110, készpénz **0**.
- Döntés a 4. napon: `o_5` = 4. nap ✗, `o_6` = 5. nap ✓ → eladás a 6. sáv nyitóján, 1-en: `N = 10`, `díj = 10`, bevétel 0, `készpénz + 0 = 0`, nem negatív → **teljesül**, készpénz **0**, pozíció 0.

**I. A függő eladás nem változik ellentétes céltól.** Sávok 1–8, `open_k = 99 + k`, `close_k = open_k + 1`, `s = r = f = 0`. A 3. sáv `available_at` = 5,5. nap, a 4. sáv 5,8. nap. Stratégia (a nézet hossza szerint): 1 → LONG, 3 → FLAT, 5 → LONG.
- Vétel a 2. napon, 102-n: `q = 1000 // 102 = 9`, készpénz 82.
- Döntés az 5,5. napon (nézet: 1–3. sáv): FLAT, az eladás `j*` = 7. sáv (`o_7` = 6. nap).
- Döntés az 5,8. napon (nézet: 1–5. sáv): LONG, ellentétes a függő eladással → `REJECTED(opposite_while_pending)`. Az eredeti eladás szándéka (`j*` = 7) változatlan, teljesül a 6. napon 106-on: 9·106 = 954, készpénz **1036**, pozíció 0.

## 9. Elfogadási tesztlista
1. **Sorrend:** `CLOSE → OPEN → OPEN_MARK → DECISION` (A példa 2. napja). Fajtánként legfeljebb egy esemény időbélyegenként.
2. **Szigorú `>`:** folytonos sávoknál egy sávval későbbi teljesítés (A), szünetnél a következő nyitó (B); a B példa sávjainak átfedés-mentessége.
3. **Késleltetett adat** (C); nem monoton `available_at` esetén az előtag-szabály.
4. **Futás vége:** F és G; a döntés és a lejárat sorrendje meghatározott; a záró érték az utolsó CLOSE.
5. **Stratégia-szerződés:** a nézet változtathatatlan; a stratégia nem kap teljesítési árat, számlaállapotot vagy jövőbeli adatot; érvénytelen cél blokkoló hiba.
6. **Jövőbeli ár (5a):** olyan döntések és megbízás-szándékok, amelyek **a módosított adat elérhetővé válása előtt** keletkeztek (`D < A*` a módosított sávra), változatlanok. A későbbi napló nem része az elvárásnak.
7. **Jövőbeli ár (5b, külön):** ha a teljesítési sáv `open` ára változik, a teljesítés ára és mennyisége a képlet szerint változik, és az A–D azonosságok fennmaradnak.
8. **Decimal:** `Decimal(repr(0.1))`; `float` paraméter elutasítva; az `Inexact` csapda blokkoló hibát ad; a méretezésben nincs osztás; a globális kontextus változatlan.
9. **Méretezés:** lefelé az egységre (`u` = 1 és 0,5), `készpénz − f ≤ 0` → `q = 0`; terhelés ≤ készpénz minden vételnél (véletlen szintetikus idősorokon); maximalitás; `sizing_violation` kiváltása.
10. **Paraméterek:** minden érvénytelen érték blokkoló hiba, a futás el sem indul; a határesetek érvényesek.
11. **Függő megbízás:** azonos cél nem hoz új megbízást; ellentétes cél függő mellett `opposite_while_pending`, a függő megbízás változatlanul teljesül; egyszerre legfeljebb egy függő megbízás.
12. **Elutasítás után** (E1, E2, E3): nincs automatikus újrapróba; későbbi döntési eseményen az ismételt cél új megbízást hoz, ha eltér a vetített állapottól; ha azonos, nem. `fee_exceeds_cash` külön.
13. **Értékelések:** a `close` és `open_ref` jelölés külön; `OPEN_MARK` csak teljesítés után.
14. **Azonosságok A–D** véletlenszerű szintetikus idősorokon; a készpénz sosem negatív.
15. **Példák A–G** fixtúraként, pontos `Decimal`-egyezéssel.
16. **Determinizmus**, **bemenet** (`synthetic: false`, átfedés, nem `SYN-`), **hálózati zár**.
17/b. **Felülvizsgálat utáni regressziók:** a stratégia kontextus-módosítása nem változtatja a motor számítását, és a stratégia saját alapértelmezett kontextust kap; a stratégia `Decimal`-osztása nem motorhiba; a stratégia hibája `strategy_error`; `str`-alosztályú cél elutasítva; a közvetlenül épített `Series` hibái (lookahead, üres, ismeretlen időkeret, `NaN`/nulla/negatív/végtelen ár, naiv időpont, azonos és nem növekvő időbélyeg, `Decimal` ár, rossz szimbólum, nem logikai `synthetic`, nem `Series`) `input_contract`; a túl pontos paraméter (jegy- és kitevőkorlát) indulás előtt `param_range`; vegyes és ismeretlen kulcsok determinisztikusan `param_unknown`; a hívó kontextusa nem befolyásolja a feldolgozást; nem ASCII számjegy `param_type`; a negatív nulla nem jelenik meg a kimenetben.
17/c. **Hiányzó tesztek pótlása:** eladás nulla nettó bevétellel teljesül (H); az eladás-elutasítás utáni függőállapot-törlés, vagyis a következő döntés új megbízást hozhat; az eredeti függő eladás változatlansága ellentétes cél mellett (I); nem monoton elérhetőség kézi példával és véletlen mintákon, a döntési időkre, nézethosszra, `j*`-ra, a teljesítés idejére és referenciaárára a szimulátor kódjától független (lineáris keresésű) újraszámolással; a `sizing_violation` védelem **célzott hibainjektálással** egy eldobható másolaton (a helyes aritmetika nem gyengül); az egyenértékű mutáns (`cash − f ≤ 0` ág) nem változtat eredményt, ezért nem teszthiba.
17. **Mutációs próbák** (mindegyiknek el kell buknia legalább egy teszten): a `>` helyett `≥`, a méretezés a döntéskori árral, a díj kihagyása a méretből, az `A*` helyett `available_at`, a CLOSE és a teljesítés sorrendjének felcserélése, az `Inexact` csapda kikapcsolása, az azonnali lejárat helyett késői lejáratás, a vetített állapot figyelmen kívül hagyása.

## 10. Ami nincs eldöntve
A piac, a valós költségmodell, a viszonyítási alapok, a küszöbök, a statisztikai protokoll megoldatlan részei (a „próba" fogalma, a bootstrap típusa és blokkhossza, az 50 próbás korlát) és a valós adatos mérés. A szimulátor ezekhez nem ad bemenetet.
