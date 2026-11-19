# Minimális szintetikus szimulátor: terv (TERVEZET, nincs megépítve, nincs elfogadva)

Állapot: javaslat. A szimulátor megépítése külön jóváhagyást kér. A mérési kapu zárva marad; a szimulátor kimenete nem kapu-bemenet és nem teljesítményállítás.
Cél kizárólag a működés ellenőrzése szintetikus adaton (`SYN-` jelölés). Kereskedési előny bizonyítására nem használható.
Solaris és Média-Zaj itt nem szerepel; később külön adatforrásként, saját adatszerződési bejegyzéssel.

## 1. Eseménysorrend azonos időbélyegnél

Jelölés: a `t` időbélyegű sáv vége = a következő sáv nyitásának időpontja, ha a sávok folytonosak (pl. 24/7 piac); ülésszakos (napi) adatnál a következő nyitás későbbi, mint a sáv vége.

Javasolt kötelező sorrend, azonos `T` időbélyegen belül:

1. **Elérhetővé válás.** Csak az az adat számít elérhetőnek, amelynek `available_at <= T`. Az ismeretlen `available_at` adat nem használható.
2. **Korábban leadott megbízások teljesítése.** Csak olyan megbízás teljesülhet, amelyet *szigorúan korábbi* döntés hozott. A teljesítés az árát az adott nyitóból veszi, amely időben nem előzheti meg a döntés idejét.
3. **Döntés.** A stratégia csak az 1. lépés utáni adatot látja. Az itt leadott megbízás `T`-n nem teljesülhet.
4. **Értékelés (mark).** A számla értékelése az 1–3. lépés után.

Következmény folytonos sávoknál: ha a döntés `T`-n történik, és a következő nyitó is `T`-n van, akkor a nyitóár a döntéssel azonos időpontú, tehát nem érhető el késleltetés nélkül. **Javasolt alapszabály:** az ilyen megbízás nem teljesülhet az azonos időpontú nyitón; a következő *szigorúan későbbi* teljesítési eseményre vár. Ezt a késleltetést külön paraméterként kell rögzíteni, ha később lazítani akarjuk. Ülésszakos adatnál (a következő nyitó szigorúan később van) a következő nyitó megengedett lenne.

**Döntésre vár:** (a) elfogadjuk-e az alapszabályt; (b) milyen a késleltetés paramétere; (c) mi számít „teljesítési eseménynek" a valós adat piacán (aukció vagy első ügylet). A MOC és a same-bar teljesítés az első változatban elutasított.

Szükséges tesztek (a megépítéskor): a döntés nem látja a teljesítési sávot; az `available_at` a döntés és a teljesítés közé eső adatnál a következő döntésre vár; mutációs próba (az adat eltolása megváltoztatja az eredményt).

## 2. „Teljes pozíció" jelentése

Javasolt meghatározás: a pozícióméret a **teljesítéskor** rendelkezésre álló készpénzből számolódik, a teljesítési árral és az összes vételi költséggel együtt, lefelé kerekítve. Nincs tőkeáttétel, nincs rövid pozíció, nincs rejtett hitel.

- Vételkor: `q = a legnagyobb megengedett mennyiség, amelyre q * ár_teljesítés + költség(q) <= készpénz` a teljesítés pillanatában. A költség (jutalék, csúszás, egyéb) a mennyiség meghatározásába beleszámít, nem utólag vonódik le.
- Ha `q` kisebb, mint a legkisebb mennyiség (egység vagy lot), a megbízás nem teljesül, és a hiányt a probléma-lista rögzíti (nem csendben nulla).
- A készpénz egyetlen pillanatban sem lehet negatív. Ez a számlaazonosság része, és tesztelendő.
- Eladáskor: a teljes pozíció zárul, a bevétel a költségek levonásával kerül a készpénzhez.
- Az árfolyamrés (gap) miatt a döntéskori ár nem használható méretezésre; a méret mindig a teljesítési árral készül.

**Döntésre vár:** az egység oszthatósága (egész darab vagy törtrész) a piactól függ; a legkisebb mennyiség; a költségmodell értékei (nyitott, nem rögzítettek). A szimulátor tesztértékei „nem bizonyíték" jelölésűek.

## 3. Ami nyitva marad (nem dönthető el a meglévő információkból)

A statisztikai protokoll megoldatlan részei nyitottak: a „próba" fogalma, a bootstrap típusa és blokkhossza, az egy- vagy kétoldalas teszt, az 50 próbás korlát. A `gate_config.json` meglévő rögzítése nem jelent módszertani alkalmasság-igazolást. A piac, a költségmodell, a viszonyítási alapok és a küszöbök a valós adatos szakaszhoz tartoznak.
