# Kutatási kérdés és kapu (TERVEZET: nincs rögzítve, a felhasználó jóváhagyására vár)

**Ez a dokumentum javaslat.** Egyik érték sem rögzített és nem jóváhagyott. A rögzítés (lezárási jegyzék) az első backtest előtt történik, és onnantól csak jelölt, jóváhagyott kivétellel módosítható (lásd `SZABALYOK.md`).

## Kutatási kérdés (javaslat)
Egy **előre, a mérés előtt megadott** jelgenerátor-szabály egy **zárt, időben a tanítás után álló** teszttartományon, **költségekkel és csúszással** megáll-e a rögzített kapun, úgy, hogy a hangolás a teszttartományt nem látta?

Ez megvalósíthatósági kérdés, nem hozamígéret: a Média-Zaj pilotja is azt vizsgálta, hogy a módszer működik-e, nem azt, hogy mennyire pontos.

## Nem cél
Hozam- vagy nyereségígéret, befektetési tanács, éles kereskedés, a piac „előrejelzése", és bármi, ami szintetikus adaton mérne teljesítményt.

## Rögzítendő paraméterek (javaslat, jóváhagyásra vár)
| Paraméter | Javaslat | Állapot |
|---|---|---|
| Adatfelosztás | időrendi tanító / validációs / zárt teszt (javaslat 60 / 20 / 20), a határoknál embargó legalább a leghosszabb visszatekintés hosszával; a zárt teszt egyszer nyitható | **nincs rögzítve** |
| Költség és csúszás | piacfüggő; **nem tudok javasolni, a te adatod kell** (jutalék, spread, csúszás, csak papíron) | **nincs rögzítve** |
| Viszonyítási alapok | „vegyél és tarts" és véletlen jelek ugyanazzal a költségmodellel | **nincs rögzítve** |
| Mérőszámok | nettó eredmény költségek után, legnagyobb visszaesés (drawdown), ügyletszám; a bizonytalanságot bootstrap 95%-os intervallum jelzi (mint a pilotban) | **nincs rögzítve** |
| Minimális ügyletszám | javaslat: legalább 30 a zárt teszten; kevesebbnél `nem_szamolhato` | **nincs rögzítve** |
| Többszörös tesztelés | a próbált változatok és paraméterek számát naplózni kell, és a kapu ezt figyelembe veszi (a módszert a rögzítéskor kell kiválasztani) | **nincs rögzítve** |
| Kapu küszöbei | **nincs javaslatom számmal**: a küszöböt a költségmodell és a viszonyítási alapok ismeretében, de az eredmények ismerete **előtt** kell megadni | **nincs rögzítve** |

## A kapu kimenete (javaslat)
`atment`, `nem_ment_at`, `eldonthetetlen` (a pontbecslés a küszöb alatt, de a bootstrap-intervallum felső határa eléri), és külön `nem_szamolhato` (kevés adat vagy ügylet). A Média-Zaj kapujának mintájára a kimenet külön jelzi, ha a rögzítés óta bármi módosult.

## Rögzítés menete (javaslat)
1. A felhasználó jóváhagyja a fenti táblázat értékeit.
2. Lezárási jegyzék (`results/` alatt, git nem követi): az adatfájlok SHA-256 értéke, a felosztás határai, a költségmodell, a küszöbök, a mag és a konfiguráció hash-e.
3. A backtest-motor csak érvényes lezárási jegyzékkel indulhat; ha a jegyzék és a bemenet eltér, a kapu elzár.
4. A zárt teszt megnyitása egyszer történhet meg, és a jegyzék rögzíti.

## Nyitott döntések (tőled)
A költség- és csúszásmodell, a viszonyítási alapok, a mérőszámok és a küszöbök, valamint hogy melyik piacra szóljon az első mentett adat. Addig a modul csak az adatszerződést és a szintetikus eszköztárat tartalmazza.
